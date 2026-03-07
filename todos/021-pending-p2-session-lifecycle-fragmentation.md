---
status: pending
priority: p2
issue_id: "021"
tags: [code-review, architecture, performance]
dependencies: []
---

# Fragmented Database Sessions -- Multiple Independent Sessions per Request

## Problem Statement

A single HTTP request can open 3+ independent database sessions: one for WhoopClient token loading, one for the main route handler, and one inside `generate_coaching_insight`. This wastes connections, creates transaction consistency gaps, and risks pool exhaustion.

## Findings

- **Files:** `src/app.py:242` (coaching opens own session), `src/app.py:530` (log_run session), `src/whoop.py:126-139` (token session)
- **Agents:** Architecture Strategist (Critical), Performance Oracle (Critical), Python Quality Reviewer (Important)
- `generate_coaching_insight` opens its own `get_session()` after the run-saving session has already committed.
- `WhoopClient` methods `_load_tokens_from_db` and `_save_tokens_to_db` use raw `SessionLocal()` instead of `get_session()` context manager.
- With `pool_size=3`, a single POST to `/api/runs` can consume 3 connections simultaneously.

## Proposed Solutions

### Solution A: Pass session through, use get_session() in WhoopClient
1. Pass the existing session to `generate_coaching_insight` instead of opening a new one.
2. Refactor WhoopClient token methods to use `get_session()`.

- **Pros:** Single session per request, proper rollback, fewer connections
- **Cons:** Requires threading session through function calls
- **Effort:** Small-Medium
- **Risk:** Low

## Acceptance Criteria

- [ ] `log_run` handler opens only one database session for the entire request
- [ ] WhoopClient token methods use `get_session()` context manager
- [ ] No raw `SessionLocal()` usage outside `get_session()`
