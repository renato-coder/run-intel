---
status: pending
priority: p3
issue_id: "029"
tags: [code-review, simplicity, dependencies]
dependencies: []
---

# pandas (~40MB) Used Only in One-Time CSV Seeder Script

## Problem Statement

The `pandas` library is a ~40MB production dependency used only in `upload_history.py`, a one-time CSV seeding script. Python's built-in `csv.DictReader` would accomplish the same thing.

## Findings

- **File:** `requirements.txt:8`, `src/upload_history.py:15`
- **Agents:** Code Simplicity Reviewer, Architecture Strategist, Performance Oracle
- Only `pd.read_csv()` and `df.iterrows()` are used
- `iterrows()` is notoriously slow; `csv.DictReader` would be equivalent or faster

## Proposed Solutions

### Solution A: Replace with `csv.DictReader`
Use stdlib `csv` module. Remove `pandas` from `requirements.txt`.

- **Pros:** 40MB smaller deployment, no external dependency for seeder
- **Cons:** Slightly more manual type conversion
- **Effort:** Small
- **Risk:** Low

## Acceptance Criteria

- [ ] `pandas` removed from `requirements.txt`
- [ ] `upload_history.py` works with `csv.DictReader`
