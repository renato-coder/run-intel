"""Nutrition routes — CRUD /api/nutrition."""

from datetime import date, datetime, timedelta, timezone

from flask import Blueprint, jsonify, request
from sqlalchemy import func as sa_func

from database import BodyComp, NutritionLog, UserProfile, Workout, get_session
from services.coaching import compute_nutrition_plan, compute_weekly_deficit_target
from utils import validate_log_date

bp = Blueprint("nutrition", __name__)


@bp.route("/api/nutrition", methods=["GET"])
def get_nutrition():
    """Get nutrition logs. Supports ?days=30 and ?date=YYYY-MM-DD filters."""
    date_filter = request.args.get("date")
    try:
        days = int(request.args.get("days", 30))
    except (ValueError, TypeError):
        return jsonify({"error": "days must be an integer"}), 400

    with get_session() as session:
        query = session.query(NutritionLog).order_by(NutritionLog.date.desc())

        if date_filter:
            try:
                d = date.fromisoformat(date_filter)
                query = query.filter(NutritionLog.date == d)
            except ValueError:
                return jsonify({"error": "Invalid date format. Use YYYY-MM-DD."}), 400
        else:
            cutoff = datetime.now(timezone.utc).date() - timedelta(days=days)
            query = query.filter(NutritionLog.date >= cutoff)

        logs = query.all()
        return jsonify([{
            "id": log.id,
            "date": log.date.isoformat(),
            "calories": log.calories,
            "protein_grams": log.protein_grams,
            "notes": log.notes,
        } for log in logs])


@bp.route("/api/nutrition", methods=["POST"])
def log_nutrition():
    """Log calories + protein for a day."""
    data = request.get_json(silent=True)
    if not data:
        return jsonify({"error": "Request must be JSON"}), 400

    # Validate required fields
    calories = data.get("calories")
    protein = data.get("protein_grams")
    if calories is None or protein is None:
        return jsonify({"error": "calories and protein_grams are required"}), 400

    try:
        calories = int(calories)
        protein = int(protein)
    except (ValueError, TypeError):
        return jsonify({"error": "calories and protein_grams must be integers"}), 400

    if calories < 0 or protein < 0:
        return jsonify({"error": "calories and protein_grams must be >= 0"}), 400

    # Optional date (defaults to today UTC, backdating up to 7 days)
    log_date, err = validate_log_date(data.get("date"))
    if err:
        return jsonify({"error": err}), 400

    with get_session() as session:
        entry = NutritionLog(
            date=log_date,
            calories=calories,
            protein_grams=protein,
            notes=data.get("notes"),
        )
        session.add(entry)
        session.flush()
        result = {
            "id": entry.id,
            "date": entry.date.isoformat(),
            "calories": entry.calories,
            "protein_grams": entry.protein_grams,
            "notes": entry.notes,
        }

    return jsonify(result), 201


@bp.route("/api/nutrition/<int:entry_id>", methods=["PUT"])
def update_nutrition(entry_id):
    """Update a nutrition entry."""
    data = request.get_json(silent=True)
    if not data:
        return jsonify({"error": "Request must be JSON"}), 400

    with get_session() as session:
        entry = session.query(NutritionLog).get(entry_id)
        if not entry:
            return jsonify({"error": "Not found"}), 404

        if "calories" in data:
            try:
                cal = int(data["calories"])
            except (ValueError, TypeError):
                return jsonify({"error": "calories must be an integer"}), 400
            if cal < 0:
                return jsonify({"error": "calories must be >= 0"}), 400
            entry.calories = cal
        if "protein_grams" in data:
            try:
                prot = int(data["protein_grams"])
            except (ValueError, TypeError):
                return jsonify({"error": "protein_grams must be an integer"}), 400
            if prot < 0:
                return jsonify({"error": "protein_grams must be >= 0"}), 400
            entry.protein_grams = prot
        if "notes" in data:
            entry.notes = data["notes"]

        session.flush()
        result = {
            "id": entry.id,
            "date": entry.date.isoformat(),
            "calories": entry.calories,
            "protein_grams": entry.protein_grams,
            "notes": entry.notes,
        }

    return jsonify(result)


@bp.route("/api/nutrition/<int:entry_id>", methods=["DELETE"])
def delete_nutrition(entry_id):
    """Delete a nutrition entry."""
    with get_session() as session:
        entry = session.query(NutritionLog).get(entry_id)
        if not entry:
            return jsonify({"error": "Not found"}), 404
        session.delete(entry)

    return jsonify({"ok": True})


