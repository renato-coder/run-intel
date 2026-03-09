---
status: complete
priority: p2
issue_id: "028"
tags: [code-review, bug, python]
dependencies: []
---

# UTC vs Local Date Inconsistency -- Subtle Bug Near Midnight

## Problem Statement

The codebase uses `date.today()` (local time) in some places and `datetime.now(timezone.utc)` (UTC) in others. Around midnight, these produce different dates, causing the briefing endpoint and run logger to disagree on "today".

## Findings

- **File:** `src/app.py:154,317` (`date.today()` -- local), `src/app.py:480` (`datetime.now(timezone.utc)` -- UTC)
- **Agent:** Python Quality Reviewer (Minor but real bug)
- `fetch_and_cache_recovery` uses `date.today()` for "today"
- `log_run` uses UTC for "today"
- A run logged at 11pm EST would get a different date than the recovery fetched in the same request

## Proposed Solutions

### Solution A: Standardize on UTC everywhere
Replace all `date.today()` with `datetime.now(timezone.utc).date()`.

- **Pros:** Consistent, predictable, no timezone surprises
- **Cons:** "Today" might not match user's local date
- **Effort:** Small
- **Risk:** Low

## Acceptance Criteria

- [ ] All date computations use the same timezone (UTC)
- [ ] No `date.today()` calls remain in the codebase
