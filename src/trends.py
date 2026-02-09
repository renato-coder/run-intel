"""
Run Intel analysis engine.

Reads runs.csv and recovery.csv to produce running performance insights.

Two sections:
  1. HISTORICAL ANALYSIS — all Whoop data (HR, strain, recovery, HRV, zones)
  2. PACE ANALYSIS — only manually logged runs with valid pace data

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


def fmt_pace(minutes):
    """Format float minutes (7.817) as M:SS string (7:49)."""
    if pd.isna(minutes) or minutes <= 0:
        return "N/A"
    m = int(minutes)
    s = int((minutes - m) * 60)
    return f"{m}:{s:02d}"


def pace_to_minutes(pace_str):
    """Convert pace string like '7:49' to float minutes (7.817)."""
    if pd.isna(pace_str) or not isinstance(pace_str, str) or ":" not in pace_str:
        return None
    parts = pace_str.split(":")
    return int(parts[0]) + int(parts[1]) / 60


# ═══════════════════════════════════════════════════════════════════
#  SECTION 1: HISTORICAL ANALYSIS (all Whoop data)
# ═══════════════════════════════════════════════════════════════════


def avg_hr_trend(runs):
    """Monthly average heart rate trend across all runs."""
    print("\n" + "=" * 60)
    print("  AVG HEART RATE TREND (monthly)")
    print("=" * 60)

    df = runs.dropna(subset=["avg_hr"]).copy()
    if len(df) < 2:
        print("  Not enough HR data.\n")
        return

    df["month"] = df["date"].dt.to_period("M")
    monthly = df.groupby("month")["avg_hr"].mean()

    # Show last 6 months
    recent = monthly.tail(6)
    for period, hr in recent.items():
        print(f"  {period}:  {hr:.0f} bpm")

    # Overall trend
    first_q = monthly.head(len(monthly) // 3).mean()
    last_q = monthly.tail(len(monthly) // 3).mean()
    diff = last_q - first_q
    direction = "DOWN" if diff < 0 else "UP"
    print(f"\n  Trend: {diff:+.0f} bpm ({direction}) from early to recent")
    if diff < -2:
        print("  Lower avg HR at same effort = improving fitness")
    print()


def resting_hr_trend(recovery):
    """Monthly resting heart rate trend from recovery data."""
    print("=" * 60)
    print("  RESTING HEART RATE TREND (monthly)")
    print("=" * 60)

    if recovery is None or recovery.empty:
        print("  No recovery data available.\n")
        return

    df = recovery.dropna(subset=["resting_hr"]).copy()
    if len(df) < 2:
        print("  Not enough data.\n")
        return

    df["month"] = df["date"].dt.to_period("M")
    monthly = df.groupby("month")["resting_hr"].mean()

    recent = monthly.tail(6)
    for period, hr in recent.items():
        print(f"  {period}:  {hr:.0f} bpm")

    first_q = monthly.head(len(monthly) // 3).mean()
    last_q = monthly.tail(len(monthly) // 3).mean()
    diff = last_q - first_q
    print(f"\n  Trend: {diff:+.0f} bpm from early to recent")
    if diff < -2:
        print("  Dropping resting HR = stronger cardiovascular system")
    print()


def hrv_trend(recovery):
    """Monthly HRV trend from recovery data."""
    print("=" * 60)
    print("  HRV TREND (monthly)")
    print("=" * 60)

    if recovery is None or recovery.empty:
        print("  No recovery data available.\n")
        return

    df = recovery.dropna(subset=["hrv"]).copy()
    if len(df) < 2:
        print("  Not enough data.\n")
        return

    df["month"] = df["date"].dt.to_period("M")
    monthly = df.groupby("month")["hrv"].mean()

    recent = monthly.tail(6)
    for period, hrv in recent.items():
        print(f"  {period}:  {hrv:.1f} ms")

    first_q = monthly.head(len(monthly) // 3).mean()
    last_q = monthly.tail(len(monthly) // 3).mean()
    diff = last_q - first_q
    print(f"\n  Trend: {diff:+.1f} ms from early to recent")
    if diff > 2:
        print("  Rising HRV = better recovery capacity")
    print()


def strain_load(runs):
    """7-day and 30-day rolling average strain."""
    print("=" * 60)
    print("  STRAIN LOAD")
    print("=" * 60)

    df = runs.dropna(subset=["strain"]).set_index("date").copy()
    if len(df) < 7:
        print("  Not enough strain data.\n")
        return

    avg_7 = df["strain"].rolling("7D").mean().iloc[-1]
    avg_30 = df["strain"].rolling("30D").mean().iloc[-1]

    print(f"  7-day avg strain:  {avg_7:.1f}")
    print(f"  30-day avg strain: {avg_30:.1f}")

    if avg_7 > avg_30 * 1.2:
        print("  Recent load is HIGH relative to your baseline.")
    elif avg_7 < avg_30 * 0.8:
        print("  Recent load is LOW — good recovery window or time to push.")
    else:
        print("  Load is steady.")
    print()


def recovery_trends(recovery):
    """Recovery score trend over time."""
    print("=" * 60)
    print("  RECOVERY SCORE TRENDS")
    print("=" * 60)

    if recovery is None or recovery.empty:
        print("  No recovery data available.\n")
        return

    df = recovery.dropna(subset=["recovery_score"]).copy()
    if len(df) < 2:
        print("  Not enough data.\n")
        return

    df["month"] = df["date"].dt.to_period("M")
    monthly = df.groupby("month")["recovery_score"].mean()

    recent = monthly.tail(6)
    for period, score in recent.items():
        print(f"  {period}:  {score:.0f}%")

    # Count red/yellow/green days in last 30
    last_30 = df[df["date"] >= df["date"].max() - pd.Timedelta(days=30)]
    if not last_30.empty:
        red = len(last_30[last_30["recovery_score"] < 34])
        yellow = len(last_30[(last_30["recovery_score"] >= 34) & (last_30["recovery_score"] < 67)])
        green = len(last_30[last_30["recovery_score"] >= 67])
        print(f"\n  Last 30 days: {green} green, {yellow} yellow, {red} red")
    print()


def zone_distribution(runs):
    """HR zone time distribution and how it's changed."""
    print("=" * 60)
    print("  HR ZONE DISTRIBUTION")
    print("=" * 60)

    zone_cols = [
        "zone_zero_milli", "zone_one_milli", "zone_two_milli",
        "zone_three_milli", "zone_four_milli", "zone_five_milli",
    ]
    zone_labels = ["Zone 0", "Zone 1", "Zone 2", "Zone 3", "Zone 4", "Zone 5"]

    df = runs.dropna(subset=zone_cols, how="all").copy()
    if len(df) < 2:
        print("  Not enough zone data.\n")
        return

    # Fill NaN zones with 0 for summing
    for col in zone_cols:
        df[col] = pd.to_numeric(df[col], errors="coerce").fillna(0)

    # Overall distribution
    totals = df[zone_cols].sum()
    grand_total = totals.sum()
    if grand_total == 0:
        print("  No zone time recorded.\n")
        return

    print("\n  Overall:")
    for label, col in zip(zone_labels, zone_cols):
        pct = totals[col] / grand_total * 100
        bar = "#" * int(pct / 2)
        print(f"    {label}: {pct:5.1f}%  {bar}")

    # Compare first half vs second half
    mid = len(df) // 2
    if mid > 0:
        early_totals = df.iloc[:mid][zone_cols].sum()
        early_grand = early_totals.sum()
        recent_totals = df.iloc[mid:][zone_cols].sum()
        recent_grand = recent_totals.sum()

        if early_grand > 0 and recent_grand > 0:
            print("\n  Shift over time (early -> recent):")
            for label, col in zip(zone_labels, zone_cols):
                early_pct = early_totals[col] / early_grand * 100
                recent_pct = recent_totals[col] / recent_grand * 100
                diff = recent_pct - early_pct
                if abs(diff) >= 1:
                    arrow = "+" if diff > 0 else ""
                    print(f"    {label}: {early_pct:.0f}% -> {recent_pct:.0f}% ({arrow}{diff:.0f}%)")
    print()


