"""Small shared contracts; no runtime provider dependencies."""
import hashlib
import json
import math
from datetime import date, datetime, timedelta, timezone

SHANGHAI = timezone(timedelta(hours=8))


class ValidationError(ValueError):
    def __init__(self, code, message):
        self.code = code
        super().__init__(message)


def parse_time(value):
    try:
        if not isinstance(value, str):
            raise ValueError("timestamp must be a string")
        result = datetime.fromisoformat(value.replace("Z", "+00:00"))
        if result.tzinfo is None or result.utcoffset() is None:
            raise ValueError("timezone required")
        return result
    except (ValueError, TypeError) as exc:
        raise ValidationError("INVALID_TIME", str(exc)) from exc


def digest(obj):
    try:
        encoded = json.dumps(obj, ensure_ascii=False, sort_keys=True,
                             separators=(",", ":"), allow_nan=False)
    except (ValueError, TypeError) as exc:
        raise ValidationError("INVALID_JSON", str(exc)) from exc
    return hashlib.sha256(encoded.encode("utf-8")).hexdigest()


def number(value, field, minimum=None):
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        raise ValidationError("INVALID_NUMBER", field + " must be numeric")
    try:
        result = float(value)
    except (OverflowError, ValueError) as exc:
        raise ValidationError("INVALID_NUMBER", field + " must be finite") from exc
    if not math.isfinite(result) or (minimum is not None and result < minimum):
        raise ValidationError("INVALID_NUMBER", field + " is outside its domain")
    return result


def hours(target_date):
    try:
        day = date.fromisoformat(target_date)
    except (TypeError, ValueError) as exc:
        raise ValidationError("INVALID_DATE", "target_date must be YYYY-MM-DD") from exc
    start = datetime(day.year, day.month, day.day, tzinfo=SHANGHAI)
    return [(start + timedelta(hours=h)).isoformat() for h in range(24)]


def curve(values, name, nonnegative=False):
    if not isinstance(values, (list, tuple)) or len(values) != 24:
        raise ValidationError("INVALID_CURVE", name + " must contain 24 hourly values")
    return [number(v, name, 0 if nonnegative else None) for v in values]


def write_json(path, obj):
    """Caller owns directory creation and immutable output policy."""
    from pathlib import Path
    Path(path).write_text(json.dumps(obj, ensure_ascii=False, indent=2, sort_keys=True,
                                   allow_nan=False) + "\n", encoding="utf-8")
