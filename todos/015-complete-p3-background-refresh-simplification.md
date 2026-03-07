---
status: complete
priority: p3
issue_id: "015"
tags: [code-review, architecture, simplicity]
dependencies: []
---

# Simplify or Remove Background Refresh Thread

## Problem Statement

The background recovery refresh system (70 lines, 3 functions + before_request hook) uses recursive threading.Timer with no cancellation, race conditions on startup, and is redundant with on-demand fetching already in the API endpoints.

## Findings

- **File:** `src/app.py:665-736`
- `_bg_started` flag has no thread safety (race condition on concurrent first requests)
- Each gunicorn worker spawns its own refresh loop, multiplying Whoop API calls
- Recursive Timer chain creates new thread objects every 30 minutes indefinitely
- No cancellation mechanism for clean shutdown
- The `get_briefing` and `get_recovery_today` endpoints already fetch from Whoop on-demand
- Recovery scores update once per day (when Whoop processes sleep), not every 30 min
- **Agents:** Code Simplicity Reviewer, Performance Oracle, Architecture Strategist, Security Sentinel

## Proposed Solutions

### Option A: Remove entirely (Recommended)
- Delete lines 665-736
- Rely on on-demand fetching in `get_briefing` and `get_recovery_today`
- Recovery data is already cached to DB on first fetch
- **Effort:** Small
- **Risk:** Low

### Option B: Fix with proper locking + scheduler
- Use `threading.Lock` for startup flag
- Use APScheduler for periodic tasks
- **Effort:** Medium
- **Risk:** Low

## Acceptance Criteria

- [ ] No race conditions in background task startup
- [ ] No duplicate refresh loops in multi-worker deployment
- [ ] Recovery data still fresh on API requests

## Work Log

| Date | Action | Learnings |
|------|--------|-----------|
| 2026-03-06 | Created from code review | |
