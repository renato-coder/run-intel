"""Briefing routes — GET /api/briefing, GET /api/recovery/today, GET /api/snapshot."""

from dataclasses import asdict
from datetime import datetime, timedelta, timezone

from flask import Blueprint, jsonify, request

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
            # Take the most recent record (Whoop returns newest first)
            latest_rec = recs[0]
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


def _sync_withings_weights(session, today):
    """Pull last 30 days of Withings weight data and upsert into BodyComp."""
    import logging

    logger = logging.getLogger(__name__)

    try:
        from config import WITHINGS_CLIENT_ID
        if not WITHINGS_CLIENT_ID:
            return

        from withings import WithingsClient
        client = WithingsClient()
        if not client.has_tokens():
            return

        start = today - timedelta(days=30)
        measurements = client.get_weight_measurements(start, today)

        for m in measurements:
            meas_date = m["date"]
            weight_kg = m["weight_kg"]
            weight_lbs = round(weight_kg * 2.20462, 1)
            body_fat_pct = m.get("body_fat_pct")

            existing = (
                session.query(BodyComp)
                .filter(BodyComp.date == meas_date, BodyComp.source == "withings")
                .first()
            )
            if existing:
                existing.weight_lbs = weight_lbs
                if body_fat_pct is not None:
                    existing.body_fat_pct = body_fat_pct
            else:
                session.add(BodyComp(
                    date=meas_date,
                    weight_lbs=weight_lbs,
                    body_fat_pct=body_fat_pct,
                    source="withings",
                ))
        session.flush()
    except Exception:
        logger.exception("Error syncing Withings weights")


def _fetch_today_workout_calories():
    """Sum kilojoules from all Whoop workouts today, return kcal."""
    import logging

    from whoop import WhoopClient

    logger = logging.getLogger(__name__)
    today = datetime.now(timezone.utc).date()

    try:
        client = WhoopClient()
        yesterday_start = (
            datetime.now(timezone.utc)
            .replace(hour=0, minute=0, second=0, microsecond=0)
            - timedelta(days=1)
        ).isoformat()
        workouts = client.get_workouts(start=yesterday_start)
        total_kj = 0
        for w in workouts:
            w_start = w.get("start")
            if w_start:
                w_date = datetime.fromisoformat(w_start.replace("Z", "+00:00")).date()
                if w_date != today:
                    continue
            score = w.get("score", {})
            kj = score.get("kilojoule") or 0
            total_kj += kj
        return round(total_kj / 4.184) if total_kj else 0
    except Exception:
        logger.exception("Error fetching workout calories from Whoop")
        return 0


@bp.route("/api/briefing", methods=["GET"])
def get_briefing():
    """Return the enhanced morning briefing with structured JSON.

    Includes: recovery status, workout prescription, pace progress,
    nutrition targets, body comp, and longevity metrics.
    Each section is null if no data is available (graceful degradation).
    Accepts ?local_date=YYYY-MM-DD to align "today" with client timezone.
    """
    # Use client's local date if provided, else fall back to UTC
    local_date_str = request.args.get("local_date")
    if local_date_str:
        try:
            from datetime import date as date_cls
            today = date_cls.fromisoformat(local_date_str)
        except ValueError:
            today = datetime.now(timezone.utc).date()
    else:
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

        # Today's nutrition
        today_nutrition = (
            session.query(NutritionLog)
            .filter(NutritionLog.date == today)
            .all()
        )
        today_cals = sum(n.calories for n in today_nutrition) if today_nutrition else 0
        today_protein = sum(n.protein_grams for n in today_nutrition) if today_nutrition else 0

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

        # Sync Withings weights (upserts last 30 days into BodyComp)
        _sync_withings_weights(session, today)

        # Weight trend for chart (last 30 days, all sources)
        weight_rows = (
            session.query(BodyComp)
            .filter(BodyComp.date >= cutoff_30d, BodyComp.date <= today)
            .order_by(BodyComp.date)
            .all()
        )
        weight_trend = [
            {
                "date": bc.date.isoformat(),
                "weight_lbs": float(bc.weight_lbs),
                "body_fat_pct": float(bc.body_fat_pct) if bc.body_fat_pct else None,
                "source": bc.source or "manual",
            }
            for bc in weight_rows
        ]

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

    # Add nutrition target — workout-based daily budget
    result["nutrition_target"] = None
    current_weight = bc_data["weight_lbs"] if bc_data else profile_data.get("weight_lbs")
    if current_weight:
        current_weight = float(current_weight)
        height = profile_data.get("height_inches")
        age = profile_data.get("age")
        sex = profile_data.get("sex")

        custom_cals = profile_data.get("goal_calorie_target")
        custom_protein = profile_data.get("goal_protein_target_grams")

        # Fetch today's workout calories from Whoop
        workout_calories = _fetch_today_workout_calories()

        if height and age and sex:
            plan = compute_nutrition_plan(
                weight_lbs=current_weight,
                height_inches=height,
                age=age,
                sex=sex,
                goal_weight_lbs=float(profile_data["goal_weight_lbs"]) if profile_data.get("goal_weight_lbs") else None,
                workout_calories=workout_calories,
                rmr_override=profile_data.get("rmr_override"),
            )

            # Custom calorie target overrides the auto budget
            if custom_cals or custom_protein:
                target_cals = custom_cals or plan.daily_budget
                target_protein = custom_protein or plan.protein_target_grams
                target_source = "custom"
            else:
                target_cals = plan.daily_budget
                target_protein = plan.protein_target_grams
                target_source = "auto"

            net = target_cals - today_cals

            result["nutrition_target"] = {
                "calories": target_cals,
                "protein_grams": target_protein,
                "target_source": target_source,
                "rmr": plan.rmr,
                "rmr_adapted": plan.rmr_adapted,
                "workout_calories": plan.workout_calories,
                "daily_budget": plan.daily_budget,
                "is_cutting": plan.is_cutting,
                "warning": plan.warning,
                "today": {
                    "calories": today_cals,
                    "protein_grams": today_protein,
                },
                "net": net,
                "yesterday": {
                    "calories": yesterday_cals,
                    "protein_grams": yesterday_protein,
                } if yesterday_cals is not None else None,
            }
        else:
            # Fallback when profile is incomplete — use weight-based estimate
            auto_protein = max(int(current_weight * 0.9), 150)
            auto_cals = int(current_weight * 13) + workout_calories

            if custom_cals or custom_protein:
                target_cals = custom_cals or auto_cals
                target_protein = custom_protein or auto_protein
                target_source = "custom"
            else:
                target_cals = auto_cals
                target_protein = auto_protein
                target_source = "auto"

            net = target_cals - today_cals

            result["nutrition_target"] = {
                "calories": target_cals,
                "protein_grams": target_protein,
                "target_source": target_source,
                "rmr": None,
                "rmr_adapted": None,
                "workout_calories": workout_calories,
                "daily_budget": target_cals,
                "is_cutting": False,
                "warning": "Set height, age, and sex in Settings for RMR-based targets.",
                "today": {
                    "calories": today_cals,
                    "protein_grams": today_protein,
                },
                "net": net,
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

    # Add weight trend
    result["weight_trend"] = weight_trend if weight_trend else None

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