# ═══════════════════════════════════════════════════════════════════
#  SECTION 2: PACE ANALYSIS (manually logged runs only)
# ═══════════════════════════════════════════════════════════════════


def get_pace_runs(runs):
    """Filter to only runs with valid manually-logged pace (> 0 and < 15 min/mi)."""
    df = runs.copy()
    df["pace_min"] = df["pace_per_mile"].apply(pace_to_minutes)
    df = df.dropna(subset=["pace_min"])
    df = df[(df["pace_min"] > 0) & (df["pace_min"] < 15)]
    return df


def efficiency_analysis(df):
    """Pace vs HR efficiency: lower HR at the same pace = better fitness."""
    print("=" * 60)
    print("  EFFICIENCY: Pace vs Heart Rate")
    print("=" * 60)

    df = df.dropna(subset=["avg_hr"]).copy()
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


def cardiac_drift(df):
    """Detect cardiac drift: is HR trending up at a similar pace?"""
    print("=" * 60)
    print("  CARDIAC DRIFT DETECTION")
    print("=" * 60)

    df = df.dropna(subset=["avg_hr"]).copy()
    if len(df) < 5:
        print("  Not enough data to detect cardiac drift.\n")
        return

    # Bin runs by similar pace (within 0.5 min/mi) and see if HR is rising
    median_pace = df["pace_min"].median()
    similar = df[(df["pace_min"] >= median_pace - 0.25) & (df["pace_min"] <= median_pace + 0.25)]

    if len(similar) < 4:
        print(f"  Not enough runs near your typical pace ({fmt_pace(median_pace)}/mi).\n")
        return

    # Split into early and recent halves
    mid = len(similar) // 2
    early_hr = similar.iloc[:mid]["avg_hr"].mean()
    recent_hr = similar.iloc[mid:]["avg_hr"].mean()
    diff = recent_hr - early_hr

    pace_lo = fmt_pace(median_pace - 0.25)
    pace_hi = fmt_pace(median_pace + 0.25)
    print(f"  At similar pace ({pace_lo}-{pace_hi}/mi):")
    print(f"    Early avg HR:  {early_hr:.0f} bpm")
    print(f"    Recent avg HR: {recent_hr:.0f} bpm")

    if diff > 3:
        print(f"    WARNING: HR is {diff:.0f} bpm higher — possible fatigue/drift.")
    elif diff < -3:
        print(f"    GOOD: HR is {abs(diff):.0f} bpm lower — fitness improving.")
    else:
        print(f"    STABLE: HR difference is only {diff:+.0f} bpm.")
    print()


