"""Briefing routes — GET /api/briefing, GET /api/recovery/today, GET /api/snapshot."""

from dataclasses import asdict
from datetime import datetime, timedelta, timezone

from flask import Blueprint, jsonify

from briefing import generate_briefing
from database import BodyComp, NutritionLog, Recovery, Run, UserProfile, get_session
from services.coaching import categorize_vo2max, compute_nutrition_plan, prescribe_workout, vdot_to_marathon_time
from services.metrics_service import get_current_metrics

bp = Blueprint("briefing", __name__)


def _fetch_and_cache_recovery(session):
    """Fetch today's recovery from Whoop, cache to DB.

    Returns (recovery_dict, date_iso) or ({defaults}, None) on failure.
    """
    import logging

    from whoop import WhoopClient

    logger = logging.getLogger(__name__)
    today = datetime.now(timezone.utc).date()
    defaults = {"recovery_score": None, "hrv": None, "resting_hr": None}

    try:
        client = WhoopClient()
        # Query from yesterday — Whoop recovery is tied to a sleep cycle that
        # starts the previous day, so today's recovery may have a cycle_start
        # before midnight UTC today.
        yesterday_start = (
            datetime.now(timezone.utc)
            .replace(hour=0, minute=0, second=0, microsecond=0)
            - timedelta(days=1)
        ).isoformat()
        recs = client.get_recovery(start=yesterday_start)
        if recs:
            # Take the most recent record and cache it
            latest_rec = recs[-1]
            score = latest_rec.get("score", {})
            recovery = {
                "recovery_score": score.get("recovery_score"),
                "hrv": score.get("hrv_rmssd_milli"),
                "resting_hr": score.get("resting_heart_rate"),
            }
            # Determine the record's actual date from the cycle's created_at
            rec_date = today
            created = latest_rec.get("created_at") or latest_rec.get("updated_at")
            if created:
                try:
                    rec_date = datetime.fromisoformat(created.replace("Z", "+00:00")).date()
                except (ValueError, AttributeError):
                    pass

            if recovery["recovery_score"] is not None:
                existing = session.query(Recovery).filter(Recovery.date == rec_date).first()
                if existing:
                    existing.recovery_score = recovery["recovery_score"]
                    existing.hrv = recovery["hrv"]
                    existing.resting_hr = recovery["resting_hr"]
                else:
                    session.add(Recovery(date=rec_date, **recovery))
                session.flush()
                return recovery, rec_date.isoformat()
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

        # Extract profile values before session closes
        profile_data = profile.to_dict() if profile else {}

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
        bc_data = None
        if latest_bc:
            bc_data = {
                "weight_lbs": float(latest_bc.weight_lbs),
                "body_fat_pct": float(latest_bc.body_fat_pct) if latest_bc.body_fat_pct else None,
            }

        # Weight trend (7-day)
        week_ago_bc = (
            session.query(BodyComp)
            .filter(BodyComp.date <= today - timedelta(days=6))
            .order_by(BodyComp.date.desc())
            .first()
        )
        week_ago_weight = float(week_ago_bc.weight_lbs) if week_ago_bc else None

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
        max_hr=profile_data.get("max_hr"),
    )
    result["workout"] = asdict(rx)

    # Add pace progress with human-readable marathon times
    result["pace_progress"] = None
    if metrics.vdot or metrics.ef_30d:
        progress = {}
        if metrics.vdot:
            progress["vdot_current"] = metrics.vdot
            progress["marathon_estimate"] = vdot_to_marathon_time(metrics.vdot)
        if profile_data.get("goal_marathon_time_min"):
            from services.coaching import estimate_vdot
            goal_time = float(profile_data["goal_marathon_time_min"])
            target_vdot = estimate_vdot(26.2, goal_time)
            progress["vdot_target"] = target_vdot
            hours = int(goal_time // 60)
            mins = int(goal_time % 60)
            progress["marathon_target"] = f"{hours}:{mins:02d}"
        if metrics.ef_trend:
            progress["ef_trend"] = metrics.ef_trend
        if metrics.ef_30d and metrics.ef_90d and metrics.ef_90d > 0:
            progress["ef_change_30d_pct"] = round((metrics.ef_30d - metrics.ef_90d) / metrics.ef_90d * 100, 1)
        result["pace_progress"] = progress

    # Add nutrition target — RMR-based (Mifflin-St Jeor) or custom override
    result["nutrition_target"] = None
    # Weight priority: latest body comp → profile weight
    current_weight = bc_data["weight_lbs"] if bc_data else profile_data.get("weight_lbs")
    if current_weight:
        current_weight = float(current_weight)
        height = profile_data.get("height_inches")
        age = profile_data.get("age")
        sex = profile_data.get("sex")

        # Determine training day type
        if rx.type in ("tempo", "intervals", "long"):
            day_type = "hard"
        elif rx.type == "rest":
            day_type = "rest"
        else:
            day_type = "easy"

        custom_cals = profile_data.get("goal_calorie_target")
        custom_protein = profile_data.get("goal_protein_target_grams")

        # If we have enough data for RMR-based calculation
        if height and age and sex:
            goal_date = profile_data.get("goal_target_date")
            if isinstance(goal_date, str):
                from datetime import date as date_cls
                try:
                    goal_date = date_cls.fromisoformat(goal_date)
                except ValueError:
                    goal_date = None

            plan = compute_nutrition_plan(
                weight_lbs=current_weight,
                height_inches=height,
                age=age,
                sex=sex,
                goal_weight_lbs=float(profile_data["goal_weight_lbs"]) if profile_data.get("goal_weight_lbs") else None,
                goal_target_date=goal_date,
            )

            # Training-day adjustment: hard days get smaller deficit, rest days get larger
            if day_type == "hard":
                adjusted_cals = plan.tdee  # maintenance on hard days
            elif day_type == "rest":
                adjusted_cals = max(1200, plan.calorie_target - 100)
            else:
                adjusted_cals = plan.calorie_target

            # Custom targets override auto-calculated
            if custom_cals or custom_protein:
                target_cals = custom_cals or adjusted_cals
                target_protein = custom_protein or plan.protein_target_grams
                target_source = "custom"
            else:
                target_cals = adjusted_cals
                target_protein = plan.protein_target_grams
                target_source = "auto"

            result["nutrition_target"] = {
                "calories": target_cals,
                "protein_grams": target_protein,
                "day_type": day_type,
                "target_source": target_source,
                "rmr": plan.rmr,
                "rmr_adapted": plan.rmr_adapted,
                "tdee": plan.tdee,
                "daily_deficit": plan.daily_deficit,
                "weekly_loss_rate": plan.weekly_loss_rate,
                "weeks_to_goal": plan.weeks_to_goal,
                "is_safe": plan.is_safe,
                "warning": plan.warning,
                "yesterday": {
                    "calories": yesterday_cals,
                    "protein_grams": yesterday_protein,
                } if yesterday_cals is not None else None,
            }
        else:
            # Fallback: old formula when profile is incomplete
            auto_protein = max(int(current_weight * 0.9), 150)
            if day_type == "hard":
                auto_cals = int(current_weight * 15)
            elif day_type == "rest":
                auto_cals = int(current_weight * 11)
            else:
                auto_cals = int(current_weight * 13)

            if custom_cals or custom_protein:
                target_cals = custom_cals or auto_cals
                target_protein = custom_protein or auto_protein
                target_source = "custom"
            else:
                target_cals = auto_cals
                target_protein = auto_protein
                target_source = "auto"

            result["nutrition_target"] = {
                "calories": target_cals,
                "protein_grams": target_protein,
                "day_type": day_type,
                "target_source": target_source,
                "rmr": None,
                "rmr_adapted": None,
                "tdee": None,
                "daily_deficit": None,
                "weekly_loss_rate": None,
                "weeks_to_goal": None,
                "is_safe": True,
                "warning": "Set height, age, and sex in Settings for RMR-based targets.",
                "yesterday": {
                    "calories": yesterday_cals,
                    "protein_grams": yesterday_protein,
                } if yesterday_cals is not None else None,
            }

    # Add body comp
    result["body_comp"] = None
    if bc_data:
        bc = dict(bc_data)
        if week_ago_weight:
            weekly_change = bc_data["weight_lbs"] - week_ago_weight
            bc["weight_trend_per_week"] = round(weekly_change, 1)
        if bc_data["body_fat_pct"] and profile_data.get("goal_body_fat_pct"):
            current_bf = bc_data["body_fat_pct"]
            target_bf = profile_data["goal_body_fat_pct"]
            if current_bf > target_bf:
                weeks = round((current_bf - target_bf) / 0.5)
                bc["target_body_fat_pct"] = target_bf
                bc["weeks_to_goal"] = weeks
        result["body_comp"] = bc

    # Add longevity
    result["longevity"] = None
    if metrics.estimated_vo2max:
        vo2 = metrics.estimated_vo2max
        category = categorize_vo2max(vo2)
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


@bp.route("/api/debug/whoop-recovery", methods=["GET"])
def debug_whoop_recovery():
    """Temporary debug endpoint: show raw Whoop recovery API response."""
    from whoop import WhoopClient

    today = datetime.now(timezone.utc).date()
    yesterday_start = (
        datetime.now(timezone.utc)
        .replace(hour=0, minute=0, second=0, microsecond=0)
        - timedelta(days=1)
    ).isoformat()
    today_start = (
        datetime.now(timezone.utc)
        .replace(hour=0, minute=0, second=0, microsecond=0)
    ).isoformat()

    try:
        client = WhoopClient()
        recs_yesterday = client.get_recovery(start=yesterday_start)
        recs_today = client.get_recovery(start=today_start)
    except Exception as e:
        return jsonify({"error": str(e)})

    # Show top-level keys of each record (not full nested data)
    def summarize(rec):
        score = rec.get("score", {})
        return {
            "top_keys": list(rec.keys()),
            "cycle_id": rec.get("cycle_id"),
            "sleep_id": rec.get("sleep_id"),
            "created_at": rec.get("created_at"),
            "updated_at": rec.get("updated_at"),
            "score_state": rec.get("score_state"),
            "recovery_score": score.get("recovery_score"),
            "hrv": score.get("hrv_rmssd_milli"),
            "resting_hr": score.get("resting_heart_rate"),
        }

    return jsonify({
        "utc_now": datetime.now(timezone.utc).isoformat(),
        "today": today.isoformat(),
        "query_yesterday_start": yesterday_start,
        "query_today_start": today_start,
        "recs_from_yesterday_count": len(recs_yesterday),
        "recs_from_yesterday": [summarize(r) for r in recs_yesterday],
        "recs_from_today_count": len(recs_today),
        "recs_from_today": [summarize(r) for r in recs_today],
    })


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
