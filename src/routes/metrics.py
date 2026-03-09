"""Metrics routes — GET /api/metrics, GET /api/longevity, POST /api/backfill."""

from dataclasses import asdict
from datetime import datetime, timedelta, timezone

from flask import Blueprint, jsonify

from database import Recovery, Run, UserProfile, get_session
from services.coaching import compute_efficiency_factor, prescribe_workout
from services.metrics_service import get_current_metrics
from utils import pace_str_to_seconds

bp = Blueprint("metrics", __name__)


@bp.route("/api/metrics", methods=["GET"])
def get_metrics():
    """Return current training metrics: EF, VDOT, CTL/ATL/TSB, ACWR, VO2max."""
    with get_session() as session:
        profile = session.query(UserProfile).first()
        snapshot = get_current_metrics(session, profile)

    result = asdict(snapshot)

    # Add workout prescription
    rx = prescribe_workout(
        recovery_score=None,  # Will be populated from briefing route
        tsb=snapshot.tsb,
        acwr=snapshot.acwr,
        vdot=snapshot.vdot,
        max_hr=profile.max_hr if profile else None,
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
    category = None
    if vo2max:
        if vo2max >= 50:
            category = "Elite"
        elif vo2max >= 45:
            category = "Above Average"
        elif vo2max >= 40:
            category = "Average"
        elif vo2max >= 35:
            category = "Below Average"
        else:
            category = "Low"

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