def shoe_analysis(df):
    """Average pace and HR by shoe model."""
    print("=" * 60)
    print("  SHOE BREAKDOWN")
    print("=" * 60)

    df = df[df["shoes"].notna() & (df["shoes"] != "")]

    if df.empty:
        print("  No shoe data recorded. Use the shoe arg in log_run.py.\n")
        return

    for shoe, group in df.groupby("shoes"):
        avg_pace = group["pace_min"].dropna().mean()
        avg_hr = group["avg_hr"].dropna().mean()
        count = len(group)
        hr_str = f"{avg_hr:.0f}" if pd.notna(avg_hr) else "N/A"
        print(f"\n  {shoe}:")
        print(f"    Runs: {count}")
        print(f"    Avg pace: {fmt_pace(avg_pace)}/mi")
        print(f"    Avg HR:   {hr_str} bpm")

    print()


# ═══════════════════════════════════════════════════════════════════


def main():
    runs, recovery = load_data()
    if runs is None:
        return

    print(f"\n{'#' * 60}")
    print(f"  RUN INTEL — {len(runs)} runs loaded")
    print(f"{'#' * 60}")

    # ── Section 1: Historical analysis (all Whoop data) ───────────
    print(f"\n{'─' * 60}")
    print(f"  SECTION 1: HISTORICAL ANALYSIS ({len(runs)} runs)")
    print(f"{'─' * 60}")

    avg_hr_trend(runs)
    resting_hr_trend(recovery)
    hrv_trend(recovery)
    strain_load(runs)
    recovery_trends(recovery)
    zone_distribution(runs)

    # ── Section 2: Pace analysis (manually logged runs only) ──────
    pace_runs = get_pace_runs(runs)

    if len(pace_runs) == 0:
        print(f"{'─' * 60}")
        print(f"  SECTION 2: PACE ANALYSIS")
        print(f"{'─' * 60}")
        print("\n  No manually logged runs with pace data yet.")
        print("  Pace analysis will appear here once you log runs.\n")
    else:
        print(f"{'─' * 60}")
        print(f"  SECTION 2: PACE ANALYSIS ({len(pace_runs)} logged runs)")
        print(f"{'─' * 60}")

        efficiency_analysis(pace_runs)
        cardiac_drift(pace_runs)
        shoe_analysis(pace_runs)

    # ── Footer ────────────────────────────────────────────────────
    print("─" * 60)
    print("  Log runs with: python3 src/log_run.py [miles] [minutes] [shoe]")
    print("─" * 60)
    print()


if __name__ == "__main__":
    main()
