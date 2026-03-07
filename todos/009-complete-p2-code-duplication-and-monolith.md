---
status: complete
priority: p2
issue_id: "009"
tags: [code-review, architecture, quality]
dependencies: []
---

# Code Duplication and Monolithic app.py

## Problem Statement

Four helper functions are copy-pasted across modules, six pace conversion implementations exist, recovery fetch logic is triplicated, and app.py is a 743-line monolith mixing 6+ responsibilities.

## Findings

### 1. Duplicated functions (HIGH)
- `format_pace`: `app.py:140`, `log_run.py:42`
- `find_closest_run`: `app.py:150`, `log_run.py:52`
- `safe_float`: `app.py:167`, `upload_history.py:23`
- `safe_int`: `app.py:176`, `upload_history.py:31`
- 6 separate pace conversion implementations across 4 files
- **Agents:** All 6 agents flagged this

### 2. Recovery fetch logic triplicated (HIGH)
- `get_briefing()`: `app.py:308-337`
- `get_recovery_today()`: `app.py:433-456`
- `_refresh_recovery()`: `app.py:672-708`
- Same ~25 lines copy-pasted 3 times with subtle differences
- **Agents:** Code Simplicity Reviewer, Architecture Strategist

### 3. app.py monolith (HIGH)
- 743 lines mixing: auth, helpers, coaching logic, 7 routes, background tasks, bootstrap
- **Agents:** Architecture Strategist, Python Reviewer

### 4. `today_start` UTC computation repeated 5 times
- `app.py:310-312, 435-437, 579-581, 674-676`, `log_run.py:92-94`
- **Agent:** Code Simplicity Reviewer

## Proposed Solutions

### Option A: Extract modules (Recommended)
1. Create `src/utils.py` with shared helpers (format_pace, safe_float, safe_int, etc.)
2. Create `fetch_and_cache_recovery()` function used by all 3 callers
3. Extract coaching logic to `src/coaching.py`
4. Extract auth to `src/web_auth.py`
5. Extract background tasks to `src/tasks.py`
- **Effort:** Medium
- **Risk:** Low

## Acceptance Criteria

- [ ] Zero duplicated function definitions across modules
- [ ] Recovery fetch logic exists in exactly one place
- [ ] app.py contains only route registrations and app bootstrap
- [ ] No function exceeds 50 lines

## Work Log

| Date | Action | Learnings |
|------|--------|-----------|
| 2026-03-06 | Created from code review | Universal agreement across all agents |
