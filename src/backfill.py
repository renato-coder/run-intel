"""
Backfill historical Whoop data into local CSVs.

Pulls ALL workout history (filters to running) and ALL recovery history.
Skips dates already present in the CSV files.

Usage:
    python src/backfill.py
"""

import csv
from datetime import datetime
from pathlib import Path

from whoop import WhoopClient

DATA_DIR = Path(__file__).resolve().parent.parent / "data"
RUNS_CSV = DATA_DIR / "runs.csv"
RECOVERY_CSV = DATA_DIR / "recovery.csv"

RUN_COLUMNS = [
    "date",
    "distance_miles",
    "time_minutes",
    "pace_per_mile",
    "avg_hr",
    "max_hr",
    "strain",
    "whoop_distance_meters",
    "zone_zero_milli",
    "zone_one_milli",
    "zone_two_milli",
    "zone_three_milli",
    "zone_four_milli",
    "zone_five_milli",
    "shoes",
]

RECOVERY_COLUMNS = [
    "date",
    "recovery_score",
    "hrv",
    "resting_hr",
]


def load_existing_dates(csv_path):
    """Read existing CSV and return a set of dates already recorded."""
    dates = set()
    if csv_path.exists():
        with open(csv_path) as f:
            reader = csv.DictReader(f)
            for row in reader:
                dates.add(row["date"])
    return dates


def parse_date(iso_string):
    """Extract YYYY-MM-DD from an ISO timestamp."""
    if not iso_string:
        return None
    return datetime.fromisoformat(iso_string.replace("Z", "+00:00")).strftime("%Y-%m-%d")


def backfill_runs(client):
    """Pull all running workouts from Whoop and append new ones to runs.csv."""
    DATA_DIR.mkdir(parents=True, exist_ok=True)
    existing = load_existing_dates(RUNS_CSV)

    print("Fetching all workouts from Whoop...")
    workouts = client.get_workouts()

    # Filter to running only
    runs = [w for w in workouts if w.get("sport_name", "").lower() == "running"]
    print(f"Found {len(runs)} running workouts total.")

    file_exists = RUNS_CSV.exists()
    added = 0

    with open(RUNS_CSV, "a", newline="") as f:
        writer = csv.DictWriter(f, fieldnames=RUN_COLUMNS)
        if not file_exists:
            writer.writeheader()

        for run in runs:
            date = parse_date(run.get("start"))
            if not date or date in existing:
                continue

            score = run.get("score", {})
            zones = score.get("zone_durations", {})

            # Calculate distance in miles and duration in minutes from Whoop data
            distance_m = score.get("distance_meter", 0) or 0
            distance_miles = round(distance_m / 1609.34, 2) if distance_m else ""

            start_dt = datetime.fromisoformat(run["start"].replace("Z", "+00:00"))
            end_dt = datetime.fromisoformat(run["end"].replace("Z", "+00:00"))
            time_minutes = round((end_dt - start_dt).total_seconds() / 60, 1)

            # Calculate pace
            pace = ""
            if distance_miles and distance_miles > 0:
                pace_min = time_minutes / distance_miles
                mins = int(pace_min)
                secs = int((pace_min - mins) * 60)
                pace = f"{mins}:{secs:02d}"

            writer.writerow({
                "date": date,
                "distance_miles": distance_miles,
                "time_minutes": time_minutes,
                "pace_per_mile": pace,
                "avg_hr": score.get("average_heart_rate", ""),
                "max_hr": score.get("max_heart_rate", ""),
                "strain": score.get("strain", ""),
                "whoop_distance_meters": distance_m or "",
                "zone_zero_milli": zones.get("zone_zero_milli", ""),
                "zone_one_milli": zones.get("zone_one_milli", ""),
                "zone_two_milli": zones.get("zone_two_milli", ""),
                "zone_three_milli": zones.get("zone_three_milli", ""),
                "zone_four_milli": zones.get("zone_four_milli", ""),
                "zone_five_milli": zones.get("zone_five_milli", ""),
                "shoes": "",
            })
            existing.add(date)
            added += 1

    print(f"Added {added} new running records to {RUNS_CSV.name}.")
    return added


def backfill_recovery(client):
    """Pull all recovery records from Whoop and append new ones to recovery.csv."""
    DATA_DIR.mkdir(parents=True, exist_ok=True)
    existing = load_existing_dates(RECOVERY_CSV)

    print("Fetching all recovery records from Whoop...")
    recoveries = client.get_recovery()
    print(f"Found {len(recoveries)} recovery records total.")

    file_exists = RECOVERY_CSV.exists()
    added = 0

    with open(RECOVERY_CSV, "a", newline="") as f:
        writer = csv.DictWriter(f, fieldnames=RECOVERY_COLUMNS)
        if not file_exists:
            writer.writeheader()

        for rec in recoveries:
            # Recovery date comes from the cycle it belongs to
            date = parse_date(rec.get("created_at") or rec.get("updated_at"))
            if not date or date in existing:
                continue

            score = rec.get("score", {})
            writer.writerow({
                "date": date,
                "recovery_score": score.get("recovery_score", ""),
                "hrv": score.get("hrv_rmssd_milli", ""),
                "resting_hr": score.get("resting_heart_rate", ""),
            })
            existing.add(date)
            added += 1

    print(f"Added {added} new recovery records to {RECOVERY_CSV.name}.")
    return added


def main():
    client = WhoopClient()
    print("\n=== Backfilling Whoop Data ===\n")
    backfill_runs(client)
    print()
    backfill_recovery(client)
    print("\nDone.\n")


if __name__ == "__main__":
    main()
