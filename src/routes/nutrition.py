"""Nutrition routes — CRUD /api/nutrition."""

from datetime import date, datetime, timedelta, timezone

from flask import Blueprint, jsonify, request

from database import NutritionLog, get_session

bp = Blueprint("nutrition", __name__)


@bp.route("/api/nutrition", methods=["GET"])
def get_nutrition():
    """Get nutrition logs. Supports ?days=30 and ?date=YYYY-MM-DD filters."""
    date_filter = request.args.get("date")
    days = int(request.args.get("days", 30))

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
    log_date = datetime.now(timezone.utc).date()
    if data.get("date"):
        try:
            log_date = date.fromisoformat(data["date"])
        except (ValueError, TypeError):
            return jsonify({"error": "date must be YYYY-MM-DD format"}), 400
        today = datetime.now(timezone.utc).date()
        if log_date > today:
            return jsonify({"error": "Cannot log future dates"}), 400
        if (today - log_date).days > 7:
            return jsonify({"error": "Cannot backdate more than 7 days"}), 400

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
            entry.calories = int(data["calories"])
        if "protein_grams" in data:
            entry.protein_grams = int(data["protein_grams"])
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