def _get_monday(d: date) -> date:
    """Return the Monday of the week containing date d."""
    return d - timedelta(days=d.weekday())


@bp.route("/api/nutrition/weekly-summary")
def weekly_summary():
    """Return per-day budget, intake, and deficit for the current week."""
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
        profile = session.query(UserProfile).first()
        if not profile:
            return jsonify({"error": "No profile set"}), 404

        pd = profile.to_dict()

        # Current weight from latest body comp
        latest_bc = session.query(BodyComp).order_by(BodyComp.date.desc()).first()
        current_weight = float(latest_bc.weight_lbs) if latest_bc else (float(pd["weight_lbs"]) if pd.get("weight_lbs") else None)

        if not current_weight:
            return jsonify({"error": "No weight data available"}), 422

        # Compute RMR (once — same for all days in the week)
        height = pd.get("height_inches")
        age = pd.get("age")
        sex = pd.get("sex")
        goal_weight = float(pd["goal_weight_lbs"]) if pd.get("goal_weight_lbs") else None
        rmr_override = pd.get("rmr_override")

        has_full_profile = bool(height and age and sex)

        if has_full_profile:
            base_plan = compute_nutrition_plan(
                weight_lbs=current_weight,
                height_inches=height,
                age=age,
                sex=sex,
                goal_weight_lbs=goal_weight,
                workout_calories=0,
                rmr_override=rmr_override,
            )
            rmr_adapted = base_plan.rmr_adapted
        else:
            rmr_adapted = int(current_weight * 13)

        # Nutrition logs for the week grouped by date
        nutrition_rows = (
            session.query(
                NutritionLog.date,
                sa_func.sum(NutritionLog.calories).label("total_cal"),
                sa_func.sum(NutritionLog.protein_grams).label("total_protein"),
            )
            .filter(NutritionLog.date >= monday, NutritionLog.date <= today)
            .group_by(NutritionLog.date)
            .all()
        )
        daily_nutrition = {row.date: {"cal": int(row.total_cal), "protein": int(row.total_protein)} for row in nutrition_rows}

        # Workout kilojoules for the week grouped by date
        workout_rows = (
            session.query(
                Workout.date,
                sa_func.sum(Workout.kilojoule).label("total_kj"),
            )
            .filter(Workout.date >= monday, Workout.date <= today, Workout.kilojoule.isnot(None))
            .group_by(Workout.date)
            .all()
        )
        daily_workout_kj = {row.date: float(row.total_kj) for row in workout_rows}

    # Build per-day summary
    days = []
    weekly_deficit_actual = 0
    for offset in range((today - monday).days + 1):
        d = monday + timedelta(days=offset)
        nut = daily_nutrition.get(d)
        if not nut:
            # No nutrition logged — skip this day (no false deficit)
            days.append({
                "date": d.isoformat(),
                "day_label": d.strftime("%A"),
                "calories_in": None,
                "protein_in": None,
                "budget": None,
                "deficit": None,
                "workout_cal": None,
                "has_data": False,
            })
            continue

        kj = daily_workout_kj.get(d, 0)
        workout_cal = round(kj / 4.184) if kj else 0
        budget = rmr_adapted + workout_cal
        deficit = budget - nut["cal"]
        weekly_deficit_actual += deficit

        days.append({
            "date": d.isoformat(),
            "day_label": d.strftime("%A"),
            "calories_in": nut["cal"],
            "protein_in": nut["protein"],
            "budget": budget,
            "deficit": deficit,
            "workout_cal": workout_cal,
            "has_data": True,
        })

    # Weekly deficit target from goals
    goal_target_date = pd.get("goal_target_date")
    deficit_target = compute_weekly_deficit_target(
        current_weight=current_weight,
        goal_weight=goal_weight,
        goal_target_date=goal_target_date,
        today=today.isoformat(),
    )

    weekly_deficit_needed = deficit_target.get("weekly_deficit_needed", 0)
    weekly_deficit_remaining = max(0, weekly_deficit_needed - weekly_deficit_actual) if weekly_deficit_needed else None

    return jsonify({
        "days": days,
        "weekly_deficit_target": weekly_deficit_needed,
        "weekly_deficit_actual": weekly_deficit_actual,
        "weekly_deficit_remaining": weekly_deficit_remaining,
        "deficit_target": deficit_target,
        "rmr_adapted": rmr_adapted,
        "has_full_profile": has_full_profile,
    })
