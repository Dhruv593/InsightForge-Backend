from types import SimpleNamespace
from unittest.mock import AsyncMock
from uuid import uuid4

import pytest

from app.schemas.llm import LLMMessage, LLMResult, LLMUsage
from app.schemas.supervisor import SupervisorDecision
from app.schemas.profile_interpretation import ProfileInterpretation, RelevantColumn
from app.schemas.analysis_plan import AnalysisPlanOutput
from app.services.llm.llm_service import LLMService
from app.services.llm.base import LLMProviderError
from app.services.analysis_execution_service import AnalysisExecutionService
from app.services.analysis_recovery import recovery_report
from app.agents.planner import PlannerAgent


@pytest.mark.anyio
async def test_invalid_response_is_repaired_once_without_mutating_messages():
    expected = LLMResult(provider='gemini', model='test', content={'ok': True}, usage=LLMUsage(), latency_ms=1)
    provider = SimpleNamespace(provider_name='gemini', generate_structured=AsyncMock(side_effect=[LLMProviderError('LLM_INVALID_RESPONSE', 'invalid'), expected]))
    service = LLMService(providers={'gemini': provider})
    messages = [LLMMessage(role='user', content='Summarize revenue')]
    assert await service.generate_structured(provider='gemini', messages=messages, response_model=AnalysisPlanOutput) == expected
    assert len(messages) == 1
    assert len(provider.generate_structured.call_args.kwargs['messages']) == 2


@pytest.mark.anyio
@pytest.mark.parametrize(('code', 'attempts'), [('LLM_TIMEOUT', 2), ('LLM_AUTHENTICATION_FAILED', 1)])
async def test_provider_retry_is_bounded(code, attempts):
    provider = SimpleNamespace(provider_name='gemini', generate_text=AsyncMock(side_effect=LLMProviderError(code, 'unavailable')))
    service = LLMService(providers={'gemini': provider})
    with pytest.raises(LLMProviderError):
        await service.generate_text(provider='gemini', messages=[])
    assert provider.generate_text.await_count == attempts


@pytest.mark.anyio
async def test_planner_failure_uses_verified_metric_and_discloses_unapplied_filters():
    agent = PlannerAgent(SimpleNamespace(generate_structured=AsyncMock(side_effect=LLMProviderError('LLM_TIMEOUT', 'unavailable'))))
    decision = SupervisorDecision(query_type='comparative', objective='Compare', target_metrics=['Revenue'], relevant_dimensions=[], requires_statistics=False, requires_visualization=False, can_answer_with_available_data=True, missing_requirements=[])
    profile = ProfileInterpretation(relevant_columns=[RelevantColumn(name='Revenue', role='metric', inferred_type='numeric', relevance_reason='Requested')], usable_date_columns=[], data_quality_constraints=[], excluded_columns=[], analysis_warnings=[])
    result = await agent.run(provider='gemini', query='Revenue in March', supervisor_decision=decision, profile_interpretation=profile, verified_columns=['Revenue'])
    plan = AnalysisPlanOutput.model_validate(result.content)
    assert plan.tasks[0].required_columns == ['Revenue']
    assert 'have not been applied' in plan.limitations[0]
    with pytest.raises(LLMProviderError):
        await agent.run(provider='gemini', query='Revenue', supervisor_decision=decision, profile_interpretation=profile, verified_columns=[])


def test_empty_recovery_does_not_claim_success_or_invent_findings():
    result = recovery_report({'row_count': 5, 'column_count': 1, 'columns': [{'name': 'Revenue'}]}, [])
    assert result['key_findings'] == []
    assert 'could not complete' in result['executive_summary']
    assert '5 records' in result['data_notes'][0]


@pytest.mark.anyio
async def test_recovery_saves_report_and_excludes_rejected_and_statistical_claims():
    service = AnalysisExecutionService.__new__(AnalysisExecutionService)
    run = SimpleNamespace(id=uuid4())
    service.session = SimpleNamespace(rollback=AsyncMock(), get=AsyncMock(return_value=run))
    accepted = SimpleNamespace(status='accepted', claim_type='descriptive', claim_code='C1', claim_text='North: 100', review=None, evidence_items=[SimpleNamespace(evidence_code='E1', limitations=['Limited period'])])
    rejected = SimpleNamespace(status='rejected')
    statistical = SimpleNamespace(status='accepted', claim_type='statistical')
    service.outputs = SimpleNamespace(reports=SimpleNamespace(get_for_run=AsyncMock(return_value=None), create=AsyncMock()), claims=SimpleNamespace(list_for_run=AsyncMock(return_value=[accepted, rejected, statistical])), format_report=lambda payload: payload['executive_summary'])
    service._complete = AsyncMock(return_value=('run', 'message'))
    assert await service._recover_response(run.id, {}) == ('run', 'message')
    report = service.outputs.reports.create.call_args.args[0]
    assert [finding['claim_code'] for finding in report.key_findings] == ['C1']
    assert report.statistical_findings == []
    assert 'Limited period' in report.limitations
    assert 'analysis_plan' not in service._complete.call_args.args[1]


@pytest.mark.anyio
async def test_recovery_reuses_report_instead_of_creating_duplicate():
    service = AnalysisExecutionService.__new__(AnalysisExecutionService)
    run = SimpleNamespace(id=uuid4())
    saved = SimpleNamespace(report=recovery_report({}, []))
    service.session = SimpleNamespace(rollback=AsyncMock(), get=AsyncMock(return_value=run))
    service.outputs = SimpleNamespace(reports=SimpleNamespace(get_for_run=AsyncMock(return_value=saved), create=AsyncMock()), claims=SimpleNamespace(list_for_run=AsyncMock(return_value=[])), format_report=lambda payload: payload['executive_summary'])
    service._complete = AsyncMock()
    await service._recover_response(run.id, {})
    service.outputs.reports.create.assert_not_awaited()
