---
status: pending
priority: p3
issue_id: "030"
tags: [code-review, simplicity]
dependencies: []
---

# Three-Tier Token Resolution Is Over-Engineered

## Problem Statement

`WhoopClient.__init__` tries DB, then env vars, then file for token loading. The env-var tier is useless in steady state because tokens expire in ~1 hour and static env vars go stale immediately after the first refresh.

## Findings

- **File:** `src/whoop.py:46-49,141-151`
- **Agent:** Code Simplicity Reviewer
- Auth flow (`auth.py`) writes to both DB and file on initial setup
- After first token refresh, env vars are permanently stale
- 3 sources of truth creates debugging confusion

## Proposed Solutions

### Solution A: Remove env-var tier
Drop `_load_tokens_from_env`. Keep DB as primary, file as fallback.

- **Pros:** Simpler, fewer failure modes, ~10 LOC removed
- **Cons:** Can't bootstrap via env vars (but auth.py handles initial setup)
- **Effort:** Small
- **Risk:** Low

## Acceptance Criteria

- [ ] `_load_tokens_from_env` removed
- [ ] Token resolution is DB -> file (2 tiers)
