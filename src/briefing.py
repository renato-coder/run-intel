"""
Morning Briefing engine for Run Intel.

Analyzes recovery, HRV, RHR, and strain data to produce a daily
status assessment with evidence-based explanations and action items.

References:
  - Plews et al., Sports Med 2013 (HRV trends in endurance athletes)
  - Buchheit 2014 (HRV monitoring in team sports)
  - Flatt & Esco 2015 (HRV CV as readiness marker)
"""

import statistics
from datetime import date, timedelta


def generate_briefing(today_recovery, recovery_history, run_history):
    """
    Generate the morning briefing.

    Args:
        today_recovery: dict with recovery_score, hrv, resting_hr (or Nones)
        recovery_history: list of dicts with date, recovery_score, hrv, resting_hr
                          (last 30 days, sorted by date ascending)
        run_history: list of dicts with date, strain (last 30 days, sorted by date asc)

    Returns:
        dict with status, status_label, color, why (list), actions (list), metrics (dict)
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

    # HRV metrics
    hrv_7d = hrv_values[-7:] if len(hrv_values) >= 7 else hrv_values
    hrv_30d = hrv_values

    hrv_7d_avg = statistics.mean(hrv_7d) if hrv_7d else None
    hrv_30d_baseline = statistics.mean(hrv_30d) if hrv_30d else None
    hrv_7d_cv = None
    if len(hrv_7d) >= 3 and hrv_7d_avg and hrv_7d_avg > 0:
        hrv_7d_cv = (statistics.stdev(hrv_7d) / hrv_7d_avg) * 100

    # HRV consecutive drop detection
    hrv_dropping = False
    if len(hrv_values) >= 3:
        last3 = hrv_values[-3:]
        hrv_dropping = last3[0] > last3[1] > last3[2]

    # RHR metrics
    rhr_7d = rhr_values[-7:] if len(rhr_values) >= 7 else rhr_values
    rhr_30d = rhr_values
    rhr_7d_avg = statistics.mean(rhr_7d) if rhr_7d else None
    rhr_30d_baseline = statistics.mean(rhr_30d) if rhr_30d else None
    rhr_elevated = False
    rhr_diff = None
    if rhr_today is not None and rhr_30d_baseline is not None:
        rhr_diff = rhr_today - rhr_30d_baseline
        rhr_elevated = rhr_diff >= 3

    # Recovery trend: last 3 days vs 7-day avg
    rec_last3 = rec_values[-3:] if len(rec_values) >= 3 else rec_values
    rec_7d = rec_values[-7:] if len(rec_values) >= 7 else rec_values
    rec_3d_avg = statistics.mean(rec_last3) if rec_last3 else None
    rec_7d_avg = statistics.mean(rec_7d) if rec_7d else None
    rec_trending_down = False
    if rec_3d_avg is not None and rec_7d_avg is not None:
        rec_trending_down = rec_3d_avg < rec_7d_avg - 5

    # Strain load: last 3 days vs typical 3-day from 30d data
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
        status_label = "You're primed. Push it today."
        color = "#00F19F"
    elif score is not None and score >= 50 and not rhr_elevated and not hrv_well_below:
        status = "solid"
        status_label = "Solid foundation. Normal training."
        color = "#FFD600"
    elif score is not None and score < 34 and (hrv_well_below or (rhr_elevated and cv_high)):
        status = "recovery"
        status_label = "Recovery mode. Protect your streak."
        color = "#FF4D4D"
    elif score is not None and score < 50:
        status = "cautious"
        status_label = "Your body is working hard. Go easy today."
        color = "#FF8C00"
    elif hrv_below or rhr_elevated or cv_high:
        status = "cautious"
        status_label = "Your body is working hard. Go easy today."
        color = "#FF8C00"
    else:
        status = "solid"
        status_label = "Solid foundation. Normal training."
        color = "#FFD600"

    # ── Generate WHY bullets ─────────────────────────────────────────

    why = []

    # HRV consecutive drop
    if hrv_dropping and len(hrv_values) >= 3:
        last3 = hrv_values[-3:]
        why.append(
            f"Your HRV has dropped 3 days straight ({last3[0]:.0f} → {last3[1]:.0f} → {last3[2]:.0f} ms). "
            "Consecutive HRV drops often precede illness or injury in endurance athletes "
            "(Plews et al., Sports Med 2013)."
        )

    # HRV vs baseline
    if hrv_today is not None and hrv_30d_baseline is not None:
        diff = hrv_today - hrv_30d_baseline
        if abs(diff) > 3:
            direction = "above" if diff > 0 else "below"
            why.append(
                f"HRV is {hrv_today:.0f} ms, {abs(diff):.0f} {direction} your "
                f"{hrv_30d_baseline:.0f} ms baseline. "
                + ("Elevated HRV signals strong parasympathetic tone and readiness (Buchheit 2014)."
                   if diff > 0 else
                   "Suppressed HRV indicates your autonomic nervous system hasn't fully recovered.")
            )

    # HRV CV
    if hrv_7d_cv is not None:
        normal_cv = 10  # rough normal for consistent athletes
        if hrv_7d_cv > 15:
            why.append(
                f"Your HRV coefficient of variation is {hrv_7d_cv:.0f}% this week. "
                "High day-to-day HRV swings indicate your nervous system is struggling "
                "to stabilize (Flatt & Esco 2015)."
            )
        elif hrv_7d_cv <= 8 and status == "primed":
            why.append(
                f"HRV CV is only {hrv_7d_cv:.0f}% this week — very stable. "
                "Low variability between days reflects a well-regulated autonomic system."
            )

    # RHR
    if rhr_today is not None and rhr_30d_baseline is not None and rhr_diff is not None:
        if abs(rhr_diff) >= 2:
            why.append(
                f"RHR is {rhr_today:.0f} bpm, {abs(rhr_diff):.0f} "
                f"{'above' if rhr_diff > 0 else 'below'} your "
                f"{rhr_30d_baseline:.0f} bpm baseline. "
                + ("Elevated resting HR signals incomplete autonomic recovery."
                   if rhr_diff > 0 else
                   "Lower RHR suggests strong cardiovascular recovery.")
            )

    # Recovery trend
    if rec_3d_avg is not None and rec_7d_avg is not None and rec_trending_down:
        why.append(
            f"Recovery has averaged {rec_3d_avg:.0f}% over the last 3 days "
            f"vs your 7-day average of {rec_7d_avg:.0f}%"
            + (f" with cumulative strain of {strain_3d:.0f}. "
               "Your body needs a lighter load."
               if strain_3d else ". Your body is accumulating fatigue.")
        )

    # Strain load
    if strain_high and strain_typical_3d is not None:
        why.append(
            f"3-day strain load is {strain_3d:.0f} vs your typical {strain_typical_3d:.0f}. "
            "Accumulated strain without adequate recovery increases overtraining risk."
        )

    # Elevation note — always relevant
    if not why or len(why) < 3:
        why.append(
            "At 4,500ft elevation in Lehi, your heart works 3-5% harder than sea level. "
            "Factor this into pace targets, especially on harder efforts."
        )

    # Respiratory context if recovery is low
    if score is not None and score < 50 and len(why) < 3:
        why.append(
            "With respiratory inflammation (prednisone/albuterol), your body is "
            "diverting recovery resources. Expect lower HRV and higher RHR until "
            "the inflammation resolves."
        )

    why = why[:3]

    # ── Generate ACTIONS ─────────────────────────────────────────────

    actions = []

    if status == "primed":
        actions.append("Good day for a tempo effort. Try 3 miles at 8:00/mi.")
        actions.append("Add 10 minutes of zone 2 warmup before picking up pace.")
        actions.append("Hydrate 20oz before your run — dry winter air at elevation increases dehydration.")
    elif status == "solid":
        actions.append("Stick to your normal easy pace (9:00-9:30/mi). Solid day to build mileage.")
        if strain_high:
            actions.append("Strain has been high — keep today under 5 miles.")
        else:
            actions.append("You can push distance slightly if you feel good after the first mile.")
        actions.append("Hydrate 20oz before your run — dry winter air at elevation increases dehydration.")
    elif status == "cautious":
        actions.append("Keep today's run under 5 miles at conversational pace (9:30+/mi).")
        if hrv_dropping:
            actions.append("If you feel off in the first mile, cut it short. Listen to your body.")
        else:
            actions.append("Focus on nasal breathing — it naturally limits intensity.")
        actions.append("Add 5-10 min of easy stretching or foam rolling after your run.")
    elif status == "recovery":
        actions.append(
            "Consider taking today off or cross-training. "
            "Your 700+ day streak won't suffer from one easy day."
        )
        actions.append("If you must run, keep it under 3 miles at 10:00+/mi — a jog, not a run.")
        actions.append("Prioritize sleep tonight. 8+ hours will do more for fitness than any workout.")

    actions = actions[:3]

    # ── Build metrics dict ───────────────────────────────────────────

    metrics = {
        "recovery_score": round(score, 1) if score is not None else None,
        "hrv_today": round(hrv_today, 1) if hrv_today is not None else None,
        "rhr_today": round(rhr_today) if rhr_today is not None else None,
        "hrv_7d_avg": round(hrv_7d_avg, 1) if hrv_7d_avg is not None else None,
        "hrv_7d_cv": round(hrv_7d_cv, 1) if hrv_7d_cv is not None else None,
        "hrv_30d_baseline": round(hrv_30d_baseline, 1) if hrv_30d_baseline is not None else None,
        "rhr_7d_avg": round(rhr_7d_avg, 1) if rhr_7d_avg is not None else None,
        "rhr_30d_baseline": round(rhr_30d_baseline, 1) if rhr_30d_baseline is not None else None,
        "rec_3d_avg": round(rec_3d_avg, 1) if rec_3d_avg is not None else None,
        "strain_3d": round(strain_3d, 1) if strain_3d else None,
        "strain_typical_3d": round(strain_typical_3d, 1) if strain_typical_3d is not None else None,
    }

    return {
        "status": status,
        "status_label": status_label,
        "color": color,
        "why": why,
        "actions": actions,
        "metrics": metrics,
    }
