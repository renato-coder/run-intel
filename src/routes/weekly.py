"""Weekly intelligence routes — scorecard and training plan."""

import json
import logging
from dataclasses import asdict
from datetime import date, datetime, timedelta, timezone

from flask import Blueprint, jsonify, request

from database import (
    BodyComp, NutritionLog, Recovery, Run, UserProfile, WeeklyPlanModel, Workout,
    get_session,
)
from services.coaching import compute_weekly_scorecard, vdot_to_marathon_time
from services.metrics_service import get_current_metrics
from services.weekly_planner import generate_weekly_plan
from whoop import WhoopClient

bp = Blueprint("weekly", __name__)
logger = logging.getLogger(__name__)


def _get_monday(d: date) -> date:
    """Return the Monday of the week containing date d."""
    return d - timedelta(days=d.weekday())


@bp.route("/api/weekly-scorecard")
def weekly_scorecard():
    """Return the weekly scorecard — goal progress at a glance."""
    local_date_str = request.args.get("local_date")
    if local_date_str:
        try:
            today = date.fromisoformat(local_date_str)
        except ValueError:
            today = datetime.now(timezone.utc).date()
    else:
        today = datetime.now(timezone.utc).date()

    monday = _get_monday(today)
    sunday = monday + timedelta(days=6)

    with get_session() as session:
        profile = session.query(UserProfile).first()
        if not profile:
            return jsonify({"error": "No profile set"}), 404

        profile_data = profile.to_dict()
        metrics = get_current_metrics(session, profile)

        # Current weight (latest body comp)
        latest_bc = session.query(BodyComp).order_by(BodyComp.date.desc()).first()
        current_weight = float(latest_bc.weight_lbs) if latest_bc else None

        # Weight 7 days ago
        week_ago_bc = (
            session.query(BodyComp)
            .filter(BodyComp.date <= today - timedelta(days=6))
            .order_by(BodyComp.date.desc())
            .first()
        )
        weight_7d_ago = float(week_ago_bc.weight_lbs) if week_ago_bc else None

        # Body fat current + 30d ago
        current_bf = float(latest_bc.body_fat_pct) if latest_bc and latest_bc.body_fat_pct else None
        bf_30d_bc = (
            session.query(BodyComp)
            .filter(BodyComp.date <= today - timedelta(days=30), BodyComp.body_fat_pct.isnot(None))
            .order_by(BodyComp.date.desc())
            .first()
        )
        bf_30d_ago = float(bf_30d_bc.body_fat_pct) if bf_30d_bc else None

        # Nutrition compliance this week
        week_nutrition = (
            session.query(NutritionLog)
            .filter(NutritionLog.date >= monday, NutritionLog.date <= today)
            .all()
        )
        # Group by day
        daily_cals = {}
        daily_protein = {}
        for n in week_nutrition:
            d = n.date.isoformat()
            daily_cals[d] = daily_cals.get(d, 0) + n.calories
            daily_protein[d] = daily_protein.get(d, 0) + n.protein_grams

        nutrition_days = len(daily_cals)
        target_cals = profile_data.get("goal_calorie_target") or 2200
        target_protein = profile_data.get("goal_protein_target_grams") or max(int((current_weight or 190) * 1.0), 150)
        hit_cal = sum(1 for c in daily_cals.values() if c <= target_cals * 1.1)  # within 10% of target
        hit_protein = sum(1 for p in daily_protein.values() if p >= target_protein * 0.8)  # within 80%

        # Weekly miles
        week_runs = (
            session.query(Run)
            .filter(Run.date >= monday, Run.date <= today)
            .all()
        )
        weekly_miles = sum(r.distance_miles or 0 for r in week_runs)

        # Average recovery this week
        week_recovery = (
            session.query(Recovery)
            .filter(Recovery.date >= monday, Recovery.date <= today,
                    Recovery.recovery_score.isnot(None))
            .all()
        )
        avg_recovery = (
            round(sum(r.recovery_score for r in week_recovery) / len(week_recovery), 1)
            if week_recovery else None
        )

    scorecard = compute_weekly_scorecard(
        current_weight=current_weight,
        goal_weight=float(profile_data["goal_weight_lbs"]) if profile_data.get("goal_weight_lbs") else None,
        weight_7d_ago=weight_7d_ago,
        vdot=metrics.vdot,
        goal_marathon_min=float(profile_data["goal_marathon_time_min"]) if profile_data.get("goal_marathon_time_min") else None,
        ef_trend=metrics.ef_trend,
        current_bf=current_bf,
        goal_bf=float(profile_data["goal_body_fat_pct"]) if profile_data.get("goal_body_fat_pct") else None,
        bf_30d_ago=bf_30d_ago,
        nutrition_days=nutrition_days,
        nutrition_hit_cal=hit_cal,
        nutrition_hit_protein=hit_protein,
        zone2_minutes=metrics.zone2_minutes_week or 0,
        avg_recovery=avg_recovery,
        weekly_miles=weekly_miles,
        week_ending=sunday.isoformat(),
    )

    return jsonify(asdict(scorecard))


