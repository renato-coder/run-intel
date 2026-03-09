"""Body composition routes — CRUD /api/body-comp."""

from datetime import date, datetime, timedelta, timezone
from decimal import Decimal

from flask import Blueprint, jsonify, request

from database import BodyComp, get_session

bp = Blueprint("body_comp", __name__)


@bp.route("/api/body-comp", methods=["GET"])
def get_body_comp():
    """Get body composition history. Supports ?days=90 filter."""
    days = int(request.args.get("days", 90))
    cutoff = datetime.now(timezone.utc).date() - timedelta(days=days)

    with get_session() as session:
        entries = (
            session.query(BodyComp)
            .filter(BodyComp.date >= cutoff)
            .order_by(BodyComp.date.desc())
            .all()
        )
        return jsonify([{
            "id": e.id,
            "date": e.date.isoformat(),
            "weight_lbs": float(e.weight_lbs),
            "body_fat_pct": float(e.body_fat_pct) if e.body_fat_pct else None,
            "notes": e.notes,
        } for e in entries])


@bp.route("/api/body-comp", methods=["POST"])
def log_body_comp():
    """Log weight + optional body fat %."""
    data = request.get_json(silent=True)
    if not data:
        return jsonify({"error": "Request must be JSON"}), 400

    weight = data.get("weight_lbs")
    if weight is None:
        return jsonify({"error": "weight_lbs is required"}), 400

    try:
        weight = float(weight)
    except (ValueError, TypeError):
        return jsonify({"error": "weight_lbs must be a number"}), 400

    if weight < 50 or weight > 500:
        return jsonify({"error": "weight_lbs must be between 50 and 500"}), 400

    body_fat = None
    if data.get("body_fat_pct") is not None:
        try:
            body_fat = float(data["body_fat_pct"])
        except (ValueError, TypeError):
            return jsonify({"error": "body_fat_pct must be a number"}), 400
        if body_fat < 3 or body_fat > 60:
            return jsonify({"error": "body_fat_pct must be between 3 and 60"}), 400

    # Optional date
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
        entry = BodyComp(
            date=log_date,
            weight_lbs=Decimal(str(weight)),
            body_fat_pct=Decimal(str(body_fat)) if body_fat is not None else None,
            notes=data.get("notes"),
        )
        session.add(entry)
        session.flush()
        result = {
            "id": entry.id,
            "date": entry.date.isoformat(),
            "weight_lbs": float(entry.weight_lbs),
            "body_fat_pct": float(entry.body_fat_pct) if entry.body_fat_pct else None,
            "notes": entry.notes,
        }

    return jsonify(result), 201


@bp.route("/api/body-comp/<int:entry_id>", methods=["DELETE"])
def delete_body_comp(entry_id):
    """Delete a body comp entry."""
    with get_session() as session:
        entry = session.query(BodyComp).get(entry_id)
        if not entry:
            return jsonify({"error": "Not found"}), 404
        session.delete(entry)

    return jsonify({"ok": True})
