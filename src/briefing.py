"""
Morning Briefing engine for Run Intel.

Analyzes recovery, HRV, RHR, and strain data to produce a daily
status with one plain-English explanation and one clear action.
"""

import statistics
from datetime import date, timedelta


def generate_briefing(today_recovery, recovery_history, run_history):
    """
    Generate the morning briefing.

    Returns:
        dict with status, headline, emoji, color, summary, play, metrics
        or None if insufficient data
    """
    score = today_recovery.get("recovery_score")
    hrv_today = today_recovery.get("hrv")
    rhr_today = today_recovery.get("resting_hr")

    if score is None and hrv_today is None:
        return None

    # ── Compute derived metrics ──────────────────────────────────────

    hrv_values = [r["hrv"] for r in recovery_history if r.get("hrv") is not None]
    rhr_values = [r["resting_hr"] for r in recovery_history if r.get("resting_hr") is not None]
    rec_values = [r["recovery_score"] for r in recovery_history if r.get("recovery_score") is not None]

    hrv_7d = hrv_values[-7:] if len(hrv_values) >= 7 else hrv_values
    hrv_30d = hrv_values

    hrv_7d_avg = statistics.mean(hrv_7d) if hrv_7d else None
    hrv_30d_baseline = statistics.mean(hrv_30d) if hrv_30d else None
    hrv_7d_cv = None
    if len(hrv_7d) >= 3 and hrv_7d_avg and hrv_7d_avg > 0:
        hrv_7d_cv = (statistics.stdev(hrv_7d) / hrv_7d_avg) * 100

    hrv_dropping = False
    if len(hrv_values) >= 3:
        last3 = hrv_values[-3:]
        hrv_dropping = last3[0] > last3[1] > last3[2]

    rhr_7d = rhr_values[-7:] if len(rhr_values) >= 7 else rhr_values
    rhr_30d = rhr_values
    rhr_7d_avg = statistics.mean(rhr_7d) if rhr_7d else None
    rhr_30d_baseline = statistics.mean(rhr_30d) if rhr_30d else None
    rhr_elevated = False
    rhr_diff = None
    if rhr_today is not None and rhr_30d_baseline is not None:
        rhr_diff = rhr_today - rhr_30d_baseline
        rhr_elevated = rhr_diff >= 3

    rec_last3 = rec_values[-3:] if len(rec_values) >= 3 else rec_values
    rec_7d = rec_values[-7:] if len(rec_values) >= 7 else rec_values
    rec_3d_avg = statistics.mean(rec_last3) if rec_last3 else None
    rec_7d_avg = statistics.mean(rec_7d) if rec_7d else None

    strain_values = [r["strain"] for r in run_history if r.get("strain") is not None]
    strain_3d = sum(strain_values[-3:]) if len(strain_values) >= 3 else sum(strain_values)
    strain_30d_total = sum(strain_values) if strain_values else 0
    strain_days = len(strain_values)
    strain_typical_3d = (strain_30d_total / strain_days * 3) if strain_days > 0 else None
    strain_high = False
    if strain_typical_3d is not None and strain_typical_3d > 0:
        strain_high = strain_3d > strain_typical_3d * 1.25

    # ── Determine status ─────────────────────────────────────────────

    hrv_above = hrv_today is not None and hrv_30d_baseline is not None and hrv_today >= hrv_30d_baseline
    hrv_below = hrv_today is not None and hrv_30d_baseline is not None and hrv_today < hrv_30d_baseline - 5
    hrv_well_below = hrv_today is not None and hrv_30d_baseline is not None and hrv_today < hrv_30d_baseline - 10
    cv_high = hrv_7d_cv is not None and hrv_7d_cv > 15
    cv_low = hrv_7d_cv is not None and hrv_7d_cv <= 10

    if score is not None and score >= 67 and hrv_above and not rhr_elevated and cv_low:
        status = "primed"
        headline = "Push it today."
        emoji = "\U0001f7e2"  # green circle
        color = "#00F19F"
    elif score is not None and score >= 50 and not rhr_elevated and not hrv_well_below:
        status = "solid"
        headline = "Normal training."
        emoji = "\U0001f7e2"
        color = "#00F19F"
    elif score is not None and score < 34 and (hrv_well_below or (rhr_elevated and cv_high)):
        status = "recovery"
        headline = "Recovery mode."
        emoji = "\U0001f534"  # red circle
        color = "#FF4D4D"
    elif score is not None and score < 50:
        status = "cautious"
        headline = "Go easy today."
        emoji = "\U0001f7e1"  # yellow circle
        color = "#FF8C00"
    elif hrv_below or rhr_elevated or cv_high:
        status = "cautious"
        headline = "Go easy today."
        emoji = "\U0001f7e1"
        color = "#FF8C00"
    else:
        status = "solid"
        headline = "Normal training."
        emoji = "\U0001f7e2"
        color = "#00F19F"

    # ── Generate single summary sentence ─────────────────────────────

    parts = []

    if hrv_today is not None and hrv_30d_baseline is not None:
        hrv_diff = hrv_today - hrv_30d_baseline
        if abs(hrv_diff) > 3:
            parts.append(
                f"your HRV is {abs(hrv_diff):.0f}ms {'above' if hrv_diff > 0 else 'below'} your baseline"
            )

    if rhr_elevated and rhr_diff is not None:
        parts.append(f"resting heart rate is {rhr_diff:.0f} above your {rhr_30d_baseline:.0f} baseline")
    elif rhr_today is not None and rhr_30d_baseline is not None and rhr_diff is not None and rhr_diff <= -2:
        parts.append(f"resting heart rate is low at {rhr_today:.0f}")

    if cv_high and hrv_7d_cv is not None:
        parts.append(f"HRV has been swinging day-to-day (CV {hrv_7d_cv:.0f}%)")

    if hrv_dropping:
        parts.append("HRV has dropped 3 days straight")

    if strain_high and strain_typical_3d is not None:
        parts.append(f"strain load is elevated ({strain_3d:.0f} vs typical {strain_typical_3d:.0f})")

    if status == "primed":
        if parts:
            summary = parts[0].capitalize() + ((" and " + parts[1]) if len(parts) > 1 else "") + " — your body is ready to work."
        else:
            summary = "All systems look good — your body is ready to work."
    elif status == "recovery":
        if parts:
            summary = parts[0].capitalize() + ((" and " + parts[1]) if len(parts) > 1 else "") + " — your body needs rest, not more miles."
        else:
            summary = f"Recovery at {score:.0f}% — your body needs rest, not more miles."
    else:
        if parts:
            summary = parts[0].capitalize() + ((" and " + parts[1]) if len(parts) > 1 else "") + " — your body is still recovering."
        else:
            summary = "Your numbers are slightly off baseline — take it easy and let your body catch up."

    # ── Generate single action (today's play) ────────────────────────

    if status == "primed":
        play = "Good day for a tempo effort — try 3 miles at 8:00/mi after a zone 2 warmup."
    elif status == "solid":
        if strain_high:
            play = "Easy 4-5 miles at 9:00-9:30 pace. Strain has been high, so don't push distance."
        else:
            play = "Solid day to build. Run your normal 5-6 miles at easy pace (9:00-9:30/mi)."
    elif status == "cautious":
        if hrv_dropping:
            play = "Run 3-4 miles at 9:30+ pace. If you feel off in the first mile, cut it short."
        else:
            play = "Run 4-5 miles, keep it at 9:30 pace or slower."
    elif status == "recovery":
        play = "Take today off or jog 2-3 easy miles at 10:00+ pace. Sleep 8 hours tonight."

    # ── Metrics ──────────────────────────────────────────────────────

    metrics = {
        "recovery_score": round(score) if score is not None else None,
        "hrv_today": round(hrv_today, 1) if hrv_today is not None else None,
        "rhr_today": round(rhr_today) if rhr_today is not None else None,
        "hrv_7d_cv": round(hrv_7d_cv) if hrv_7d_cv is not None else None,
    }

    return {
        "status": status,
        "headline": headline,
        "emoji": emoji,
        "color": color,
        "summary": summary,
        "play": play,
        "metrics": metrics,
    }
