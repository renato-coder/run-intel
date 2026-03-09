"""Briefing routes — GET /api/briefing, GET /api/recovery/today, GET /api/snapshot."""

from dataclasses import asdict
from datetime import datetime, timedelta, timezone

from flask import Blueprint, jsonify

from briefing import generate_briefing
from database import BodyComp, NutritionLog, Recovery, Run, UserProfile, get_session
from services.coaching import prescribe_workout
from services.metrics_service import get_current_metrics

bp = Blueprint("briefing", __name__)


def _fetch_and_cache_recovery(session):
    """Fetch today's recovery from Whoop, cache to DB.

    Returns (recovery_dict, date_iso) or ({defaults}, None) on failure.
    """
    import logging

    from utils import today_utc_start
    from whoop import WhoopClient

    logger = logging.getLogger(__name__)
    today = datetime.now(timezone.utc).date()
    defaults = {"recovery_score": None, "hrv": None, "resting_hr": None}

    try:
        client = WhoopClient()
        recs = client.get_recovery(start=today_utc_start())
        if recs:
            score = recs[-1].get("score", {})
            recovery = {
                "recovery_score": score.get("recovery_score"),
                "hrv": score.get("hrv_rmssd_milli"),
                "resting_hr": score.get("resting_heart_rate"),
            }
            if recovery["recovery_score"] is not None:
                existing = session.query(Recovery).filter(Recovery.date == today).first()
                if existing:
                    existing.recovery_score = recovery["recovery_score"]
                    existing.hrv = recovery["hrv"]
                    existing.resting_hr = recovery["resting_hr"]
                else:
                    session.add(Recovery(date=today, **recovery))
                session.flush()
                return recovery, today.isoformat()
    except Exception:
        logger.exception("Error fetching recovery from Whoop")

    rec = session.query(Recovery).filter(Recovery.date == today).first()
    if rec and rec.recovery_score is not None:
        return {
            "recovery_score": rec.recovery_score,
            "hrv": rec.hrv,
            "resting_hr": rec.resting_hr,
        }, today.isoformat()

    latest = (
        session.query(Recovery)
        .filter(Recovery.recovery_score.isnot(None))
        .order_by(Recovery.date.desc())
        .first()
    )
    if latest:
        return {
            "recovery_score": latest.recovery_score,
            "hrv": latest.hrv,
            "resting_hr": latest.resting_hr,
        }, latest.date.isoformat()

    return defaults, None


