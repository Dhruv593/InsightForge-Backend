"""Conservative next steps derived from verified evidence, not model promises."""
import math
from datetime import datetime


def _period_label(value, frequency):
    try:
        date = datetime.fromisoformat(str(value).replace("Z", "+00:00"))
    except ValueError:
        return str(value)
    if frequency == "monthly":
        return date.strftime("%B %Y")
    if frequency == "quarterly":
        return f"Q{(date.month - 1) // 3 + 1} {date.year}"
    if frequency == "yearly":
        return str(date.year)
    return f"{date.day} {date.strftime('%B %Y')}"


def _humanize(value):
    return str(value or "metric").replace("_", " ").strip().lower()


def _valid_points(rows, dimension, metric):
    points = []
    for row in rows:
        if not isinstance(row, dict) or row.get(dimension) is None:
            continue
        value = row.get("value", row.get(metric))
        if isinstance(value, (int, float)) and not isinstance(value, bool) and math.isfinite(value):
            points.append((str(row[dimension])[:100], value))
    return points


def _comparison_recommendation(metric, dimension, high, low):
    metric_label = _humanize(metric)
    dimension_label = _humanize(dimension)
    if any(word in metric_label for word in ("revenue", "sales")):
        return (
            f"Compare order volume, pricing, and customer or product mix between {high[0]} and {low[0]} "
            f"in the {dimension_label} breakdown. Test one focused improvement and track {metric_label} "
            "before expanding it."
        )
    return (
        f"Investigate why {high[0]} records higher {metric_label} than {low[0]} across {dimension_label}. "
        "Compare volume, mix, timing, and operating conditions, then test one change with a measurable "
        f"{metric_label} target."
    )


def _time_recommendation(metric, operation, high, low):
    metric_label = _humanize(metric)
    high_period = _period_label(high[0], operation.get("frequency"))
    low_period = _period_label(low[0], operation.get("frequency"))
    if any(word in metric_label for word in ("revenue", "sales")):
        drivers = "orders, pricing, customer mix, and campaigns"
    else:
        drivers = "volume, mix, timing, and relevant business events"
    return (
        f"Compare {drivers} in {high_period} and {low_period} to explain the change in {metric_label}. "
        "Confirm that the difference is repeatable before changing the broader plan."
    )


def deterministic_recommendations(evidence):
    """Build domain-neutral fallback actions from comparable evidence groups."""
    suggestions = []
    for item in evidence:
        operation = item.get("operation") or {}
        metric = operation.get("metric") or ""
        if not metric:
            continue
        method = item.get("method")
        rows = item.get("result")
        if method not in {"groupby_aggregate", "time_series_aggregate"} or not isinstance(rows, list):
            continue
        groups = operation.get("group_by") or []
        dimension = operation.get("date_column") if method == "time_series_aggregate" else groups[0] if len(groups) == 1 else None
        if not dimension:
            continue
        points = _valid_points(rows, dimension, metric)
        if len(points) < 2:
            continue
        high = max(points, key=lambda point: point[1])
        low = min(points, key=lambda point: point[1])
        if high[1] == low[1]:
            continue
        if method == "time_series_aggregate":
            suggestions.append(_time_recommendation(metric, operation, high, low))
        else:
            suggestions.append(_comparison_recommendation(metric, dimension, high, low))
    return list(dict.fromkeys(suggestions))[:4]


def revenue_recommendations(evidence):
    """Compatibility wrapper for callers that still request revenue-only fallbacks."""
    revenue_evidence = [
        item for item in evidence
        if any(word in str((item.get("operation") or {}).get("metric") or "").lower() for word in ("revenue", "sales"))
    ]
    return deterministic_recommendations(revenue_evidence)
