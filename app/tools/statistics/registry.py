from typing import Any
import numpy as np
import pandas as pd
from scipy import stats

from app.core.analysis_constants import STATISTICAL_ALPHA
from app.schemas.statistical_validation import StatisticalTestResult, StatisticalValidationRequest


class StatisticalToolError(Exception): pass


class StatisticalToolRegistry:
    def execute(self, frame: pd.DataFrame, request: StatisticalValidationRequest) -> StatisticalTestResult:
        if any(column not in frame.columns for column in request.columns): raise StatisticalToolError("Unknown statistical column.")
        method = request.test_type
        try:
            if method in {"pearson", "spearman"}: return self._correlation(frame, request, method)
            if method == "chi_square": return self._chi_square(frame, request)
            return self._group_test(frame, request, method)
        except StatisticalToolError: raise
        except Exception as exc: raise StatisticalToolError("Statistical test failed.") from exc

    def _correlation(self, frame, request, method):
        x, y = request.columns[:2]
        values = frame[[x, y]].apply(pd.to_numeric, errors="coerce").dropna()
        if len(values) < 3: raise StatisticalToolError("At least three complete observations are required.")
        result = stats.pearsonr(values[x], values[y]) if method == "pearson" else stats.spearmanr(values[x], values[y])
        coefficient, p = float(result.statistic), float(result.pvalue)
        return self._result(method, coefficient, p, abs(coefficient), {"sample_size": len(values)}, ["Correlation does not establish causation."])

    def _chi_square(self, frame, request):
        a, b = request.columns[:2]; table = pd.crosstab(frame[a], frame[b])
        if table.shape[0] < 2 or table.shape[1] < 2: raise StatisticalToolError("Chi-square requires at least two categories per variable.")
        statistic, p, _, expected = stats.chi2_contingency(table)
        n = table.to_numpy().sum(); denominator = max(1, min(table.shape) - 1)
        effect = float(np.sqrt(statistic / (n * denominator)))
        assumptions = {"minimum_expected_count": float(expected.min()), "sample_size": int(n)}
        warnings = ["Some expected cell counts are below 5."] if expected.min() < 5 else []
        return self._result("chi_square", statistic, p, effect, assumptions, warnings)

    def _group_test(self, frame, request, method):
        group_column = request.group_column
        metric = next((c for c in request.columns if c != group_column), request.columns[-1])
        if not group_column or group_column not in frame.columns: raise StatisticalToolError("A valid group column is required.")
        groups = [pd.to_numeric(group[metric], errors="coerce").dropna().to_numpy() for _, group in frame.groupby(group_column)]
        groups = [group for group in groups if len(group) >= 2]
        if len(groups) < 2: raise StatisticalToolError("At least two groups with observations are required.")
        normality = [self._finite_or_none(stats.shapiro(group[:5000]).pvalue) if 3 <= len(group) else None for group in groups]
        levene_p = self._finite_or_none(stats.levene(*groups).pvalue)
        assumptions: dict[str, Any] = {"group_sizes": [len(g) for g in groups], "normality_p_values": normality, "levene_p_value": levene_p}
        warnings = []
        if levene_p is None:
            warnings.append("The equal-variance check was inconclusive for these samples.")
        if method == "anova":
            statistic, p = stats.f_oneway(*groups)
            all_values = np.concatenate(groups); grand = all_values.mean()
            between = sum(len(g) * (g.mean() - grand) ** 2 for g in groups); total = sum(((g - grand) ** 2).sum() for g in groups)
            effect = float(between / total) if total else None
        else:
            if len(groups) != 2: raise StatisticalToolError("This test requires exactly two groups.")
            a, b = groups
            confidence_interval = None
            if method == "mann_whitney_u":
                statistic, p = stats.mannwhitneyu(a, b, alternative="two-sided")
                effect = float(1 - (2 * statistic) / (len(a) * len(b)))
            else:
                equal_var = method == "independent_t_test"
                statistic, p = stats.ttest_ind(a, b, equal_var=equal_var)
                pooled = np.sqrt(((len(a)-1)*a.var(ddof=1)+(len(b)-1)*b.var(ddof=1))/(len(a)+len(b)-2))
                effect = float((a.mean()-b.mean())/pooled) if pooled else None
                mean_difference = float(a.mean() - b.mean())
                if equal_var:
                    standard_error = float(pooled * np.sqrt(1 / len(a) + 1 / len(b)))
                    degrees_freedom = len(a) + len(b) - 2
                else:
                    variance_a, variance_b = a.var(ddof=1) / len(a), b.var(ddof=1) / len(b)
                    standard_error = float(np.sqrt(variance_a + variance_b))
                    degrees_freedom = float((variance_a + variance_b) ** 2 / ((variance_a ** 2) / (len(a) - 1) + (variance_b ** 2) / (len(b) - 1)))
                margin = float(stats.t.ppf(0.975, degrees_freedom) * standard_error)
                confidence_interval = {"lower": mean_difference - margin, "upper": mean_difference + margin, "confidence_level": 0.95}
                if equal_var and levene_p is not None and levene_p < STATISTICAL_ALPHA: warnings.append("Equal variance assumption may be violated; Welch's test is preferable.")
            return self._result(method, statistic, p, effect, assumptions, warnings, confidence_interval)
        return self._result(method, statistic, p, effect, assumptions, warnings)

    @staticmethod
    def _result(method, statistic, p, effect, assumptions, warnings, confidence_interval=None):
        statistic_value = StatisticalToolRegistry._finite_or_none(statistic)
        p_value = StatisticalToolRegistry._finite_or_none(p)
        effect_value = StatisticalToolRegistry._finite_or_none(effect)
        assumptions = {**assumptions, "significance_alpha": STATISTICAL_ALPHA}
        valid = statistic_value is not None and p_value is not None
        result_warnings = list(warnings)
        if not valid:
            result_warnings.append("The test result was not finite, commonly because the input lacked variation.")
        return StatisticalTestResult(method_used=method, statistic=statistic_value, p_value=p_value, effect_size=effect_value, confidence_interval=confidence_interval if valid else None, assumptions=assumptions, is_significant=p_value < STATISTICAL_ALPHA if valid else None, is_valid=valid, warnings=result_warnings)

    @staticmethod
    def _finite_or_none(value):
        if value is None:
            return None
        number = float(value)
        return number if np.isfinite(number) else None
