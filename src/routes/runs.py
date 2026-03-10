"""Run routes — GET/POST /api/runs, GET /api/trends, GET /api/shoes."""

import logging
from datetime import date, datetime, timedelta, timezone

from flask import Blueprint, jsonify, request
from sqlalchemy import func

from database import Recovery, Run, get_session
from utils import (
    find_closest_run,
    format_pace,
    pace_str_to_seconds,
    safe_float,
    safe_int,
    seconds_to_pace,
    today_utc_start,
    validate_log_date,
    whoop_query_window,
)
from whoop import WhoopClient

logger = logging.getLogger(__name__)

bp = Blueprint("runs", __name__)


def _generate_coaching_insight(row: dict, recovery_data: dict | None) -> str:
    """Generate coaching insight based on recent run history."""
    today_pace_sec = pace_str_to_seconds(row.get("pace_per_mile"))
    today_hr = safe_float(row.get("avg_hr"))
    today_date = row.get("date")

    rec_score = safe_float(recovery_data.get("recovery_score")) if recovery_data else None
    rec_rhr = safe_float(recovery_data.get("resting_heart_rate")) if recovery_data else None
    rec_hrv = safe_float(recovery_data.get("hrv_rmssd_milli")) if recovery_data else None

    recovery_line = ""
    if rec_score is not None:
        color = "green" if rec_score >= 67 else ("yellow" if rec_score >= 34 else "red")
        parts = [f"Recovery: {rec_score:.0f}% ({color})"]
        if rec_rhr is not None:
            parts.append(f"RHR: {rec_rhr:.0f} bpm")
        if rec_hrv is not None:
            parts.append(f"HRV: {rec_hrv:.1f} ms")
        recovery_line = ". ".join(parts) + "."

    if today_pace_sec is None or today_hr is None:
        insight = "Run logged! Add more data points for coaching insights."
        if recovery_line:
            insight += f" {recovery_line}"
        return insight

    pace_display = seconds_to_pace(today_pace_sec)

    cutoff = date.fromisoformat(today_date) - timedelta(days=30) if today_date else datetime.now(timezone.utc).date() - timedelta(days=30)

    with get_session() as session:
        runs = (
            session.query(Run.pace_per_mile, Run.avg_hr)
            .filter(
                Run.date >= cutoff,
                Run.date < date.fromisoformat(today_date) if today_date else datetime.now(timezone.utc).date(),
                Run.pace_per_mile.isnot(None),
                Run.avg_hr.isnot(None),
            )
            .all()
        )
        past_runs = [(r.pace_per_mile, r.avg_hr) for r in runs]

    if not past_runs:
        insight = f"Building your baseline at {pace_display}/mi. Log a few more runs and I'll start giving pace recommendations."
        if recovery_line:
            insight += f" {recovery_line}"
        return insight

    similar_hrs = []
    for r_pace_str, r_hr in past_runs:
        r_pace = pace_str_to_seconds(r_pace_str)
        if r_pace and abs(r_pace - today_pace_sec) <= 30:
            similar_hrs.append(r_hr)

    if len(similar_hrs) >= 3:
        avg_similar_hr = sum(similar_hrs) / len(similar_hrs)
        hr_diff = today_hr - avg_similar_hr

        if hr_diff < -3:
            faster_pace = seconds_to_pace(today_pace_sec - 10)
            insight = (
                f"Your avg HR at {pace_display}/mi has dropped from "
                f"{avg_similar_hr:.0f} to {today_hr:.0f} bpm. "
                f"Your body has adapted. Try {faster_pace}/mi next run."
            )
        elif hr_diff > 3 and rec_score is not None and rec_score < 50:
            insight = (
                f"HR was {hr_diff:.0f} bpm higher than usual at this pace. "
                f"Recovery was only {rec_score:.0f}% -- your body needs rest. "
                f"Don't push pace tomorrow."
            )
        elif hr_diff > 3:
            insight = (
                "HR was a bit elevated today. Could be heat, caffeine, or sleep. "
                "Nothing to worry about."
            )
        else:
            insight = (
                f"Solid run. You're consistent at {pace_display}/mi. "
                f"Keep building here."
            )
    else:
        insight = (
            f"Building your baseline at {pace_display}/mi. "
            f"Log a few more runs and I'll start giving pace recommendations."
        )

    if recovery_line:
        insight += f" {recovery_line}"
    return insight


@bp.route("/api/runs", methods=["GET"])
def get_runs():
    """Return runs as JSON, newest first, with recovery scores. Supports ?days=90."""
    try:
        days = int(request.args.get("days", 90))
    except (ValueError, TypeError):
        return jsonify({"error": "days must be an integer"}), 400
    cutoff = datetime.now(timezone.utc).date() - timedelta(days=days)

    with get_session() as session:
        results = (
            session.query(Run, Recovery.recovery_score)
            .outerjoin(Recovery, Run.date == Recovery.date)
            .filter(Run.date >= cutoff)
            .order_by(Run.date.desc())
            .all()
        )
        records = []
        for run, recovery_score in results:
            d = run.to_dict()
            d["recovery_score"] = recovery_score
            records.append(d)
    return jsonify(records)


