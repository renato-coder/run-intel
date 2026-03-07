"""
Seed the PostgreSQL database from local CSV files.

Usage:
    python src/upload_history.py

NOTE: This truncates existing data before inserting. Safe to re-run.
"""

import logging
from datetime import date
from pathlib import Path

import pandas as pd

from database import Recovery, Run, get_session, init_db
from utils import safe_float, safe_int

logger = logging.getLogger(__name__)

DATA_DIR = Path(__file__).resolve().parent.parent / "data"
RUNS_CSV = DATA_DIR / "runs.csv"
RECOVERY_CSV = DATA_DIR / "recovery.csv"


def upload_runs():
    if not RUNS_CSV.exists():
        print("No runs.csv found, skipping.")
        return

    df = pd.read_csv(RUNS_CSV)
    with get_session() as session:
        # Truncate before re-seeding to prevent duplicates
        session.query(Run).delete()
        count = 0

        for _, row in df.iterrows():
            run = Run(
                date=date.fromisoformat(str(row["date"]).split(" ")[0]),
                distance_miles=safe_float(row.get("distance_miles")),
                time_minutes=safe_float(row.get("time_minutes")),
                pace_per_mile=str(row.get("pace_per_mile")) if pd.notna(row.get("pace_per_mile")) else None,
                avg_hr=safe_int(row.get("avg_hr")),
                max_hr=safe_int(row.get("max_hr")),
                strain=safe_float(row.get("strain")),
                whoop_distance_meters=safe_float(row.get("whoop_distance_meters")),
                zone_zero_milli=safe_int(row.get("zone_zero_milli")),
                zone_one_milli=safe_int(row.get("zone_one_milli")),
                zone_two_milli=safe_int(row.get("zone_two_milli")),
                zone_three_milli=safe_int(row.get("zone_three_milli")),
                zone_four_milli=safe_int(row.get("zone_four_milli")),
                zone_five_milli=safe_int(row.get("zone_five_milli")),
                shoes=str(row.get("shoes")) if pd.notna(row.get("shoes")) else None,
            )
            session.add(run)
            count += 1

    print(f"Uploaded {count} runs.")


def upload_recovery():
    if not RECOVERY_CSV.exists():
        print("No recovery.csv found, skipping.")
        return

    df = pd.read_csv(RECOVERY_CSV)
    with get_session() as session:
        # Truncate before re-seeding to prevent duplicates
        session.query(Recovery).delete()
        count = 0

        for _, row in df.iterrows():
            rec = Recovery(
                date=date.fromisoformat(str(row["date"]).split(" ")[0]),
                recovery_score=safe_float(row.get("recovery_score")),
                hrv=safe_float(row.get("hrv")),
                resting_hr=safe_float(row.get("resting_hr")),
            )
            session.add(rec)
            count += 1

    print(f"Uploaded {count} recovery records.")


if __name__ == "__main__":
    logging.basicConfig(level=logging.INFO)
    print("Initializing database tables...")
    init_db()

    print("Uploading runs...")
    upload_runs()

    print("Uploading recovery...")
    upload_recovery()

    print("Done!")
