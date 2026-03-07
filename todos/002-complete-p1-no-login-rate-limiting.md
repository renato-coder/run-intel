---
status: complete
priority: p1
issue_id: "002"
tags: [code-review, security]
dependencies: []
---

# No Rate Limiting on Login Endpoint

## Problem Statement

The `/login` POST endpoint has zero rate limiting. Combined with a weak default password (see #001), this makes brute-force attacks trivial.

## Findings

- **File:** `src/app.py:94-108`
- No `flask-limiter` or equivalent in requirements.txt
- No throttling logic anywhere in the codebase
- An attacker can make unlimited password attempts per second
- **Agent:** Security Sentinel

## Proposed Solutions

### Option A: flask-limiter (Recommended)
- Install `flask-limiter` and add rate limits to the login endpoint (e.g., 5/minute)
- **Pros:** Simple, battle-tested
- **Cons:** New dependency
- **Effort:** Small
- **Risk:** Low

### Option B: Custom in-memory rate limiter
- Track failed attempts by IP in a dict with TTL
- **Pros:** No new dependency
- **Cons:** Not production-grade, doesn't survive restarts
- **Effort:** Small
- **Risk:** Medium

## Acceptance Criteria

- [ ] Login endpoint rate-limited to max 5 attempts per minute per IP
- [ ] Rate limit applies to failed attempts specifically
- [ ] Clear error message returned when rate limited

## Work Log

| Date | Action | Learnings |
|------|--------|-----------|
| 2026-03-06 | Created from code review | |
