"""Briefing routes — GET /api/briefing, GET /api/recovery/today, GET /api/snapshot."""

from datetime import datetime, timedelta, timezone

from flask import Blueprint, jsonify

from briefing import generate_briefing
from database import Recovery, Run, get_session

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
    """Return the morning briefing based on recovery, HRV, and strain data."""
    today = datetime.now(timezone.utc).date()
    cutoff_30d = today - timedelta(days=30)

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

    result = generate_briefing(today_recovery, recovery_history, run_history)
    if result is None:
        return jsonify({"status": "unavailable", "status_label": "No recovery data available yet."})
    result["recovery_date"] = recovery_date
    if note:
        result["note"] = note
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
