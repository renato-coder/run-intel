---
status: complete
priority: p2
issue_id: "008"
tags: [code-review, performance]
dependencies: ["003"]
---

# Unbounded Database Queries on Hot Paths

## Problem Statement

Multiple API endpoints load entire tables into memory and build pandas DataFrames just to compute simple aggregates, adding unnecessary latency and memory overhead.

## Findings

### 1. generate_coaching_insight loads ALL runs
- **File:** `src/app.py:219`
- `session.query(Run).all()` on every POST /api/runs
- Builds pandas DataFrame, then filters to last 30 days
- Only needs ~30 days of data with valid pace and HR
- **Agents:** Performance Oracle, Code Simplicity Reviewer

### 2. get_snapshot loads ALL runs and ALL recoveries
- **File:** `src/app.py:517-518`
- Two full table scans, two DataFrame constructions
- Only needs 30-day aggregates that could be SQL `AVG()`
- **Agent:** Performance Oracle

### 3. pandas used for trivial operations
- `pd.notna()` in `safe_float()` for a simple None check
- ~30MB import overhead, ~150ms cold start penalty
- **Agent:** Code Simplicity Reviewer

## Proposed Solutions

### Option A: Filtered queries + drop pandas from app.py (Recommended)
- Push date filters into SQL: `Run.date >= date.today() - timedelta(days=30)`
- Replace DataFrame aggregates with SQL `func.avg()` or plain Python
- Remove pandas import from app.py entirely
- **Effort:** Medium
- **Risk:** Low

## Acceptance Criteria

- [ ] `generate_coaching_insight` queries only last 30 days
- [ ] `get_snapshot` uses SQL aggregates instead of loading all data
- [ ] pandas not imported in app.py
- [ ] No `session.query(Model).all()` on any hot path

## Work Log

| Date | Action | Learnings |
|------|--------|-----------|
| 2026-03-06 | Created from code review | |
