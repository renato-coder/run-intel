"""Metrics routes — GET /api/metrics, GET /api/longevity, POST /api/backfill."""

from dataclasses import asdict
from datetime import datetime, timedelta, timezone

from flask import Blueprint, jsonify

from database import Recovery, Run, UserProfile, get_session
from services.coaching import categorize_vo2max, compute_efficiency_factor, prescribe_workout
from services.metrics_service import get_current_metrics
from utils import pace_str_to_seconds

bp = Blueprint("metrics", __name__)


@bp.route("/api/metrics", methods=["GET"])
def get_metrics():
    """Return current training metrics: EF, VDOT, CTL/ATL/TSB, ACWR, VO2max."""
    with get_session() as session:
        profile = session.query(UserProfile).first()
        snapshot = get_current_metrics(session, profile)
        max_hr = profile.max_hr if profile else None

    result = asdict(snapshot)

    # Add workout prescription
    rx = prescribe_workout(
        recovery_score=None,  # Will be populated from briefing route
        tsb=snapshot.tsb,
        acwr=snapshot.acwr,
        vdot=snapshot.vdot,
        max_hr=max_hr,
    )
    result["workout_rx"] = asdict(rx)

    # Add ACWR safety status
    if snapshot.acwr is not None:
        if snapshot.acwr > 1.5:
            result["acwr_status"] = "danger"
            result["acwr_message"] = "Training load spike detected. High injury risk. Scale back."
        elif snapshot.acwr > 1.3:
            result["acwr_status"] = "warning"
            result["acwr_message"] = "Training load is elevated. Monitor closely."
        elif snapshot.acwr < 0.8:
            result["acwr_status"] = "low"
            result["acwr_message"] = "Training load is low. Consider increasing gradually."
        else:
            result["acwr_status"] = "optimal"
            result["acwr_message"] = "Training load is in the sweet spot."

    return jsonify(result)


@bp.route("/api/longevity", methods=["GET"])
def get_longevity():
    """Return longevity metrics: VO2 max, Zone 2 minutes, category, RHR/HRV trends."""
    today = datetime.now(timezone.utc).date()
    cutoff_90d = today - timedelta(days=90)

    with get_session() as session:
        profile = session.query(UserProfile).first()
        snapshot = get_current_metrics(session, profile)

        # RHR and HRV trends (last 90 days)
        recovery_rows = (
            session.query(Recovery)
            .filter(Recovery.date >= cutoff_90d, Recovery.date <= today)
            .order_by(Recovery.date)
            .all()
        )
        rhr_trend = [
            {"date": r.date.isoformat(), "value": round(r.resting_hr, 1)}
            for r in recovery_rows if r.resting_hr is not None
        ]
        hrv_trend = [
            {"date": r.date.isoformat(), "value": round(r.hrv, 1)}
            for r in recovery_rows if r.hrv is not None
        ]

    vo2max = snapshot.estimated_vo2max
    category = categorize_vo2max(vo2max)

    # Compute trend directions: compare last 7 days vs prior 23 days (30d window)
    def _trend_direction(points, lower_is_better):
        if len(points) < 4:
            return None, None, None
        recent = [p["value"] for p in points[-7:]]
        older = [p["value"] for p in points[:-7]]
        if not recent or not older:
            return None, None, None
        avg_recent = sum(recent) / len(recent)
        avg_older = sum(older) / len(older)
        diff = avg_recent - avg_older
        if lower_is_better:
            direction = "improving" if diff < -1 else ("declining" if diff > 1 else "stable")
        else:
            direction = "improving" if diff > 1 else ("declining" if diff < -1 else "stable")
        return direction, round(avg_recent, 1), round(diff, 1)

    rhr_direction, rhr_current, rhr_change = _trend_direction(rhr_trend, lower_is_better=True)
    hrv_direction, hrv_current, hrv_change = _trend_direction(hrv_trend, lower_is_better=False)

    indicators = {
        "rhr": {"direction": rhr_direction, "current": rhr_current, "change": rhr_change},
        "hrv": {"direction": hrv_direction, "current": hrv_current, "change": hrv_change},
        "vo2max": {"direction": snapshot.ef_trend, "current": vo2max, "category": category},
    }

    return jsonify({
        "vo2max_estimate": vo2max,
        "vo2max_category": category,
        "zone2_minutes_week": snapshot.zone2_minutes_week,
        "zone2_target": 150,
        "ef_trend": snapshot.ef_trend,
        "ef_30d": snapshot.ef_30d,
        "ef_90d": snapshot.ef_90d,
        "rhr_trend": rhr_trend,
        "hrv_trend": hrv_trend,
        "indicators": indicators,
    })


@bp.route("/api/backfill", methods=["POST"])
def backfill_metrics():
    """Compute EF for all historical runs that have pace + HR data."""
    with get_session() as session:
        runs = session.query(Run).order_by(Run.date).all()
        computed = 0
        results = []
        for r in runs:
            pace_sec = pace_str_to_seconds(r.pace_per_mile)
            if pace_sec and r.avg_hr:
                ef = compute_efficiency_factor(pace_sec, r.avg_hr)
                if ef:
                    computed += 1
                    results.append({
                        "date": r.date.isoformat(),
                        "distance": r.distance_miles,
                        "pace": r.pace_per_mile,
                        "avg_hr": r.avg_hr,
                        "ef": ef,
                    })

    return jsonify({
        "total_runs": len(runs),
        "computed_ef": computed,
        "sample": results[-5:] if results else [],
    })