@bp.route("/api/weekly-plan")
def weekly_plan():
    """Return current week's training plan. Generates if none exists."""
    local_date_str = request.args.get("local_date")
    if local_date_str:
        try:
            today = date.fromisoformat(local_date_str)
        except ValueError:
            today = datetime.now(timezone.utc).date()
    else:
        today = datetime.now(timezone.utc).date()

    monday = _get_monday(today)

    with get_session() as session:
        # Check for existing plan
        existing = (
            session.query(WeeklyPlanModel)
            .filter(WeeklyPlanModel.week_start == monday)
            .first()
        )
        if existing:
            plan = json.loads(existing.plan_json)
            plan["from_cache"] = True
            return jsonify(plan)

        # Generate new plan
        profile = session.query(UserProfile).first()
        if not profile:
            return jsonify({"error": "Set up your profile first"}), 404

        profile_data = profile.to_dict()
        metrics = get_current_metrics(session, profile)

        # Check minimum data
        if not metrics.vdot:
            return jsonify({
                "error": "Need more run data to generate a plan",
                "detail": "Log at least one run of 3+ miles with heart rate data.",
            }), 422

        # Latest recovery
        latest_rec = (
            session.query(Recovery)
            .filter(Recovery.recovery_score.isnot(None))
            .order_by(Recovery.date.desc())
            .first()
        )
        latest_recovery = latest_rec.recovery_score if latest_rec else None

        plan_obj = generate_weekly_plan(metrics, profile_data, latest_recovery, monday)

        plan_dict = {
            "week_start": plan_obj.week_start,
            "weekly_miles_target": plan_obj.weekly_miles_target,
            "days": plan_obj.days,
            "generation_context": plan_obj.generation_context,
        }

        metrics_snap = {
            "vdot": metrics.vdot,
            "ctl": metrics.ctl,
            "atl": metrics.atl,
            "tsb": metrics.tsb,
            "acwr": metrics.acwr,
            "ef_trend": metrics.ef_trend,
        }

        # Store — ON CONFLICT DO NOTHING to prevent race conditions
        try:
            session.execute(
                WeeklyPlanModel.__table__.insert()
                .values(
                    week_start=monday,
                    plan_json=json.dumps(plan_dict),
                    metrics_snapshot=json.dumps(metrics_snap),
                )
                .on_conflict_do_nothing(index_elements=["week_start"])
            )
        except Exception:
            logger.exception("Error saving weekly plan")

        plan_dict["from_cache"] = False
        return jsonify(plan_dict)


@bp.route("/api/weekly-plan/regenerate", methods=["POST"])
def regenerate_plan():
    """Force regenerate this week's plan."""
    local_date_str = request.args.get("local_date")
    if local_date_str:
        try:
            today = date.fromisoformat(local_date_str)
        except ValueError:
            today = datetime.now(timezone.utc).date()
    else:
        today = datetime.now(timezone.utc).date()

    monday = _get_monday(today)

    with get_session() as session:
        # Delete existing plan for this week
        session.query(WeeklyPlanModel).filter(WeeklyPlanModel.week_start == monday).delete()
        session.flush()

    # Redirect to the GET endpoint which will generate a fresh plan
    return weekly_plan()


@bp.route("/api/workouts")
def get_workouts():
    """Return workouts for the current week, syncing from Whoop first."""
    local_date_str = request.args.get("local_date")
    if local_date_str:
        try:
            today = date.fromisoformat(local_date_str)
        except ValueError:
            today = datetime.now(timezone.utc).date()
    else:
        today = datetime.now(timezone.utc).date()

    monday = _get_monday(today)
    sunday = monday + timedelta(days=6)

    # Sync from Whoop (best-effort)
    try:
        _sync_whoop_workouts(monday, sunday)
    except Exception:
        logger.exception("Error syncing Whoop workouts")

    with get_session() as session:
        rows = (
            session.query(Workout)
            .filter(Workout.date >= monday, Workout.date <= sunday)
            .order_by(Workout.date)
            .all()
        )
        result = [w.to_dict() for w in rows]

    return jsonify(result)


def _sync_whoop_workouts(monday: date, sunday: date):
    """Pull workouts from Whoop for the given week and upsert into DB."""
    client = WhoopClient()
    if not client.access_token:
        return

    start_iso = datetime.combine(monday, datetime.min.time(), tzinfo=timezone.utc).isoformat()
    end_iso = datetime.combine(sunday + timedelta(days=1), datetime.min.time(), tzinfo=timezone.utc).isoformat()

    whoop_workouts = client.get_workouts(start=start_iso, end=end_iso)

    with get_session() as session:
        for w in whoop_workouts:
            whoop_id = str(w.get("id", ""))
            if not whoop_id:
                continue

            # Skip if already stored
            existing = session.query(Workout).filter(Workout.whoop_id == whoop_id).first()
            if existing:
                continue

            sport_name = w.get("sport_name", "unknown").lower()
            sport_id = w.get("sport_id")
            score = w.get("score", {})
            strain = score.get("strain")
            kilojoule = score.get("kilojoule")

            # Compute duration from start/end
            duration_min = None
            start_str = w.get("start")
            end_str = w.get("end")
            if start_str and end_str:
                try:
                    start_dt = datetime.fromisoformat(start_str.replace("Z", "+00:00"))
                    end_dt = datetime.fromisoformat(end_str.replace("Z", "+00:00"))
                    duration_min = round((end_dt - start_dt).total_seconds() / 60, 1)
                except (ValueError, TypeError):
                    pass

            # Date from end time (workout date = when it ended, local-ish)
            workout_date = None
            if end_str:
                try:
                    end_dt = datetime.fromisoformat(end_str.replace("Z", "+00:00"))
                    # Shift to MST (UTC-7) for local date
                    local_dt = end_dt - timedelta(hours=7)
                    workout_date = local_dt.date()
                except (ValueError, TypeError):
                    pass
            if not workout_date:
                continue

            session.add(Workout(
                date=workout_date,
                sport_name=sport_name,
                sport_id=sport_id,
                strain=strain,
                kilojoule=kilojoule,
                duration_min=duration_min,
                whoop_id=whoop_id,
            ))
