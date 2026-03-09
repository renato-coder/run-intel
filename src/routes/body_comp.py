"""Body composition routes — CRUD /api/body-comp."""

import base64
import logging
from datetime import datetime, timedelta, timezone
from decimal import Decimal

from flask import Blueprint, Response, jsonify, request

from database import BodyComp, get_session
from utils import validate_log_date

logger = logging.getLogger(__name__)
bp = Blueprint("body_comp", __name__)


@bp.route("/api/body-comp", methods=["GET"])
def get_body_comp():
    """Get body composition history. Supports ?days=90 filter."""
    try:
        days = int(request.args.get("days", 90))
    except (ValueError, TypeError):
        return jsonify({"error": "days must be an integer"}), 400
    cutoff = datetime.now(timezone.utc).date() - timedelta(days=days)

    with get_session() as session:
        has_photo_expr = BodyComp.photo.isnot(None).label("has_photo")
        rows = (
            session.query(BodyComp, has_photo_expr)
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
            "has_photo": bool(has_photo),
        } for e, has_photo in rows])


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

    # Optional date (defaults to today UTC, backdating up to 7 days)
    log_date, err = validate_log_date(data.get("date"))
    if err:
        return jsonify({"error": err}), 400

    # Optional photo (base64-encoded JPEG/PNG)
    photo_bytes = None
    if data.get("photo_base64"):
        try:
            raw = base64.b64decode(data["photo_base64"], validate=True)
        except Exception:
            return jsonify({"error": "Invalid base64 encoding for photo"}), 400

        from services.photo import process_photo

        try:
            result = process_photo(raw)
            photo_bytes = result["photo"]
        except ValueError as e:
            return jsonify({"error": str(e)}), 400

    with get_session() as session:
        entry = BodyComp(
            date=log_date,
            weight_lbs=Decimal(str(weight)),
            body_fat_pct=Decimal(str(body_fat)) if body_fat is not None else None,
            notes=data.get("notes"),
            photo=photo_bytes,
        )
        session.add(entry)
        session.flush()
        result = {
            "id": entry.id,
            "date": entry.date.isoformat(),
            "weight_lbs": float(entry.weight_lbs),
            "body_fat_pct": float(entry.body_fat_pct) if entry.body_fat_pct else None,
            "notes": entry.notes,
            "has_photo": photo_bytes is not None,
        }

    return jsonify(result), 201


@bp.route("/api/body-comp/<int:entry_id>/photo", methods=["GET"])
def get_body_comp_photo(entry_id):
    """Return the photo for a body comp entry as JPEG bytes."""
    from sqlalchemy.orm import undefer

    with get_session() as session:
        entry = (
            session.query(BodyComp)
            .options(undefer(BodyComp.photo))
            .filter(BodyComp.id == entry_id)
            .first()
        )
        if not entry:
            return jsonify({"error": "Not found"}), 404
        if not entry.photo:
            return jsonify({"error": "No photo for this entry"}), 404

        return Response(
            entry.photo,
            mimetype="image/jpeg",
            headers={"Cache-Control": "public, max-age=86400"},
        )


@bp.route("/api/body-comp/<int:entry_id>", methods=["DELETE"])
def delete_body_comp(entry_id):
    """Delete a body comp entry."""
    with get_session() as session:
        entry = session.query(BodyComp).get(entry_id)
        if not entry:
            return jsonify({"error": "Not found"}), 404
        session.delete(entry)

    return jsonify({"ok": True})