@bp.route("/api/runs", methods=["POST"])
def log_run():
    """Log a run: fetch Whoop data, generate coaching insight, save to DB."""
    data = request.get_json(silent=True)
    if not data:
        return jsonify({"error": "Request must be JSON"}), 400

    raw_distance = data.get("distance_miles")
    raw_time = data.get("time_minutes")
    if raw_distance is None or raw_time is None:
        return jsonify({"error": "distance_miles and time_minutes are required"}), 400
    try:
        distance = float(raw_distance)
        time_min = float(raw_time)
    except (ValueError, TypeError):
        return jsonify({"error": "distance_miles and time_minutes must be numbers"}), 400
    if distance <= 0 or distance > 200:
        return jsonify({"error": "distance_miles must be between 0 and 200"}), 400
    if time_min <= 0 or time_min > 2000:
        return jsonify({"error": "time_minutes must be between 0 and 2000"}), 400

    shoe = data.get("shoe", "").lower().strip()
    pace = format_pace(time_min, distance)

    # Use client-supplied local date (fixes UTC timezone bug)
    log_date, date_err = validate_log_date(data.get("date"))
    if date_err:
        return jsonify({"error": date_err}), 400
    today_str = log_date.isoformat()

    client = WhoopClient()
    start = whoop_query_window(log_date)

    workout = None
    recovery_data = None
    try:
        workouts = client.get_workouts(start=start)
        workout = find_closest_run(workouts, target_date=log_date)
    except Exception:
        logger.exception("Error fetching workouts from Whoop")
    try:
        recs = client.get_recovery(start=start)
        if recs:
            recovery_data = recs[-1].get("score", {})
    except Exception:
        logger.exception("Error fetching recovery from Whoop")

    row = {
        "date": today_str,
        "distance_miles": distance,
        "time_minutes": time_min,
        "pace_per_mile": pace,
        "avg_hr": None, "max_hr": None, "strain": None,
        "whoop_distance_meters": None,
        "zone_zero_milli": None, "zone_one_milli": None,
        "zone_two_milli": None, "zone_three_milli": None,
        "zone_four_milli": None, "zone_five_milli": None,
        "shoes": shoe,
    }
    if workout:
        score = workout.get("score", {})
        zones = score.get("zone_durations", {})
        row.update({
            "avg_hr": score.get("average_heart_rate"),
            "max_hr": score.get("max_heart_rate"),
            "strain": score.get("strain"),
            "whoop_distance_meters": score.get("distance_meter"),
            "zone_zero_milli": zones.get("zone_zero_milli"),
            "zone_one_milli": zones.get("zone_one_milli"),
            "zone_two_milli": zones.get("zone_two_milli"),
            "zone_three_milli": zones.get("zone_three_milli"),
            "zone_four_milli": zones.get("zone_four_milli"),
            "zone_five_milli": zones.get("zone_five_milli"),
        })

    with get_session() as session:
        run = Run(
            date=log_date,
            distance_miles=row["distance_miles"],
            time_minutes=row["time_minutes"],
            pace_per_mile=row["pace_per_mile"],
            avg_hr=safe_int(row["avg_hr"]),
            max_hr=safe_int(row["max_hr"]),
            strain=safe_float(row["strain"]),
            whoop_distance_meters=safe_float(row["whoop_distance_meters"]),
            zone_zero_milli=safe_int(row["zone_zero_milli"]),
            zone_one_milli=safe_int(row["zone_one_milli"]),
            zone_two_milli=safe_int(row["zone_two_milli"]),
            zone_three_milli=safe_int(row["zone_three_milli"]),
            zone_four_milli=safe_int(row["zone_four_milli"]),
            zone_five_milli=safe_int(row["zone_five_milli"]),
            shoes=row["shoes"],
        )
        session.add(run)

    insight = _generate_coaching_insight(row, recovery_data)
    return jsonify({"run": row, "coaching_insight": insight})


@bp.route("/api/shoes", methods=["GET"])
def get_shoes():
    """Sum miles per shoe from runs that have a shoe value."""
    with get_session() as session:
        results = (
            session.query(Run.shoes, func.sum(Run.distance_miles))
            .filter(Run.shoes.isnot(None), Run.shoes != "")
            .group_by(Run.shoes)
            .all()
        )
        shoes = [{"name": name, "miles": round(miles, 1)} for name, miles in results if miles]
        shoes.sort(key=lambda x: x["miles"], reverse=True)
    return jsonify(shoes)


@bp.route("/api/trends", methods=["GET"])
def get_trends():
    """Return date, pace_seconds, avg_hr for runs with valid pace data. Supports ?days=90."""
    try:
        days = int(request.args.get("days", 90))
    except (ValueError, TypeError):
        return jsonify({"error": "days must be an integer"}), 400
    cutoff = datetime.now(timezone.utc).date() - timedelta(days=days)

    with get_session() as session:
        runs = (
            session.query(Run)
            .filter(Run.pace_per_mile.isnot(None), Run.avg_hr.isnot(None), Run.date >= cutoff)
            .order_by(Run.date)
            .all()
        )
        result = []
        for r in runs:
            pace_sec = pace_str_to_seconds(r.pace_per_mile)
            if pace_sec and 0 < pace_sec < 900:
                result.append({
                    "date": r.date.isoformat(),
                    "pace_seconds": pace_sec,
                    "avg_hr": r.avg_hr,
                })
    return jsonify(result)


@bp.route("/api/whoop/auth")
def whoop_auth():
    """Redirect to Whoop authorization page for re-auth."""
    from flask import redirect as flask_redirect
    client = WhoopClient()
    auth_url, _state = client.generate_auth_url()
    return flask_redirect(auth_url)


@bp.route("/api/whoop/callback")
def whoop_callback():
    """Handle Whoop OAuth callback."""
    from flask import redirect as flask_redirect
    code = request.args.get("code")
    if not code:
        # Whoop tests the callback URL with a plain GET
        return "OK", 200
    client = WhoopClient()
    try:
        client.exchange_code(code)
        return flask_redirect("/?whoop=connected")
    except Exception:
        logger.exception("Whoop OAuth callback failed")
        return jsonify({"error": "Failed to connect Whoop"}), 500
