---
title: "feat: Smart nutrition deficit calculator and human-readable dashboard"
type: feat
status: active
date: 2026-03-08
---

# Smart Nutrition Deficit Calculator + Dashboard UX Overhaul

## Overview

The app's nutrition system uses a naive `weight * 13` calorie formula that has no relationship to the user's actual metabolism. The dashboard shows jargon (VDOT, EF) that means nothing to a normal person. The longevity tab silently hides biological age when sex isn't set. A previously-logged run still shows the wrong date (03/09 instead of 03/08).

This plan replaces the nutrition engine with RMR-based deficit math, makes the dashboard speak plain English, and fixes the remaining UX gaps.

## Problem Statement

1. **Nutrition targets are meaningless.** "2548 cal / 176g protein" is computed from `weight * 13` — a number pulled from thin air. The user wants to lose 11 lbs (196 → 185). They need to know: what's my RMR? What should I actually eat? Am I on track today? The current system can't answer any of this.

2. **Dashboard speaks in code.** "VDOT: 49 → Target: 55.8 | EF: improving (+19.2%)" — the user literally said "I have no idea what that means." This should say something like "You're running a ~3:20 marathon. To hit sub-3:00, you need to get ~12% faster. Your efficiency improved 19% this month."

3. **Biological age is invisible.** The computation exists, the rendering exists, but the user's sex isn't set so the API returns null and nothing shows. No prompt tells them what's missing.

4. **03/09 run date is wrong.** The code fix is deployed (new runs use local date), but the existing DB record still has the wrong date.

## Proposed Solution

### Phase 1: RMR-Based Nutrition Intelligence

**New pure function in `coaching.py`:**

```python
# src/services/coaching.py

@dataclass
class NutritionPlan:
    rmr: int                    # Mifflin-St Jeor RMR (kcal/day)
    rmr_adapted: int            # RMR * 0.90 (metabolic adaptation during cut)
    tdee: int                   # Adapted RMR * activity multiplier
    daily_deficit: int          # Based on weight gap / weeks remaining
    calorie_target: int         # TDEE - deficit (floored at 1200)
    protein_target_grams: int   # 1g per lb of current weight
    weekly_loss_rate: float     # lbs/week (capped at 1.0 for athletes)
    weeks_to_goal: float | None # None if no goal set
    is_safe: bool               # True if deficit <= 1000 cal/day
    warning: str | None         # "Timeline requires aggressive deficit" etc.


def compute_nutrition_plan(
    weight_lbs: float,
    height_inches: int,
    age: int,
    sex: str,                   # "male" | "female"
    goal_weight_lbs: float | None = None,
    goal_target_date: date | None = None,
    activity_multiplier: float = 1.55,  # moderately active runner default
) -> NutritionPlan:
```

**Mifflin-St Jeor formula (the evidence-based standard):**
```
weight_kg = weight_lbs / 2.205
height_cm = height_inches * 2.54
Male:   RMR = (10 * weight_kg) + (6.25 * height_cm) - (5 * age) + 5
Female: RMR = (10 * weight_kg) + (6.25 * height_cm) - (5 * age) - 161
```

**Metabolic adaptation:** When cutting, RMR drops ~10% beyond what mass loss predicts (Martins et al., 2020). Apply unconditionally when a deficit is active: `rmr_adapted = rmr * 0.90`.

**TDEE:** `tdee = rmr_adapted * activity_multiplier` where activity_multiplier defaults to 1.55 (moderately active, appropriate for running 5-6 days/week).

**Deficit calculation:**
```
if goal_weight_lbs and goal_target_date and goal_target_date > today:
    weight_to_lose = weight_lbs - goal_weight_lbs
    weeks_remaining = (goal_target_date - today).days / 7
    weekly_rate = weight_to_lose / weeks_remaining
    weekly_rate = clamp(weekly_rate, 0, 1.0)   # cap at 1 lb/week for athletes
    daily_deficit = weekly_rate * 3500 / 7      # 3500 cal ≈ 1 lb
else:
    daily_deficit = 375  # default 0.75 lb/week
```

**Safety bounds:**
- Daily deficit capped at 1000 cal/day (2 lbs/week max)
- Calorie target floored at 1200 cal/day (medical minimum)
- If computed target < 1200 or deficit > 1000, set `warning` message and `is_safe = False`

**Protein:** 1g per lb of current body weight (ISSN position stand for athletes in deficit). Minimum 150g.

**Weight source:** Use latest `BodyComp.weight_lbs` entry, falling back to `UserProfile.weight_lbs`. This makes nutrition targets auto-recalculate as the user logs body comp.

#### Backend changes

