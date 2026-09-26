from app.core.tracing import traced
from app.services.deterministic_recommendations import deterministic_recommendations

from collections.abc import Awaitable, Callable
import logging
import json
import re
from typing import Any
from uuid import UUID
from pydantic import ValidationError

from app.agents import ClaimGeneratorAgent, CriticAgent, ReportAgent, VisualizationAgent
from app.agents.analyst import AnalystAgent, NumericGroundingError
from app.core.analysis_constants import MAX_CHARTS_PER_RUN, MAX_CLAIMS_PER_RUN, SUPPORTED_CHART_TYPES
from app.core.exceptions import AnalysisRunNotFoundError, ReportNotFoundError
from app.models.chart_spec import ChartSpec
from app.models.claim import Claim
from app.models.claim_review import ClaimReview
from app.models.report import Report
from app.repositories.analysis_run_repository import AnalysisRunRepository
from app.repositories.chart_repository import ChartRepository
from app.repositories.claim_repository import ClaimRepository
from app.repositories.claim_review_repository import ClaimReviewRepository
from app.repositories.evidence_repository import EvidenceRepository
from app.repositories.report_repository import ReportRepository
from app.schemas.chart import ChartRecommendation, VisualizationOutput
from app.schemas.claim import ClaimGenerationOutput
from app.schemas.claim_review import ClaimEvaluation
from app.schemas.llm import LLMResult
from app.schemas.report import FinalReportOutput

AgentRunner = Callable[[str, dict[str, Any], Callable[[], Awaitable[LLMResult]]], Awaitable[LLMResult]]
CAUSAL_PATTERN = re.compile(r"\b(cause[ds]?|causing|led to|drives?|resulted in|because of)\b", re.IGNORECASE)
VISUAL_REQUEST_PATTERN = re.compile(r"\b(chart|graph|plot|visuali[sz](?:e|ation)|bar|line|pie|donut|scatter|histogram|boxplot|heatmap|waterfall)\b", re.IGNORECASE)
logger = logging.getLogger(__name__)


class AnalysisOutputFailure(Exception):
    def __init__(self, code: str, detail: str | None = None) -> None:
        self.code = code
        self.detail = detail
        super().__init__(f"{code}: {detail}" if detail else code)

