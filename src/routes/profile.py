"""Profile routes — GET/PUT /api/profile."""

from datetime import date, datetime, timezone

from flask import Blueprint, jsonify, request

from database import UserProfile, get_session

bp = Blueprint("profile", __name__)


@bp.route("/api/profile", methods=["GET"])
def get_profile():
    """Get the user profile (single user)."""
    with get_session() as session:
        profile = session.query(UserProfile).first()
        if not profile:
            return jsonify(None)
        return jsonify(profile.to_dict())


@bp.route("/api/profile", methods=["PUT"])
def update_profile():
    """Create or update the user profile (upsert)."""
    data = request.get_json(silent=True)
    if not data:
        return jsonify({"error": "Request must be JSON"}), 400

    # Validate fields
    allowed = {
        "age", "height_inches", "weight_lbs", "max_hr", "body_fat_pct",
        "goal_marathon_time_min", "goal_body_fat_pct", "goal_weight_lbs",
        "goal_target_date", "goal_calorie_target", "goal_protein_target_grams",
        "sex", "rmr_override",
    }
    updates = {k: v for k, v in data.items() if k in allowed}

    # Validate date format
    if "goal_target_date" in updates and updates["goal_target_date"]:
        try:
            date.fromisoformat(updates["goal_target_date"])
        except (ValueError, TypeError):
            return jsonify({"error": "goal_target_date must be YYYY-MM-DD format"}), 400

    # Validate sex field
    if "sex" in updates and updates["sex"] not in (None, "", "male", "female"):
        return jsonify({"error": "sex must be 'male' or 'female'"}), 400
    if "sex" in updates and updates["sex"] == "":
        updates["sex"] = None

    # Coerce numeric fields
    int_fields = {"age", "height_inches", "max_hr", "goal_calorie_target", "goal_protein_target_grams", "rmr_override"}
    numeric_fields = {"weight_lbs", "body_fat_pct", "goal_marathon_time_min", "goal_body_fat_pct", "goal_weight_lbs"}
    for k in list(updates.keys()):
        if updates[k] is None or updates[k] == "":
            updates[k] = None
            continue
        if k in int_fields:
            try:
                updates[k] = int(updates[k])
            except (ValueError, TypeError):
                return jsonify({"error": f"{k} must be an integer"}), 400
        elif k in numeric_fields:
            try:
                updates[k] = float(updates[k])
            except (ValueError, TypeError):
                return jsonify({"error": f"{k} must be a number"}), 400

    # Auto-estimate max_hr if age provided and max_hr not set
    if "age" in updates and updates["age"] and "max_hr" not in updates:
        updates.setdefault("max_hr", int(208 - 0.7 * updates["age"]))

    with get_session() as session:
        profile = session.query(UserProfile).first()
        if profile:
            for k, v in updates.items():
                setattr(profile, k, v)
        else:
            profile = UserProfile(**updates)
            session.add(profile)
        session.flush()
        result = profile.to_dict()

    return jsonify(result)
