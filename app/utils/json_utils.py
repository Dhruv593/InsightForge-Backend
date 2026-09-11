import math
from datetime import date, datetime
from typing import Any

import numpy as np
import pandas as pd


def to_json_safe(value: Any) -> Any:
    """Recursively convert Pandas/NumPy values into PostgreSQL JSONB-safe values."""
    if value is pd.NA or value is pd.NaT:
        return None
    if value is None or isinstance(value, (str, bool, int)):
        return value

    if isinstance(value, float):
        return value if math.isfinite(value) else None

    if isinstance(value, np.generic):
        return to_json_safe(value.item())

    if isinstance(value, (pd.Timestamp, datetime, date)):
        return value.isoformat()

    if isinstance(value, dict):
        return {str(key): to_json_safe(item) for key, item in value.items()}

    if isinstance(value, (list, tuple, set, np.ndarray)):
        return [to_json_safe(item) for item in value]

    try:
        if bool(pd.isna(value)):
            return None
    except (TypeError, ValueError):
        pass

    return str(value)
