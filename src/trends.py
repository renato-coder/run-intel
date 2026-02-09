"""
Run Intel analysis engine.

Reads runs.csv and recovery.csv to produce running performance insights:
  - Pace vs HR efficiency over time
  - 7-day and 30-day rolling averages (pace, avg HR, strain)
  - Cardiac drift detection (HR creeping up at same pace = fatigue)
  - Recovery-to-performance correlation
  - Per-shoe breakdown

Usage:
    python src/trends.py
"""

import pandas as pd
from pathlib import Path

DATA_DIR = Path(__file__).resolve().parent.parent / "data"


def load_data():
    """Load runs and recovery CSVs into DataFrames."""
    runs_path = DATA_DIR / "runs.csv"
    recovery_path = DATA_DIR / "recovery.csv"

    if not runs_path.exists():
        print("No runs.csv found. Run backfill.py first.")
        return None, None

    runs = pd.read_csv(runs_path, parse_dates=["date"])
    runs = runs.sort_values("date").reset_index(drop=True)

    recovery = None
    if recovery_path.exists():
        recovery = pd.read_csv(recovery_path, parse_dates=["date"])
        recovery = recovery.sort_values("date").reset_index(drop=True)

    return runs, recovery


def pace_to_minutes(pace_str):
    """Convert pace string like '7:49' to float minutes (7.817)."""
    if pd.isna(pace_str) or not isinstance(pace_str, str) or ":" not in pace_str:
        return None
    parts = pace_str.split(":")
    return int(parts[0]) + int(parts[1]) / 60


