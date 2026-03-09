"""Metrics routes — GET /api/metrics, GET /api/longevity."""

from dataclasses import asdict

from flask import Blueprint, jsonify

from database import UserProfile, get_session
from services.coaching import prescribe_workout
from services.metrics_service import get_current_metrics

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
    """Return longevity metrics: VO2 max, Zone 2 minutes, category."""
    with get_session() as session:
        profile = session.query(UserProfile).first()
        snapshot = get_current_metrics(session, profile)

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
    })
