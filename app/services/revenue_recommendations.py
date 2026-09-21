"""Conservative next-step suggestions derived from completed evidence, not promises."""
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


def revenue_recommendations(evidence):
    suggestions = []
    for item in evidence:
        operation = item.get("operation") or {}
        metric = operation.get("metric") or ""
        if not any(word in str(metric).lower() for word in ("revenue", "sales")):
            continue
        method = item.get("method")
        rows = item.get("result")
        if method not in {"groupby_aggregate", "time_series_aggregate"} or not isinstance(rows, list):
            continue
        groups = operation.get("group_by") or []
        dimension = operation.get("date_column") if method == "time_series_aggregate" else groups[0] if len(groups) == 1 else None
        if not dimension:
            continue
        points = []
        for row in rows:
            if not isinstance(row, dict) or row.get(dimension) is None:
                continue
            value = row.get("value", row.get(metric))
            if isinstance(value, (int, float)) and not isinstance(value, bool) and math.isfinite(value):
                points.append((str(row[dimension])[:100], value))
        if len(points) < 2:
            continue
        high = max(points, key=lambda point: point[1])
        low = min(points, key=lambda point: point[1])
        if high[1] == low[1]:
            continue
        if method == "time_series_aggregate":
            period = _period_label(high[0], operation.get("frequency"))
            suggestions.append(f"Review orders, pricing and campaigns in the strongest period ({period}) before assuming that performance will repeat.")
        else:
            suggestions.append(f"Compare order volumes, pricing and customer mix between {high[0]} and {low[0]} in the {dimension.replace('_', ' ')} breakdown. Test a small improvement before committing more budget.")
    return list(dict.fromkeys(suggestions))[:4]
