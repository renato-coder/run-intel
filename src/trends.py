"""
Run Intel analysis engine.

Reads runs.csv and recovery.csv to produce running performance insights.

Sections:
  1. HEART RATE FITNESS TRENDS — monthly HR, resting HR, HRV, strain, zone shifts
  2. RECOVERY PATTERNS — monthly scores, day-of-week patterns, strain->recovery link
  3. CURRENT SNAPSHOT — last 7 vs last 30 days comparison
  4. PACE TRACKING — only manually logged runs (Whoop can't track treadmill pace)

Usage:
    python src/trends.py
"""

import pandas as pd
from pathlib import Path

DATA_DIR = Path(__file__).resolve().parent.parent / "data"

# ── Arrows for trend direction ────────────────────────────────────
UP = "^"
DOWN = "v"
FLAT = "="


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


def trend_arrow(diff, lower_is_better=True):
    """Return an arrow indicating trend direction and whether it's good."""
    if abs(diff) < 1:
        return FLAT, "steady"
    if lower_is_better:
        return (DOWN, "improving") if diff < 0 else (UP, "declining")
    else:
        return (UP, "improving") if diff > 0 else (DOWN, "declining")


def section_header(title):
    print(f"\n{'=' * 60}")
    print(f"  {title}")
    print("=" * 60)


# ═══════════════════════════════════════════════════════════════════
#  SECTION 1: HEART RATE FITNESS TRENDS
# ═══════════════════════════════════════════════════════════════════