class AnalysisOutputService:
    def __init__(self, session, llm_service) -> None:
        self.session = session
        self.runs = AnalysisRunRepository(session)
        self.evidence_repo = EvidenceRepository(session)
        self.claims = ClaimRepository(session)
        self.reviews = ClaimReviewRepository(session)
        self.charts = ChartRepository(session)
        self.reports = ReportRepository(session)
        self.claim_agent = ClaimGeneratorAgent(llm_service)
        self.critic_agent = CriticAgent(llm_service)
        self.visualization_agent = VisualizationAgent(llm_service)
        self.report_agent = ReportAgent(llm_service)
        self.claim_models: dict[str, Claim] = {}

    async def generate_claims(self, *, run, evidence: list[dict[str, Any]], validations: list[dict[str, Any]], run_agent: AgentRunner) -> list[dict[str, Any]]:
        async def invoke(): return await self.claim_agent.run(provider=run.llm_provider, query=run.query, evidence=evidence, validations=validations)
        result = await run_agent("claim_generator", {"query": run.query, "evidence": evidence, "statistical_validations": validations}, invoke)
        try:
            output = ClaimGenerationOutput.model_validate(result.content)
        except ValidationError as exc:
            raise AnalysisOutputFailure("CLAIM_VALIDATION_FAILED") from exc
        evidence_map = {item["evidence_code"]: item for item in evidence}
        codes = [item.claim_code for item in output.claims]
        if not output.claims or len(output.claims) > MAX_CLAIMS_PER_RUN or len(codes) != len(set(codes)):
            raise AnalysisOutputFailure("CLAIM_VALIDATION_FAILED")
        persisted_evidence = {item.evidence_code: item for item in await self.evidence_repo.list_for_run(run.id)}
        models: list[Claim] = []
        dto: list[dict[str, Any]] = []
        for candidate in output.claims:
            refs = candidate.evidence_codes
            if any(code not in evidence_map or code not in persisted_evidence for code in refs) or (candidate.claim_type != "limitation" and not refs):
                raise AnalysisOutputFailure("CLAIM_VALIDATION_FAILED")
            linked_stats = [item for item in validations if item.get("evidence_code") in refs]
            try:
                AnalystAgent._validate_numeric_grounding(candidate.claim_text, {"evidence": [evidence_map[code] for code in refs], "statistics": linked_stats})
            except NumericGroundingError as exc:
                raise AnalysisOutputFailure("CLAIM_VALIDATION_FAILED") from exc
            model = Claim(analysis_run_id=run.id, claim_code=candidate.claim_code, claim_text=candidate.claim_text, claim_type=candidate.claim_type, status="pending_review")
            model.evidence_items = [persisted_evidence[code] for code in refs]
            models.append(model)
            dto.append({**candidate.model_dump(mode="json"), "status": "pending_review"})
        try:
            await self.claims.create_many(models); await self.session.commit()
        except Exception as exc:
            await self.session.rollback(); raise AnalysisOutputFailure("CLAIM_PERSISTENCE_FAILED") from exc
        self.claim_models = {model.claim_code: model for model in models}
        return dto

    @traced("fallback.claims")
    async def generate_fallback_claims(self, *, run, evidence: list[dict[str, Any]]) -> list[dict[str, Any]]:
        persisted_evidence = {item.evidence_code: item for item in await self.evidence_repo.list_for_run(run.id)}
        models, dto = [], []
        for index, item in enumerate(evidence[:MAX_CLAIMS_PER_RUN], 1):
            code = item["evidence_code"]
            if code not in persisted_evidence:
                continue
            claim_code = f"C{index}"
            text = item["interpretation"]
            model = Claim(analysis_run_id=run.id, claim_code=claim_code, claim_text=text, claim_type="descriptive", status="pending_review")
            model.evidence_items = [persisted_evidence[code]]
            models.append(model)
            dto.append({"claim_code": claim_code, "claim_text": text, "claim_type": "descriptive", "evidence_codes": [code], "status": "pending_review"})
        if not models:
            raise AnalysisOutputFailure("CLAIM_GENERATION_FAILED", "No persisted evidence was available for deterministic claim fallback.")
        try:
            await self.claims.create_many(models); await self.session.commit()
        except Exception as exc:
            await self.session.rollback(); raise AnalysisOutputFailure("CLAIM_PERSISTENCE_FAILED") from exc
        self.claim_models = {model.claim_code: model for model in models}
        return dto

    async def review_claims(self, *, run, claims: list[dict[str, Any]], evidence: list[dict[str, Any]], validations: list[dict[str, Any]], quality_warnings: list[dict[str, Any]], run_agent: AgentRunner) -> tuple[list[dict[str, Any]], list[dict[str, Any]]]:
        evidence_map = {item["evidence_code"]: item for item in evidence}
        accepted, reviews, review_models = [], [], []
        if not self.claim_models:
            self.claim_models = {item.claim_code: item for item in await self.claims.list_for_run(run.id)}
        for claim in claims:
            linked = [evidence_map[code] for code in claim["evidence_codes"]]
            linked_stats = [item for item in validations if item.get("evidence_code") in claim["evidence_codes"]]
            async def invoke(claim=claim, linked=linked, linked_stats=linked_stats):
                return await self.critic_agent.run(provider=run.llm_provider, query=run.query, claim=claim, evidence=linked, validations=linked_stats, quality_warnings=quality_warnings)
            result = await run_agent(f"critic:{claim['claim_code']}", {"query": run.query, "claim": claim, "supporting_evidence": linked, "linked_statistical_validations": linked_stats, "data_quality_warnings": quality_warnings}, invoke)
            try:
                evaluation = ClaimEvaluation.model_validate(result.content)
            except ValidationError as exc:
                raise AnalysisOutputFailure("CRITIC_VALIDATION_FAILED") from exc
            if evaluation.claim_code != claim["claim_code"]:
                raise AnalysisOutputFailure("CRITIC_VALIDATION_FAILED")
            wording = evaluation.corrected_wording or claim["claim_text"]
            try:
                AnalystAgent._validate_numeric_grounding(wording, {"evidence": linked, "statistics": linked_stats})
            except NumericGroundingError as exc:
                raise AnalysisOutputFailure("CRITIC_VALIDATION_FAILED") from exc
            if evaluation.status == "accepted" and CAUSAL_PATTERN.search(wording) and any(item.get("method") in {"calculate_correlation", "pearson", "spearman"} for item in [*linked, *linked_stats]):
                raise AnalysisOutputFailure("CRITIC_VALIDATION_FAILED")
            if evaluation.status == "accepted" and re.search(r"\bsignificant\b", wording, re.IGNORECASE) and any(item.get("is_significant") for item in linked_stats) and not any(item.get("effect_size") is not None for item in linked_stats):
                raise AnalysisOutputFailure("CRITIC_VALIDATION_FAILED")
            model = self.claim_models[claim["claim_code"]]
            review = ClaimReview(claim_id=model.id, analysis_run_id=run.id, status=evaluation.status, evidence_strength=evaluation.evidence_strength, issues=evaluation.issues, missing_analysis=evaluation.missing_analysis, corrected_wording=evaluation.corrected_wording)
            review_models.append(review)
            model.status = evaluation.status
            review_dto = evaluation.model_dump(mode="json"); reviews.append(review_dto)
            if evaluation.status == "accepted": accepted.append({**claim, "status": "accepted", "validated_text": wording, "evidence_strength": evaluation.evidence_strength})
        try:
            self.session.add_all(review_models)
            await self.session.flush()
            await self.session.commit()
        except Exception as exc:
            await self.session.rollback()
            raise AnalysisOutputFailure("CRITIC_VALIDATION_FAILED") from exc
        return reviews, accepted

    @traced("fallback.review")
    async def accept_fallback_claims(self, *, run, claims: list[dict[str, Any]]) -> tuple[list[dict[str, Any]], list[dict[str, Any]]]:
        if not self.claim_models:
            self.claim_models = {item.claim_code: item for item in await self.claims.list_for_run(run.id)}
        reviews, accepted, models = [], [], []
        for claim in claims:
            model = self.claim_models[claim["claim_code"]]
            model.status = "accepted"
            review = ClaimReview(claim_id=model.id, analysis_run_id=run.id, status="accepted", evidence_strength="moderate", issues=["Language-model critique was unavailable; deterministic evidence grounding was retained."], missing_analysis=[], corrected_wording=None)
            models.append(review)
            reviews.append({"claim_code": claim["claim_code"], "status": "accepted", "evidence_strength": "moderate", "issues": review.issues, "missing_analysis": [], "corrected_wording": None})
            accepted.append({**claim, "status": "accepted", "validated_text": claim["claim_text"], "evidence_strength": "moderate"})
        try:
            self.session.add_all(models); await self.session.flush(); await self.session.commit()
        except Exception as exc:
            await self.session.rollback(); raise AnalysisOutputFailure("CRITIC_VALIDATION_FAILED") from exc
        return reviews, accepted

    async def create_charts(self, *, run, claims: list[dict[str, Any]], evidence: list[dict[str, Any]], columns: list[dict[str, Any]], run_agent: AgentRunner) -> list[dict[str, Any]]:
        relevant_codes = {code for claim in claims for code in claim["evidence_codes"]}
        relevant_evidence = [item for item in evidence if item["evidence_code"] in relevant_codes]
        async def invoke(): return await self.visualization_agent.run(provider=run.llm_provider, query=run.query, claims=claims, evidence=relevant_evidence, columns=columns)
        result = await run_agent("visualization", {"query": run.query, "accepted_claims": claims, "supporting_evidence": relevant_evidence, "dataset_columns": columns}, invoke)
        try:
            output = VisualizationOutput.model_validate(result.content)
        except ValidationError as exc:
            raise AnalysisOutputFailure("CHART_SPEC_INVALID", f"Visualization response schema failed: {exc}") from exc
        requested = [item for item in output.charts if item.needed]
        # Apply data-aware defaults even when the model habitually requests a bar.
        if not re.search(r'\b(pie|donut|bar|line|scatter|histogram|boxplot|heatmap|waterfall)\b', run.query, re.I):
            for index, chart in enumerate(requested):
                if chart.chart_type not in {"bar", "horizontal_bar"} or len(chart.evidence_codes) != 1:
                    continue
                source = [item for item in evidence if item["evidence_code"] in chart.evidence_codes]
                preferred = self._fallback_chart(run.query, source)
                if preferred is not None:
                    requested[index] = preferred
        if not requested and VISUAL_REQUEST_PATTERN.search(run.query):
            fallback = self._fallback_chart(run.query, relevant_evidence)
            if fallback is not None:
                requested = [fallback]
                logger.info(
                    "Created deterministic chart fallback analysis_run_id=%s chart_type=%s evidence_codes=%s",
                    run.id,
                    fallback.chart_type,
                    fallback.evidence_codes,
                    extra={
                        "analysis_run_id": str(run.id),
                        "chart_type": fallback.chart_type,
                        "evidence_codes": fallback.evidence_codes,
                        "fallback_reason": "Explicit visualization request received an empty model recommendation.",
                    },
                )
        represented = {code for chart in requested for code in chart.evidence_codes}
        for item in evidence:
            if item["evidence_code"] in represented:
                continue
            fallback = self._fallback_chart(run.query, [item])
            if fallback is not None:
                requested.append(fallback)
                represented.update(fallback.evidence_codes)
        if len(requested) > 1:
            logger.info(
                "Prepared multiple evidence-backed charts analysis_run_id=%s chart_count=%s evidence_codes=%s",
                run.id,
                len(requested),
                sorted(represented),
                extra={"analysis_run_id": str(run.id), "chart_count": len(requested), "evidence_codes": sorted(represented)},
            )
        return await self._persist_charts(run, requested, evidence, columns)

    @traced("fallback.charts")
    async def create_fallback_charts(self, *, run, claims: list[dict[str, Any]], evidence: list[dict[str, Any]], columns: list[dict[str, Any]]) -> list[dict[str, Any]]:
        relevant = evidence
        requested = []
        for item in relevant:
            recommendation = self._fallback_chart(run.query, [item])
            if recommendation is not None:
                requested.append(recommendation)
        return await self._persist_charts(run, requested, relevant, columns)

    async def _persist_charts(self, run, requested: list[ChartRecommendation], relevant_evidence: list[dict[str, Any]], columns: list[dict[str, Any]]) -> list[dict[str, Any]]:
        column_names = {item["name"] for item in columns}
        evidence_map = {item["evidence_code"]: item for item in relevant_evidence}
        models, dto = [], []
        seen = set()
        for item in requested:
            refs = item.evidence_codes
            if item.chart_type not in SUPPORTED_CHART_TYPES:
                raise AnalysisOutputFailure("CHART_SPEC_INVALID", f"Unsupported chart type '{item.chart_type}'.")
            if not refs or any(code not in evidence_map for code in refs):
                raise AnalysisOutputFailure("CHART_SPEC_INVALID", f"Chart references unavailable evidence codes: {refs}.")
            # 'value' is an aggregation result alias, not necessarily a dataset column.
            if item.y_column == "value" and "value" not in column_names:
                metrics = {(evidence_map[code].get("operation") or {}).get("metric") for code in refs}
                if len(metrics) == 1 and next(iter(metrics)) in column_names:
                    item = item.model_copy(update={"y_column": next(iter(metrics))})
                    logger.info("Resolved chart metric alias analysis_run_id=%s metric=%s", run.id, item.y_column)
            unknown_axes = [value for value in (item.x_column, item.y_column, item.group_column) if value and value not in column_names]
            if unknown_axes:
                raise AnalysisOutputFailure("CHART_SPEC_INVALID", f"Chart references unknown dataset columns: {unknown_axes}.")
            if item.chart_type in {"line", "bar", "horizontal_bar", "scatter", "pie", "donut", "waterfall"} and (not item.x_column or not item.y_column):
                raise AnalysisOutputFailure("CHART_SPEC_INVALID", f"Chart type '{item.chart_type}' requires x_column and y_column.")
            if item.chart_type in {"grouped_bar", "stacked_bar", "heatmap"} and (not item.x_column or not item.y_column or not item.group_column):
                raise AnalysisOutputFailure("CHART_SPEC_INVALID", f"Chart type '{item.chart_type}' requires x_column, y_column, and group_column.")
            if item.chart_type in {"histogram", "boxplot"} and not (item.x_column or item.y_column):
                raise AnalysisOutputFailure("CHART_SPEC_INVALID", f"Chart type '{item.chart_type}' requires a numeric axis.")
            config = self._chart_data(item.model_dump(mode="json"), [evidence_map[code] for code in refs])
            filters = [condition for code in refs for condition in evidence_map[code].get("filters", [])]
            signature = self._chart_signature(item, config, filters, [evidence_map[code] for code in refs])
            if signature in seen:
                logger.info("Skipped duplicate chart analysis_run_id=%s chart_type=%s evidence_codes=%s reason=equivalent_data_and_scope", run.id, item.chart_type, refs)
                continue
            seen.add(signature)
            if len(models) >= MAX_CHARTS_PER_RUN:
                continue
            chart_code = f"CH{len(models) + 1}"
            model = ChartSpec(analysis_run_id=run.id, chart_code=chart_code, chart_type=item.chart_type, title=item.title, x_column=item.x_column, y_column=item.y_column, group_column=item.group_column, evidence_codes=refs, filters=filters, chart_config=config, purpose=item.purpose)
            models.append(model); dto.append({"chart_code": chart_code, **item.model_dump(mode="json"), "chart_config": config, "filters": filters})
        if models:
            try: await self.charts.create_many(models); await self.session.commit()
            except Exception as exc: await self.session.rollback(); raise AnalysisOutputFailure("VISUALIZATION_FAILED") from exc
        logger.info("Charts finalized analysis_run_id=%s candidate_count=%s saved_count=%s", run.id, len(requested), len(models))
        return dto

    @staticmethod
    def _chart_signature(item, config, filters, evidence):
        def canonical(value):
            if isinstance(value, bool):
                return value
            if isinstance(value, (int, float)):
                return float(value)
            if isinstance(value, dict):
                return {key: canonical(child) for key, child in value.items()}
            if isinstance(value, (list, tuple)):
                return [canonical(child) for child in value]
            return value

        def encode(value):
            return json.dumps(canonical(value), sort_keys=True, ensure_ascii=False)

        data = dict(config)
        # Category order does not change the information in a pie/donut.
        if item.chart_type in {"pie", "donut"} and "labels" in data and "values" in data:
            data["points"] = sorted(zip(data.pop("labels"), data.pop("values")), key=encode)
        operations = []
        for source in evidence:
            operation = {key: value for key, value in (source.get("operation") or {}).items() if key != "sort"}
            operations.append(encode({"method": source.get("method"), "operation": operation}))
        return encode({
            "type": "composition" if item.chart_type in {"pie", "donut"} else item.chart_type,
            "axes": [item.x_column, item.y_column, item.group_column],
            "filters": sorted(set(encode(condition) for condition in filters)),
            "operations": sorted(set(operations)),
            "data": data,
        })

    @staticmethod
    def _fallback_chart(query: str, evidence: list[dict[str, Any]]) -> ChartRecommendation | None:
        for item in evidence:
            operation = item.get("operation") or {}
            method = item.get("method")
            result = item.get("result")
            records = result.get("contributions") if isinstance(result, dict) else result
            if not isinstance(records, list) or not records or not all(isinstance(row, dict) for row in records):
                continue

            x_column = None
            y_column = operation.get("metric")
            default_type = "bar"
            group_column = None
            if method == "groupby_aggregate":
                groups = operation.get("group_by") or []
                x_column = groups[0] if groups else None
                values = [row.get("value", row.get(y_column)) for row in records]
                additive = operation.get("aggregation") in {"sum", "count"}
                composition = (additive and 2 <= len(records) <= 6
                               and all(isinstance(value, (int, float)) and value >= 0 for value in values)
                               and sum(values) > 0
                               and len({row.get(x_column) for row in records}) == len(records))
                if len(groups) == 2:
                    group_column = groups[1]
                    default_type = "heatmap" if len(records) > 20 else "grouped_bar"
                elif len(groups) == 1 and composition:
                    default_type = "pie" if re.search(r'\b(share|percentage|proportion|composition|mix)\b', query, re.I) else "donut"
                elif len(records) > 6:
                    default_type = "horizontal_bar"
            elif method == "time_series_aggregate":
                x_column = operation.get("date_column")
                default_type = "line"
            elif method == "calculate_contribution":
                x_column = operation.get("dimension")
                default_type = "waterfall"
            else:
                continue
            if not x_column or not y_column:
                continue

            lowered = query.lower()
            if "horizontal" in lowered and "bar" in lowered:
                chart_type = "horizontal_bar"
            elif "donut" in lowered:
                chart_type = "donut"
            elif "pie" in lowered:
                chart_type = "pie"
            elif re.search(r'\bline\b', lowered):
                chart_type = "line"
            elif re.search(r'\bbar\b', lowered):
                chart_type = "bar"
            else:
                chart_type = default_type

            aggregation = operation.get("aggregation")
            prefix = f"{str(aggregation).title()} " if aggregation else ""
            return ChartRecommendation(
                needed=True,
                chart_type=chart_type,
                title=f"{prefix}{y_column} by {x_column}",
                x_column=x_column,
                y_column=y_column,
                group_column=group_column if chart_type in {"grouped_bar", "stacked_bar", "heatmap", "line"} else None,
                evidence_codes=[item["evidence_code"]],
                purpose="Visualize the verified analytical result requested by the user.",
            )
        return None

    async def create_report(self, *, run, claims: list[dict[str, Any]], evidence: list[dict[str, Any]], validations: list[dict[str, Any]], quality_warnings: list[dict[str, Any]], charts: list[dict[str, Any]], run_agent: AgentRunner) -> dict[str, Any]:
        accepted_codes = {item["claim_code"] for item in claims}
        evidence_codes = {code for claim in claims for code in claim["evidence_codes"]}
        relevant_evidence = [item for item in evidence if item["evidence_code"] in evidence_codes]
        relevant_stats = [item for item in validations if item.get("evidence_code") in evidence_codes]
        async def invoke(): return await self.report_agent.run(provider=run.llm_provider, query=run.query, claims=claims, evidence=relevant_evidence, validations=relevant_stats, quality_warnings=quality_warnings, charts=charts)
        result = await run_agent("report", {"query": run.query, "accepted_claims": claims, "supporting_evidence": relevant_evidence, "statistical_validations": relevant_stats, "data_quality_warnings": quality_warnings, "chart_specs": charts}, invoke)
        try:
            report = FinalReportOutput.model_validate(result.content)
        except ValidationError as exc:
            raise AnalysisOutputFailure("REPORT_VALIDATION_FAILED") from exc
        claim_map = {item["claim_code"]: item for item in claims}
        evidence_map = {item["evidence_code"]: item for item in relevant_evidence}
        if claims and not report.key_findings:
            raise AnalysisOutputFailure("REPORT_VALIDATION_FAILED", "The report omitted the accepted findings.")
        for finding in report.key_findings:
            if finding.claim_code not in accepted_codes or any(code not in evidence_map or code not in claim_map[finding.claim_code]["evidence_codes"] for code in finding.evidence_codes):
                raise AnalysisOutputFailure("REPORT_VALIDATION_FAILED")
            try:
                AnalystAgent._validate_numeric_grounding(finding.finding, {
                    "evidence": [evidence_map[code] for code in finding.evidence_codes],
                    "statistics": [item for item in relevant_stats if item.get("evidence_code") in finding.evidence_codes],
                })
            except NumericGroundingError as exc:
                raise AnalysisOutputFailure("REPORT_VALIDATION_FAILED", "A finding introduced a value outside its linked evidence.") from exc
        grounding = {"evidence": relevant_evidence, "statistics": relevant_stats, "quality": quality_warnings}
        texts = [report.executive_summary, *[item.finding for item in report.key_findings], *report.statistical_findings, *report.recommendations]
        try:
            for text in texts:
                AnalystAgent._validate_numeric_grounding(text, grounding)
        except NumericGroundingError as exc:
            raise AnalysisOutputFailure("REPORT_VALIDATION_FAILED") from exc
        payload = report.model_dump(mode="json")
        model = Report(analysis_run_id=run.id, executive_summary=report.executive_summary, key_findings=payload["key_findings"], statistical_findings=report.statistical_findings, data_notes=report.data_notes, limitations=report.limitations, recommendations=report.recommendations, report=payload)
        try: await self.reports.create(model); await self.session.commit()
        except Exception as exc: await self.session.rollback(); raise AnalysisOutputFailure("REPORT_PERSISTENCE_FAILED") from exc
        return payload

    @traced("fallback.report")
    async def create_fallback_report(self, *, run, claims: list[dict[str, Any]], evidence: list[dict[str, Any]], validations: list[dict[str, Any]], quality_warnings: list[dict[str, Any]]) -> dict[str, Any]:
        findings = []
        for claim in claims:
            findings.append({"claim_code": claim["claim_code"], "finding": claim.get("validated_text") or claim["claim_text"], "evidence_codes": claim["evidence_codes"]})
        summary = findings[0]["finding"] if findings else evidence[0]["interpretation"] if evidence else "The deterministic analysis completed with limited report detail."
        payload = FinalReportOutput(
            executive_summary=summary,
            key_findings=findings,
            statistical_findings=[item["interpretation"] for item in validations if item.get("interpretation")],
            data_notes=[item["message"] for item in quality_warnings if item.get("message")],
            limitations=list(dict.fromkeys([warning for item in evidence for warning in item.get("limitations", [])] + ["This report was assembled deterministically from saved evidence and accepted claims."])),
            recommendations=deterministic_recommendations(evidence),
        ).model_dump(mode="json")
        model = Report(analysis_run_id=run.id, executive_summary=payload["executive_summary"], key_findings=payload["key_findings"], statistical_findings=payload["statistical_findings"], data_notes=payload["data_notes"], limitations=payload["limitations"], recommendations=payload["recommendations"], report=payload)
        try:
            await self.reports.create(model); await self.session.commit()
        except Exception as exc:
            await self.session.rollback(); raise AnalysisOutputFailure("REPORT_PERSISTENCE_FAILED") from exc
        return payload

    @staticmethod
    def format_report(report: dict[str, Any]) -> str:
        lines = [report["executive_summary"]]
        sections = [("Key findings", [item["finding"] for item in report["key_findings"]]), ("Statistical findings", report["statistical_findings"]), ("Data notes", report["data_notes"]), ("Limitations", report["limitations"]), ("Recommendations", report["recommendations"])]
        for title, items in sections:
            if items: lines.extend(["", f"{title}:", *[f"- {item}" for item in items]])
        return "\n".join(lines)

    @staticmethod
    def _chart_data(spec: dict[str, Any], evidence: list[dict[str, Any]]) -> dict[str, Any]:
        result = evidence[0]["result"]
        records = result.get("contributions") if isinstance(result, dict) and isinstance(result.get("contributions"), list) else result if isinstance(result, list) else None
        chart_type = spec["chart_type"]
        if not records or not all(isinstance(row, dict) for row in records):
            raise AnalysisOutputFailure("CHART_SPEC_INVALID", "Supporting evidence does not contain chartable record rows.")
        keys = list(records[0])
        x_key = spec.get("x_column") if spec.get("x_column") in keys else next((key for key in keys if not isinstance(records[0].get(key), (int, float))), None)
        preferred_y = "change" if chart_type == "waterfall" and "change" in keys else "value" if "value" in keys else None
        y_key = spec.get("y_column") if spec.get("y_column") in keys else preferred_y or next((key for key in keys if key != x_key and isinstance(records[0].get(key), (int, float))), None)
        if chart_type in {"histogram", "boxplot"}:
            value_key = y_key or x_key
            values = [row.get(value_key) for row in records if isinstance(row.get(value_key), (int, float))]
            if not values:
                raise AnalysisOutputFailure("CHART_SPEC_INVALID", "Supporting evidence contains no numeric values for the distribution chart.")
            return {"values": values, "value_column": value_key}
        if not x_key or not y_key:
            raise AnalysisOutputFailure("CHART_SPEC_INVALID", f"Could not map chart axes to evidence fields: {keys}.")
        group_key = spec.get("group_column")
        if chart_type == "heatmap" and group_key in keys and group_key != x_key:
            x_values = list(dict.fromkeys(row.get(x_key) for row in records))
            group_values = list(dict.fromkeys(row.get(group_key) for row in records))
            lookup = {(row.get(x_key), row.get(group_key)): row.get(y_key) for row in records}
            if not all(value is None or isinstance(value, (int, float)) for value in lookup.values()):
                raise AnalysisOutputFailure("CHART_SPEC_INVALID")
            return {"x": x_values, "y": group_values, "z": [[lookup.get((x_value, group_value)) for x_value in x_values] for group_value in group_values], "x_column": x_key, "y_column": y_key, "group_column": group_key}
        if group_key in keys and group_key != x_key and chart_type in {"grouped_bar", "stacked_bar", "line"}:
            groups: dict[str, list[dict[str, Any]]] = {}
            for row in records:
                groups.setdefault(str(row.get(group_key)), []).append(row)
            return {"series": [{"name": name, "labels": [row.get(x_key) for row in rows], "values": [row.get(y_key) for row in rows]} for name, rows in groups.items()], "x_column": x_key, "y_column": y_key, "group_column": group_key}
        x, y = [row.get(x_key) for row in records], [row.get(y_key) for row in records]
        if not all(isinstance(value, (int, float)) for value in y):
            raise AnalysisOutputFailure("CHART_SPEC_INVALID", f"Evidence field '{y_key}' contains non-numeric chart values.")
        return {"labels": x, "values": y, "x_column": x_key, "y_column": y_key}

    async def list_claims_owned(self, run_id: UUID, user_id: UUID):
        if await self.runs.get_by_id_for_user(run_id, user_id) is None: raise AnalysisRunNotFoundError
        return await self.claims.list_for_run(run_id)
    async def list_charts_owned(self, run_id: UUID, user_id: UUID):
        if await self.runs.get_by_id_for_user(run_id, user_id) is None: raise AnalysisRunNotFoundError
        return await self.charts.list_for_run(run_id)
    async def get_report_owned(self, run_id: UUID, user_id: UUID):
        if await self.runs.get_by_id_for_user(run_id, user_id) is None: raise AnalysisRunNotFoundError
        report = await self.reports.get_for_run(run_id)
        if report is None: raise ReportNotFoundError
        return report
