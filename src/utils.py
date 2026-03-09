"""Shared utility functions for Run Intel."""

from datetime import datetime, timezone


def pace_str_to_seconds(pace_str: str | None) -> int | None:
    """Convert '7:49' to 469 seconds."""
    if not pace_str or not isinstance(pace_str, str) or ":" not in pace_str:
        return None
    parts = pace_str.split(":")
    try:
        return int(parts[0]) * 60 + int(parts[1])
    except (ValueError, IndexError):
        return None


def seconds_to_pace(secs: float | None) -> str:
    """Convert 469 seconds to '7:49'."""
    if secs is None or secs <= 0:
        return "N/A"
    m = int(secs) // 60
    s = int(secs) % 60
    return f"{m}:{s:02d}"


def format_pace(total_minutes: float, distance_miles: float) -> str:
    """Convert total time and distance into pace string."""
    if distance_miles <= 0:
        return "N/A"
    pace_minutes = total_minutes / distance_miles
    mins = int(pace_minutes)
    secs = int((pace_minutes - mins) * 60)
    return f"{mins}:{secs:02d}"


def find_closest_run(workouts: list[dict]) -> dict | None:
    """Find the running workout closest to current time."""
    now = datetime.now(timezone.utc)
    running = [w for w in workouts if w.get("sport_name", "").lower() == "running"]
    if not running:
        return None

    def time_diff(w):
        end = w.get("end")
        if not end:
            return float("inf")
        end_dt = datetime.fromisoformat(end.replace("Z", "+00:00"))
        return abs((now - end_dt).total_seconds())

    return min(running, key=time_diff)


def safe_float(val) -> float | None:
    """Convert to float, return None if not possible."""
    try:
        v = float(val)
        return v if v == v else None  # NaN check without pandas
    except (ValueError, TypeError):
        return None


def safe_int(val) -> int | None:
    """Convert to int, return None if empty or invalid."""
    if val is None or val == "":
        return None
    try:
        return int(float(val))
    except (ValueError, TypeError):
        return None


def validate_log_date(date_str: str | None) -> tuple[object, str | None]:
    """Validate an optional log date string.

    Returns (date_obj, error_message).
    If date_str is None, returns today UTC.
    """
    from datetime import date, timedelta

    today = datetime.now(timezone.utc).date()
    if not date_str:
        return today, None
    try:
        log_date = date.fromisoformat(date_str)
    except (ValueError, TypeError):
        return None, "date must be YYYY-MM-DD format"
    if log_date > today:
        return None, "Cannot log future dates"
    if (today - log_date).days > 7:
        return None, "Cannot backdate more than 7 days"
    return log_date, None


def today_utc_start() -> str:
    """Return start-of-today in UTC as an ISO string."""
    return datetime.now(timezone.utc).replace(
        hour=0, minute=0, second=0, microsecond=0
    ).isoformat()