**`src/services/coaching.py`** — Add `NutritionPlan` dataclass + `compute_nutrition_plan()` function. ~50 lines. Pure computation, no DB.

**`src/routes/briefing.py:187-224`** — Replace the `weight * 13 / 15 / 11` block with:
1. Fetch latest body comp weight (or fall back to profile weight)
2. Call `compute_nutrition_plan()` with profile data
3. Still allow custom `goal_calorie_target` / `goal_protein_target_grams` to override
4. Include the full `NutritionPlan` fields in the response so the frontend can show RMR, TDEE, deficit breakdown
5. Keep training-day adjustment: hard days get a smaller deficit (or maintenance), rest days get a larger deficit

**`src/routes/briefing.py` response shape:**
```json
"nutrition_target": {
  "calories": 1850,
  "protein_grams": 196,
  "rmr": 1888,
  "rmr_adapted": 1699,
  "tdee": 2634,
  "daily_deficit": 375,
  "weekly_loss_rate": 0.75,
  "weeks_to_goal": 14.7,
  "day_type": "easy",
  "target_source": "auto",
  "is_safe": true,
  "warning": null,
  "yesterday": { "calories": 2426, "protein_grams": 175 }
}
```

#### Frontend changes

**Settings tab (`index.html` ~line 1537)** — Add:
- `goal_target_date` date picker in the Goals section (field exists in DB, not in UI)
- Show computed RMR as read-only info below the Body section: "Your estimated RMR: 1,888 cal/day"

**Nutrition tab (`index.html` ~line 829)** — Replace/enhance:
- Show the deficit breakdown: "RMR: 1,888 → Adapted: 1,699 → TDEE: 2,634 → Target: 1,850 (deficit: 375/day)"
- Add daily feedback sentence above the progress bars:
  - Over target: "You ate 2,426 cal — that's 576 over your 1,850 target."
  - Under/on target: "You ate 1,700 cal — 150 under your 1,850 target. On track."
  - Under 1200: "You ate 1,100 cal — too low. Eating below 1,200 can slow your metabolism further."
  - Nothing logged: "No meals logged yet today. Target: 1,850 cal."
- Show protein feedback: "Protein: 175g / 196g target (89%)"
- Show weeks to goal: "At this rate, you'll hit 185 lbs in ~15 weeks (Jun 22)"
- If `is_safe` is false, show warning in red

**Settings auto-display (`index.html` ~line 1511)** — Replace `weight * 13` placeholder math with computed RMR display. Remove the misleading "Auto: 2548" placeholder. Instead show "Based on Mifflin-St Jeor: ~1,850 cal/day" as hint text.

### Phase 2: Human-Readable Dashboard

**VDOT → Marathon time:** Add a function to `coaching.py`:
```python
def vdot_to_marathon_time(vdot: float) -> str:
    """Convert VDOT to estimated marathon time string like '3:18'."""
    pace_sec = (97.0 - vdot) / 0.1   # inverse of estimate_vdot linear fit
    marathon_sec = pace_sec * 26.2
    hours = int(marathon_sec // 3600)
    mins = int((marathon_sec % 3600) // 60)
    return f"{hours}:{mins:02d}"
```

**Backend (`briefing.py`):** Add to `pace_progress`:
```python
result["pace_progress"]["marathon_estimate"] = vdot_to_marathon_time(vdot)
result["pace_progress"]["marathon_target"] = f"{int(goal_time // 60)}:{int(goal_time % 60):02d}" if goal_time else None
```

**Frontend (`index.html` ~line 591):** Replace the jargon block with:
```
Marathon Fitness: ~3:18 → Goal: sub-3:00
Your running efficiency improved 19% this month
```

EF trend sentences:
- `improving`: "Your running efficiency improved X% this month"
- `plateau`: "Your running efficiency held steady this month"
- `declining`: "Your running efficiency dipped X% this month — could be fatigue or increased training load"
- No data: hide the sentence

### Phase 3: Biological Age Prompt

**Frontend (`index.html` ~line 1332):** Add an else branch:
```jsx
{bioAge ? (
  // existing hero card
) : (
  <div className="card" style={{ textAlign: 'center', padding: '24px' }}>
    <div style={{ color: '#888', marginBottom: 12 }}>
      {!data?.vo2max_estimate
        ? "Need more run data with heart rate for biological age estimate."
        : "Set your sex and age in Settings to see your biological age."}
    </div>
    <button className="btn btn-sm" onClick={() => setTab('settings')}>
      Go to Settings
    </button>
  </div>
)}
```

This requires threading `setTab` into `LongevityTab`. Currently `LongevityTab` takes no props — it needs `setTab` added.

### Phase 4: Fix 03/09 Run Date

