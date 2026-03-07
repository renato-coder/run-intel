---
status: complete
priority: p2
issue_id: "007"
tags: [code-review, quality, performance]
dependencies: ["003"]
---

# Database Session Management: No Context Managers, No Rollback

## Problem Statement

All 13+ database interactions use manual `try/finally/session.close()` with no explicit rollback on errors. This is verbose, error-prone, and can poison the connection pool.

## Findings

- **File:** `src/app.py` (13 occurrences), `src/whoop.py` (2), `src/upload_history.py` (2)
- No `session.rollback()` anywhere in the codebase
- Failed commits leave connections in ambiguous transaction state
- `generate_coaching_insight()` opens a second independent session inside a route handler
- In `get_recovery_today()`, commit failure is silently caught, returning data that was never persisted
- **Agents:** Data Integrity Guardian, Performance Oracle, Python Reviewer, Architecture Strategist

## Proposed Solutions

### Option A: Context manager in database.py (Recommended)
```python
@contextmanager
def get_session():
    session = SessionLocal()
    try:
        yield session
        session.commit()
    except Exception:
        session.rollback()
        raise
    finally:
        session.close()
```
Replace all 17 `SessionLocal()` calls with `with get_session() as session:`
- **Effort:** Small-Medium
- **Risk:** Low

## Acceptance Criteria

- [ ] Context manager defined in database.py
- [ ] All session usage converted to context manager pattern
- [ ] Explicit rollback on all error paths
- [ ] No manual `session.close()` calls remaining

## Work Log

| Date | Action | Learnings |
|------|--------|-----------|
| 2026-03-06 | Created from code review | 4 agents flagged session management |