def hr_during_runs(runs):
    """Monthly average HR during runs — trending down = fitter."""
    section_header("AVG HR DURING RUNS (monthly)")

    df = runs.dropna(subset=["avg_hr"]).copy()
    if len(df) < 2:
        print("  Not enough HR data.\n")
        return

    df["month"] = df["date"].dt.to_period("M")
    monthly = df.groupby("month")["avg_hr"].mean()

    recent = monthly.tail(6)
    for period, hr in recent.items():
        print(f"  {period}:  {hr:.0f} bpm")

    first_third = monthly.head(max(len(monthly) // 3, 1)).mean()
    last_third = monthly.tail(max(len(monthly) // 3, 1)).mean()
    diff = last_third - first_third
    arrow, status = trend_arrow(diff, lower_is_better=True)
    print(f"\n  {arrow} {diff:+.0f} bpm overall ({status})")
    print()


def resting_hr_trend(recovery):
    """Monthly resting HR — trending down = stronger heart."""
    section_header("RESTING HEART RATE (monthly)")

    if recovery is None or recovery.empty:
        print("  No recovery data.\n")
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

    first_third = monthly.head(max(len(monthly) // 3, 1)).mean()
    last_third = monthly.tail(max(len(monthly) // 3, 1)).mean()
    diff = last_third - first_third
    arrow, status = trend_arrow(diff, lower_is_better=True)
    print(f"\n  {arrow} {diff:+.0f} bpm overall ({status})")
    print()


def hrv_trend(recovery):
    """Monthly HRV — trending up = better recovery capacity."""
    section_header("HRV (monthly)")

    if recovery is None or recovery.empty:
        print("  No recovery data.\n")
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

    first_third = monthly.head(max(len(monthly) // 3, 1)).mean()
    last_third = monthly.tail(max(len(monthly) // 3, 1)).mean()
    diff = last_third - first_third
    arrow, status = trend_arrow(diff, lower_is_better=False)
    print(f"\n  {arrow} {diff:+.1f} ms overall ({status})")
    print()


def strain_per_run(runs):
    """Monthly average strain per run."""
    section_header("AVG STRAIN PER RUN (monthly)")

    df = runs.dropna(subset=["strain"]).copy()
    if len(df) < 2:
        print("  Not enough strain data.\n")
        return

    df["month"] = df["date"].dt.to_period("M")
    monthly = df.groupby("month")["strain"].mean()

    recent = monthly.tail(6)
    for period, strain in recent.items():
        print(f"  {period}:  {strain:.1f}")

    first_third = monthly.head(max(len(monthly) // 3, 1)).mean()
    last_third = monthly.tail(max(len(monthly) // 3, 1)).mean()
    diff = last_third - first_third
    print(f"\n  {diff:+.1f} strain overall")
    print()


def zone_shift(runs):
    """Are you spending more time in lower HR zones? (fitness signal)."""
    section_header("HR ZONE SHIFT OVER TIME")

    zone_cols = [
        "zone_zero_milli", "zone_one_milli", "zone_two_milli",
        "zone_three_milli", "zone_four_milli", "zone_five_milli",
    ]
    zone_labels = ["Zone 0", "Zone 1", "Zone 2", "Zone 3", "Zone 4", "Zone 5"]

    df = runs.dropna(subset=zone_cols, how="all").copy()
    if len(df) < 4:
        print("  Not enough zone data.\n")
        return

    for col in zone_cols:
        df[col] = pd.to_numeric(df[col], errors="coerce").fillna(0)

    # Overall distribution
    totals = df[zone_cols].sum()
    grand_total = totals.sum()
    if grand_total == 0:
        print("  No zone time recorded.\n")
        return

    print("\n  Overall distribution:")
    for label, col in zip(zone_labels, zone_cols):
        pct = totals[col] / grand_total * 100
        bar = "#" * int(pct / 2)
        print(f"    {label}: {pct:5.1f}%  {bar}")

    # Compare first half vs second half
    mid = len(df) // 2
    early_totals = df.iloc[:mid][zone_cols].sum()
    early_grand = early_totals.sum()
    recent_totals = df.iloc[mid:][zone_cols].sum()
    recent_grand = recent_totals.sum()

    if early_grand > 0 and recent_grand > 0:
        # Low zones = 0,1,2  High zones = 3,4,5
        early_low = sum(early_totals[c] for c in zone_cols[:3]) / early_grand * 100
        recent_low = sum(recent_totals[c] for c in zone_cols[:3]) / recent_grand * 100
        diff = recent_low - early_low

        print(f"\n  Time in low zones (0-2): {early_low:.0f}% -> {recent_low:.0f}%")
        if diff > 2:
            print(f"  {UP} More time in lower zones — sign of better fitness")
        elif diff < -2:
            print(f"  {DOWN} Less time in lower zones — training harder or less efficient")
        else:
            print(f"  {FLAT} Zone distribution is stable")

        # Show individual zone shifts
        print("\n  Changes by zone:")
        for label, col in zip(zone_labels, zone_cols):
            early_pct = early_totals[col] / early_grand * 100
            recent_pct = recent_totals[col] / recent_grand * 100
            d = recent_pct - early_pct
            if abs(d) >= 1:
                arrow = UP if d > 0 else DOWN
                print(f"    {label}: {early_pct:.0f}% -> {recent_pct:.0f}% ({arrow} {d:+.0f}%)")
    print()


# ═══════════════════════════════════════════════════════════════════
#  SECTION 2: RECOVERY PATTERNS
# ═══════════════════════════════════════════════════════════════════


def recovery_by_month(recovery):
    """Average recovery score by month."""
    section_header("RECOVERY SCORE (monthly)")

    if recovery is None or recovery.empty:
        print("  No recovery data.\n")
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

    # Red/yellow/green in last 30 days
    last_30 = df[df["date"] >= df["date"].max() - pd.Timedelta(days=30)]
    if not last_30.empty:
        red = len(last_30[last_30["recovery_score"] < 34])
        yellow = len(last_30[(last_30["recovery_score"] >= 34) & (last_30["recovery_score"] < 67)])
        green = len(last_30[last_30["recovery_score"] >= 67])
        print(f"\n  Last 30 days: {green} green / {yellow} yellow / {red} red")
    print()


def recovery_by_day_of_week(recovery):
    """Average recovery score by day of week."""
    section_header("RECOVERY BY DAY OF WEEK")

    if recovery is None or recovery.empty:
        print("  No recovery data.\n")
        return

    df = recovery.dropna(subset=["recovery_score"]).copy()
    if len(df) < 14:
        print("  Not enough data (need 2+ weeks).\n")
        return

    df["dow"] = df["date"].dt.day_name()
    day_order = ["Monday", "Tuesday", "Wednesday", "Thursday", "Friday", "Saturday", "Sunday"]
    by_day = df.groupby("dow")["recovery_score"].mean().reindex(day_order)

    best_day = by_day.idxmax()
    worst_day = by_day.idxmin()

    for day, score in by_day.items():
        marker = ""
        if day == best_day:
            marker = "  <-- best"
        elif day == worst_day:
            marker = "  <-- worst"
        print(f"  {day:10s}  {score:.0f}%{marker}")
    print()


def strain_recovery_link(runs, recovery):
    """Does a high strain day predict low recovery the next day?"""
    section_header("STRAIN -> NEXT-DAY RECOVERY")

    if recovery is None or recovery.empty:
        print("  No recovery data.\n")
        return

    strain_df = runs.dropna(subset=["strain"])[["date", "strain"]].copy()
    rec_df = recovery.dropna(subset=["recovery_score"])[["date", "recovery_score"]].copy()

    if strain_df.empty or rec_df.empty:
        print("  Not enough data.\n")
        return

    # Shift recovery back 1 day to align with previous day's strain
    rec_df["prev_date"] = rec_df["date"] - pd.Timedelta(days=1)
    merged = strain_df.merge(rec_df, left_on="date", right_on="prev_date", how="inner")

    if len(merged) < 10:
        print("  Not enough overlapping data.\n")
        return

    # Split strain into terciles
    low_thresh = merged["strain"].quantile(0.33)
    high_thresh = merged["strain"].quantile(0.67)

    low_strain = merged[merged["strain"] <= low_thresh]
    mid_strain = merged[(merged["strain"] > low_thresh) & (merged["strain"] <= high_thresh)]
    high_strain = merged[merged["strain"] > high_thresh]

    print(f"  Low strain days (< {low_thresh:.1f}):   next-day recovery {low_strain['recovery_score'].mean():.0f}%")
    print(f"  Mid strain days:                next-day recovery {mid_strain['recovery_score'].mean():.0f}%")
    print(f"  High strain days (> {high_thresh:.1f}):  next-day recovery {high_strain['recovery_score'].mean():.0f}%")

    diff = low_strain["recovery_score"].mean() - high_strain["recovery_score"].mean()
    if diff > 5:
        print(f"\n  High strain costs you ~{diff:.0f}% recovery the next day.")
    else:
        print(f"\n  Your recovery holds up well regardless of strain.")
    print()


# ═══════════════════════════════════════════════════════════════════
#  SECTION 3: CURRENT SNAPSHOT
# ═══════════════════════════════════════════════════════════════════


def current_snapshot(runs, recovery):
    """Last 7 days vs last 30 days comparison."""
    section_header("CURRENT SNAPSHOT")

    now = runs["date"].max()
    d7 = now - pd.Timedelta(days=7)
    d30 = now - pd.Timedelta(days=30)

    runs_7 = runs[runs["date"] >= d7]
    runs_30 = runs[runs["date"] >= d30]

    metrics = []

    # Avg HR from runs
    hr_7 = runs_7["avg_hr"].dropna().mean()
    hr_30 = runs_30["avg_hr"].dropna().mean()
    if pd.notna(hr_7) and pd.notna(hr_30):
        diff = hr_7 - hr_30
        arrow, status = trend_arrow(diff, lower_is_better=True)
        metrics.append(("Avg HR (runs)", f"{hr_7:.0f} bpm", f"{hr_30:.0f} bpm", f"{arrow} {diff:+.0f} ({status})"))

    # Avg strain from runs
    strain_7 = runs_7["strain"].dropna().mean()
    strain_30 = runs_30["strain"].dropna().mean()
    if pd.notna(strain_7) and pd.notna(strain_30):
        diff = strain_7 - strain_30
        metrics.append(("Avg strain", f"{strain_7:.1f}", f"{strain_30:.1f}", f"{diff:+.1f}"))

    # Recovery, HRV, resting HR from recovery.csv
    if recovery is not None and not recovery.empty:
        rec_7 = recovery[recovery["date"] >= d7]
        rec_30 = recovery[recovery["date"] >= d30]

        rec_score_7 = rec_7["recovery_score"].dropna().mean()
        rec_score_30 = rec_30["recovery_score"].dropna().mean()
        if pd.notna(rec_score_7) and pd.notna(rec_score_30):
            diff = rec_score_7 - rec_score_30
            arrow, status = trend_arrow(diff, lower_is_better=False)
            metrics.append(("Recovery", f"{rec_score_7:.0f}%", f"{rec_score_30:.0f}%", f"{arrow} {diff:+.0f}% ({status})"))

        hrv_7 = rec_7["hrv"].dropna().mean()
        hrv_30 = rec_30["hrv"].dropna().mean()
        if pd.notna(hrv_7) and pd.notna(hrv_30):
            diff = hrv_7 - hrv_30
            arrow, status = trend_arrow(diff, lower_is_better=False)
            metrics.append(("HRV", f"{hrv_7:.1f} ms", f"{hrv_30:.1f} ms", f"{arrow} {diff:+.1f} ({status})"))

        rhr_7 = rec_7["resting_hr"].dropna().mean()
        rhr_30 = rec_30["resting_hr"].dropna().mean()
        if pd.notna(rhr_7) and pd.notna(rhr_30):
            diff = rhr_7 - rhr_30
            arrow, status = trend_arrow(diff, lower_is_better=True)
            metrics.append(("Resting HR", f"{rhr_7:.0f} bpm", f"{rhr_30:.0f} bpm", f"{arrow} {diff:+.0f} ({status})"))

    if not metrics:
        print("  Not enough recent data.\n")
        return

    # Print table
    print(f"\n  {'Metric':<16} {'Last 7d':>10} {'Last 30d':>10}   {'vs 30d'}")
    print(f"  {'-' * 54}")
    for name, val7, val30, comp in metrics:
        print(f"  {name:<16} {val7:>10} {val30:>10}   {comp}")
    print()


# ═══════════════════════════════════════════════════════════════════
#  SECTION 4: PACE TRACKING (manually logged runs only)
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
    section_header("PACE vs HR EFFICIENCY")

    df = df.dropna(subset=["avg_hr"]).copy()
    if len(df) < 2:
        print("  Not enough data with HR.\n")
        return

    df["efficiency"] = df["avg_hr"] / df["pace_min"]

    n = len(df)
    third = max(n // 3, 1)
    early = df.head(third)["efficiency"].mean()
    recent = df.tail(third)["efficiency"].mean()
    change = ((recent - early) / early) * 100

    arrow, status = trend_arrow(change, lower_is_better=True)
    print(f"  Early efficiency ratio:  {early:.1f} (HR/pace)")
    print(f"  Recent efficiency ratio: {recent:.1f} (HR/pace)")
    print(f"  {arrow} {change:+.1f}% ({status})")
    print(f"  (Lower = fitter: same pace at lower HR)\n")


def cardiac_drift(df):
    """Detect cardiac drift: is HR trending up at a similar pace?"""
    section_header("CARDIAC DRIFT DETECTION")

    df = df.dropna(subset=["avg_hr"]).copy()
    if len(df) < 5:
        print("  Not enough data yet.\n")
        return

    median_pace = df["pace_min"].median()
    similar = df[(df["pace_min"] >= median_pace - 0.25) & (df["pace_min"] <= median_pace + 0.25)]

    if len(similar) < 4:
        print(f"  Not enough runs near typical pace ({fmt_pace(median_pace)}/mi).\n")
        return

    mid = len(similar) // 2
    early_hr = similar.iloc[:mid]["avg_hr"].mean()
    recent_hr = similar.iloc[mid:]["avg_hr"].mean()
    diff = recent_hr - early_hr

    print(f"  Typical pace: {fmt_pace(median_pace)}/mi")
    print(f"  Early avg HR:  {early_hr:.0f} bpm")
    print(f"  Recent avg HR: {recent_hr:.0f} bpm")

    if diff > 3:
        print(f"  {UP} HR is {diff:.0f} bpm higher — possible fatigue/overtraining")
    elif diff < -3:
        print(f"  {DOWN} HR is {abs(diff):.0f} bpm lower — fitness improving")
    else:
        print(f"  {FLAT} HR is stable ({diff:+.0f} bpm)")
    print()


def shoe_analysis(df):
    """Average pace and HR by shoe model."""
    section_header("SHOE BREAKDOWN")

    df = df[df["shoes"].notna() & (df["shoes"] != "")]

    if df.empty:
        print("  No shoe data yet.\n")
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

    # ── 1. Heart Rate Fitness Trends ──────────────────────────────
    print(f"\n{'─' * 60}")
    print(f"  1. HEART RATE FITNESS TRENDS")
    print(f"{'─' * 60}")

    hr_during_runs(runs)
    resting_hr_trend(recovery)
    hrv_trend(recovery)
    strain_per_run(runs)
    zone_shift(runs)

    # ── 2. Recovery Patterns ──────────────────────────────────────
    print(f"{'─' * 60}")
    print(f"  2. RECOVERY PATTERNS")
    print(f"{'─' * 60}")

    recovery_by_month(recovery)
    recovery_by_day_of_week(recovery)
    strain_recovery_link(runs, recovery)

    # ── 3. Current Snapshot ───────────────────────────────────────
    print(f"{'─' * 60}")
    print(f"  3. CURRENT SNAPSHOT")
    print(f"{'─' * 60}")

    current_snapshot(runs, recovery)

    # ── 4. Pace Tracking ──────────────────────────────────────────
    print(f"{'─' * 60}")
    print(f"  4. PACE TRACKING")
    print(f"{'─' * 60}")

    pace_runs = get_pace_runs(runs)

    if len(pace_runs) == 0:
        print("\n  No pace data yet. Start logging:")
        print("  python3 src/log_run.py [miles] [minutes] [shoe]\n")
    else:
        print(f"\n  {len(pace_runs)} manually logged runs\n")
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