**`src/database.py` `_run_migrations()`** — Add one-time idempotent fix:
```python
# Fix run logged on 2026-03-08 local time that was stored as 2026-03-09 UTC
# The 12.0 mi / 140 min run is the only one on that date
conn.execute(text(
    "UPDATE runs SET date = '2026-03-08' "
    "WHERE date = '2026-03-09' AND distance_miles = 12.0 AND time_minutes = 140.0"
))
```

This is safe because it targets a specific run by date + distance + time, and is idempotent (running it twice changes nothing).

## Technical Considerations

### Architecture

All new computation goes in `coaching.py` (pure functions, no DB). The briefing route orchestrates by reading profile + latest body comp, calling the computation, and assembling the response. Frontend formats the response for display.

### Weight Source Priority

```
1. Latest BodyComp.weight_lbs (most recent weigh-in)
2. UserProfile.weight_lbs (profile setting)
3. None (show prompt to log weight)
```

This means logging a body comp entry automatically influences nutrition targets on the next page load.

### Graceful Degradation

Every computation returns sensible output or `None` when inputs are missing:
- No sex → fall back to old formula, show prompt
- No height → fall back to old formula
- No goal weight/date → show targets without deficit/timeline info
- No nutrition logged → show targets only, no feedback sentence

### Safety

- Calorie floor: 1200 cal/day (never auto-calculate below this)
- Deficit cap: 1000 cal/day (never suggest losing more than 2 lbs/week)
- Loss rate cap for athletes: 1.0 lb/week (Garthe et al., 2011)
- Warning banner when computed plan is aggressive

## Acceptance Criteria

### Phase 1: Nutrition Intelligence
- [x] `compute_nutrition_plan()` in `coaching.py` with Mifflin-St Jeor RMR
- [x] Briefing endpoint returns RMR, TDEE, deficit, weekly rate, weeks to goal
- [x] Custom targets still override auto-calculated
- [x] Latest body comp weight used (falls back to profile weight)
- [x] `goal_target_date` date picker in Settings UI
- [x] Nutrition tab shows deficit breakdown (RMR → TDEE → Target)
- [x] Daily feedback sentence: over/under/on track
- [x] Protein feedback with percentage
- [x] Weeks-to-goal with estimated date
- [x] Safety: floor at 1200 cal, cap deficit at 1000 cal/day
- [x] Warning shown when plan is aggressive

### Phase 2: Dashboard UX
- [x] VDOT replaced with estimated marathon time ("~3:18")
- [x] Target shown as marathon time ("sub-3:00")
- [x] EF trend shown as plain English sentence
- [x] No jargon visible on dashboard

### Phase 3: Bio Age Prompt
- [x] Longevity tab shows prompt when sex/age not set
- [x] Prompt includes "Go to Settings" button
- [x] Shows different message when VO2max is missing vs. profile data missing

### Phase 4: Date Fix
- [x] 03/09 run corrected to 03/08 in database
- [x] Migration is idempotent (safe to run multiple times)

## Implementation Order

1. **Phase 1 backend** — `coaching.py` nutrition plan + `briefing.py` integration
2. **Phase 4** — Date fix migration (quick, independent)
3. **Phase 2 backend** — `vdot_to_marathon_time()` + briefing response changes
4. **Phase 3 + Phase 2 frontend** — All frontend changes together (Settings, Nutrition tab, Dashboard, Longevity tab)
5. **Deploy + verify**

## Files Changed

| File | Changes |
|------|---------|
| `src/services/coaching.py` | Add `NutritionPlan`, `compute_nutrition_plan()`, `vdot_to_marathon_time()` |
| `src/routes/briefing.py` | Replace nutrition calculation, add marathon time to pace_progress |
| `src/database.py` | Add date fix migration |
| `src/static/index.html` | Settings: goal_target_date + RMR display. Nutrition: deficit breakdown + feedback. Dashboard: plain English. Longevity: bio age prompt |

## Sources & References

- Mifflin-St Jeor equation: Mifflin MD, St Jeor ST, et al. Am J Clin Nutr. 1990;51(2):241-7
- Metabolic adaptation: Martins et al., Metabolism, 2020 — ~5-15% reduction in RMR during sustained deficit
- Protein during cut: ISSN Position Stand (Jager et al., 2017) — 1.0-1.2 g/lb for athletes in deficit
- Safe loss rate for athletes: Garthe et al., 2011 — 0.7% body weight/week preserves lean mass
- 3500 kcal/lb planning constant: Standard, with Kevin Hall's NIH caveat that it over-predicts by ~20% over 6+ months
- Activity multipliers: Katch-McArdle model (1.2-1.9 range)