def efficiency_analysis(runs):
    """
    Pace vs HR efficiency: lower HR at the same pace = better fitness.
    Efficiency ratio = avg_hr / pace_minutes (lower is better).
    """
    print("\n" + "=" * 60)
    print("  EFFICIENCY: Pace vs Heart Rate")
    print("=" * 60)

    df = runs.dropna(subset=["avg_hr"]).copy()
    df["pace_min"] = df["pace_per_mile"].apply(pace_to_minutes)
    df = df.dropna(subset=["pace_min"])

    if len(df) < 2:
        print("  Not enough data with HR for efficiency analysis.\n")
        return

    df["efficiency"] = df["avg_hr"] / df["pace_min"]

    # Compare first third vs last third
    n = len(df)
    third = max(n // 3, 1)
    early = df.head(third)["efficiency"].mean()
    recent = df.tail(third)["efficiency"].mean()
    change = ((recent - early) / early) * 100

    direction = "IMPROVED" if change < 0 else "DECLINED"
    print(f"  Early avg efficiency ratio:  {early:.1f} (HR / pace)")
    print(f"  Recent avg efficiency ratio: {recent:.1f} (HR / pace)")
    print(f"  Change: {change:+.1f}% ({direction})")
    print(f"  (Lower ratio = better aerobic fitness)\n")


def rolling_averages(runs):
    """7-day and 30-day rolling averages for pace, HR, and strain."""
    print("=" * 60)
    print("  ROLLING AVERAGES")
    print("=" * 60)

    df = runs.set_index("date").copy()
    df["pace_min"] = df["pace_per_mile"].apply(pace_to_minutes)

    for col, label in [("pace_min", "Pace (min/mi)"), ("avg_hr", "Avg HR"), ("strain", "Strain")]:
        if col not in df.columns:
            continue
        series = df[col].dropna()
        if len(series) < 7:
            print(f"\n  {label}: Not enough data for rolling averages.")
            continue

        avg_7 = series.rolling("7D").mean().iloc[-1]
        avg_30 = series.rolling("30D").mean().iloc[-1] if len(series) >= 7 else None

        print(f"\n  {label}:")
        print(f"    7-day avg:  {avg_7:.1f}")
        if avg_30 is not None:
            print(f"    30-day avg: {avg_30:.1f}")

    print()


def cardiac_drift(runs):
    """
    Detect cardiac drift: is HR trending up at a similar pace?
    This signals accumulated fatigue or overtraining.
    """
    print("=" * 60)
    print("  CARDIAC DRIFT DETECTION")
    print("=" * 60)

    df = runs.dropna(subset=["avg_hr"]).copy()
    df["pace_min"] = df["pace_per_mile"].apply(pace_to_minutes)
    df = df.dropna(subset=["pace_min"])

    if len(df) < 5:
        print("  Not enough data to detect cardiac drift.\n")
        return

    # Bin runs by similar pace (within 0.5 min/mi) and see if HR is rising
    median_pace = df["pace_min"].median()
    similar = df[(df["pace_min"] >= median_pace - 0.25) & (df["pace_min"] <= median_pace + 0.25)]

    if len(similar) < 4:
        print(f"  Not enough runs near your typical pace ({median_pace:.1f} min/mi).\n")
        return

    # Split into early and recent halves
    mid = len(similar) // 2
    early_hr = similar.iloc[:mid]["avg_hr"].mean()
    recent_hr = similar.iloc[mid:]["avg_hr"].mean()
    diff = recent_hr - early_hr

    pace_range = f"{median_pace - 0.25:.1f}-{median_pace + 0.25:.1f}"
    print(f"  At similar pace ({pace_range} min/mi):")
    print(f"    Early avg HR:  {early_hr:.0f} bpm")
    print(f"    Recent avg HR: {recent_hr:.0f} bpm")

    if diff > 3:
        print(f"    WARNING: HR is {diff:.0f} bpm higher — possible fatigue/drift.")
    elif diff < -3:
        print(f"    GOOD: HR is {abs(diff):.0f} bpm lower — fitness improving.")
    else:
        print(f"    STABLE: HR difference is only {diff:+.0f} bpm.")
    print()


def recovery_correlation(runs, recovery):
    """Check if higher recovery scores correlate with faster paces."""
    print("=" * 60)
    print("  RECOVERY vs PERFORMANCE")
    print("=" * 60)

    if recovery is None or recovery.empty:
        print("  No recovery data available.\n")
        return

    df = runs.copy()
    df["pace_min"] = df["pace_per_mile"].apply(pace_to_minutes)
    df = df.dropna(subset=["pace_min"])

    # Merge on date
    merged = df.merge(recovery, on="date", how="inner")

    if len(merged) < 5:
        print("  Not enough overlapping data to analyze.\n")
        return

    # Split into high/low recovery days
    median_rec = merged["recovery_score"].median()
    high = merged[merged["recovery_score"] >= median_rec]
    low = merged[merged["recovery_score"] < median_rec]

    print(f"  Recovery median: {median_rec:.0f}%")
    print(f"  High recovery days ({len(high)} runs): avg pace {high['pace_min'].mean():.2f} min/mi")
    print(f"  Low recovery days ({len(low)} runs):  avg pace {low['pace_min'].mean():.2f} min/mi")

    diff = low["pace_min"].mean() - high["pace_min"].mean()
    if diff > 0.1:
        print(f"  You run {diff:.2f} min/mi FASTER on high recovery days.")
    else:
        print(f"  Recovery doesn't strongly predict pace for you (yet).")
    print()


def shoe_analysis(runs):
    """Average pace and HR by shoe model."""
    print("=" * 60)
    print("  SHOE BREAKDOWN")
    print("=" * 60)

    df = runs.copy()
    df["pace_min"] = df["pace_per_mile"].apply(pace_to_minutes)
    df = df[df["shoes"].notna() & (df["shoes"] != "")]

    if df.empty:
        print("  No shoe data recorded. Use the shoe arg in log_run.py.\n")
        return

    for shoe, group in df.groupby("shoes"):
        avg_pace = group["pace_min"].dropna().mean()
        avg_hr = group["avg_hr"].dropna().mean()
        count = len(group)
        pace_str = f"{int(avg_pace)}:{int((avg_pace % 1) * 60):02d}" if pd.notna(avg_pace) else "N/A"
        hr_str = f"{avg_hr:.0f}" if pd.notna(avg_hr) else "N/A"
        print(f"\n  {shoe}:")
        print(f"    Runs: {count}")
        print(f"    Avg pace: {pace_str}/mi")
        print(f"    Avg HR:   {hr_str} bpm")

    print()


def main():
    runs, recovery = load_data()
    if runs is None:
        return

    print(f"\n{'#' * 60}")
    print(f"  RUN INTEL — {len(runs)} runs loaded")
    print(f"{'#' * 60}")

    efficiency_analysis(runs)
    rolling_averages(runs)
    cardiac_drift(runs)
    recovery_correlation(runs, recovery)
    shoe_analysis(runs)


if __name__ == "__main__":
    main()