@bp.route("/api/briefing", methods=["GET"])
def get_briefing():
    """Return the enhanced morning briefing with structured JSON.

    Includes: recovery status, workout prescription, pace progress,
    nutrition targets, body comp, and longevity metrics.
    Each section is null if no data is available (graceful degradation).
    """
    today = datetime.now(timezone.utc).date()
    cutoff_30d = today - timedelta(days=30)
    yesterday = today - timedelta(days=1)

    with get_session() as session:
        today_recovery, recovery_date = _fetch_and_cache_recovery(session)

        note = None
        if recovery_date and recovery_date != today.isoformat():
            note = "Recovery not yet scored today. Showing most recent data."

        recovery_rows = (
            session.query(Recovery)
            .filter(Recovery.date >= cutoff_30d, Recovery.date <= today)
            .order_by(Recovery.date)
            .all()
        )
        recovery_history = [r.to_dict() for r in recovery_rows]

        run_rows = (
            session.query(Run)
            .filter(Run.date >= cutoff_30d, Run.date <= today)
            .order_by(Run.date)
            .all()
        )
        run_history = [{"date": r.date.isoformat(), "strain": r.strain} for r in run_rows]

        # Get profile and metrics for enhanced briefing
        profile = session.query(UserProfile).first()
        metrics = get_current_metrics(session, profile)

        # Yesterday's nutrition
        yesterday_nutrition = (
            session.query(NutritionLog)
            .filter(NutritionLog.date == yesterday)
            .all()
        )
        yesterday_cals = sum(n.calories for n in yesterday_nutrition) if yesterday_nutrition else None
        yesterday_protein = sum(n.protein_grams for n in yesterday_nutrition) if yesterday_nutrition else None

        # Latest body comp
        latest_bc = (
            session.query(BodyComp)
            .order_by(BodyComp.date.desc())
            .first()
        )

        # Weight trend (7-day)
        week_ago_bc = (
            session.query(BodyComp)
            .filter(BodyComp.date <= today - timedelta(days=6))
            .order_by(BodyComp.date.desc())
            .first()
        )

    # Generate base briefing (existing logic)
    result = generate_briefing(today_recovery, recovery_history, run_history)
    if result is None:
        return jsonify({"status": "unavailable", "status_label": "No recovery data available yet."})

    result["recovery_date"] = recovery_date
    if note:
        result["note"] = note

    # Add structured workout prescription
    recovery_score = today_recovery.get("recovery_score")
    rx = prescribe_workout(
        recovery_score=recovery_score,
        tsb=metrics.tsb,
        acwr=metrics.acwr,
        vdot=metrics.vdot,
        max_hr=profile.max_hr if profile else None,
    )
    result["workout"] = asdict(rx)

    # Add pace progress
    result["pace_progress"] = None
    if metrics.vdot or metrics.ef_30d:
        progress = {}
        if metrics.vdot:
            progress["vdot_current"] = metrics.vdot
        if profile and profile.goal_marathon_time_min:
            from services.coaching import estimate_vdot
            target_vdot = estimate_vdot(26.2, float(profile.goal_marathon_time_min))
            progress["vdot_target"] = target_vdot
        if metrics.ef_trend:
            progress["ef_trend"] = metrics.ef_trend
        if metrics.ef_30d and metrics.ef_90d and metrics.ef_90d > 0:
            progress["ef_change_30d_pct"] = round((metrics.ef_30d - metrics.ef_90d) / metrics.ef_90d * 100, 1)
        result["pace_progress"] = progress

    # Add nutrition target
    result["nutrition_target"] = None
    if profile and profile.weight_lbs:
        # Simple static target for v1
        weight = float(profile.weight_lbs)
        target_cals = int(weight * 13)  # ~13 cal/lb for moderate deficit with activity
        target_protein = int(weight * 0.9)  # 0.9g/lb for deficit + training
        result["nutrition_target"] = {
            "calories": target_cals,
            "protein_grams": target_protein,
            "day_type": rx.type if rx.type != "rest" else "rest",
            "yesterday": {
                "calories": yesterday_cals,
                "protein_grams": yesterday_protein,
            } if yesterday_cals is not None else None,
        }

    # Add body comp
    result["body_comp"] = None
    if latest_bc:
        bc = {
            "weight_lbs": float(latest_bc.weight_lbs),
            "body_fat_pct": float(latest_bc.body_fat_pct) if latest_bc.body_fat_pct else None,
        }
        if week_ago_bc:
            weekly_change = float(latest_bc.weight_lbs) - float(week_ago_bc.weight_lbs)
            bc["weight_trend_per_week"] = round(weekly_change, 1)
        if latest_bc.body_fat_pct and profile and profile.goal_body_fat_pct:
            current_bf = float(latest_bc.body_fat_pct)
            target_bf = float(profile.goal_body_fat_pct)
            if current_bf > target_bf:
                # Rough estimate: ~0.5% BF/week at moderate deficit
                weeks = round((current_bf - target_bf) / 0.5)
                bc["target_body_fat_pct"] = target_bf
                bc["weeks_to_goal"] = weeks
        result["body_comp"] = bc

    # Add longevity
    result["longevity"] = None
    if metrics.estimated_vo2max:
        vo2 = metrics.estimated_vo2max
        category = "Elite" if vo2 >= 50 else "Above Average" if vo2 >= 45 else "Average" if vo2 >= 40 else "Below Average" if vo2 >= 35 else "Low"
        result["longevity"] = {
            "vo2max_estimate": vo2,
            "vo2max_category": category,
            "zone2_minutes_week": metrics.zone2_minutes_week,
            "zone2_target": 150,
        }

    return jsonify(result)


@bp.route("/api/recovery/today", methods=["GET"])
def get_recovery_today():
    """Return today's recovery, fetching from Whoop if not cached."""
    with get_session() as session:
        recovery, recovery_date = _fetch_and_cache_recovery(session)
    return jsonify({"date": recovery_date or datetime.now(timezone.utc).date().isoformat(), **recovery})


@bp.route("/api/snapshot", methods=["GET"])
def get_snapshot():
    """Return last 7d vs last 30d averages using SQL aggregates."""
    from sqlalchemy import func

    today = datetime.now(timezone.utc).date()
    d7 = today - timedelta(days=7)
    d30 = today - timedelta(days=30)

    with get_session() as session:
        def run_avgs(since):
            row = session.query(
                func.avg(Run.avg_hr),
                func.avg(Run.strain),
            ).filter(Run.date >= since).first()
            return {
                "avg_hr": round(row[0], 1) if row[0] else None,
                "avg_strain": round(row[1], 1) if row[1] else None,
            }

        def rec_avgs(since):
            row = session.query(
                func.avg(Recovery.recovery_score),
                func.avg(Recovery.hrv),
                func.avg(Recovery.resting_hr),
            ).filter(Recovery.date >= since).first()
            return {
                "recovery": round(row[0], 1) if row[0] else None,
                "hrv": round(row[1], 1) if row[1] else None,
                "resting_hr": round(row[2], 1) if row[2] else None,
            }

        r7, r30 = run_avgs(d7), run_avgs(d30)
        c7, c30 = rec_avgs(d7), rec_avgs(d30)

    return jsonify({
        "last_7d": {**r7, **c7},
        "last_30d": {**r30, **c30},
    })
