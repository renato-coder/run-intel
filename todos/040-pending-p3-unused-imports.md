---
status: complete
priority: p3
issue_id: "040"
tags: [code-review, cleanup]
dependencies: []
---

# Unused Imports

## Problem Statement

Two unused imports after the refactor:
1. `functools.wraps` in app.py (line 11) — was used by removed `require_auth` decorator
2. `get_session` in metrics_service.py (line 9) — function receives session as parameter

## Findings

- **Location**: `src/app.py:11` and `src/services/metrics_service.py:9`

## Proposed Solutions

### Option A: Remove unused imports
- **Effort**: Trivial
- **Risk**: None

## Acceptance Criteria

- [ ] `functools.wraps` removed from app.py
- [ ] `get_session` removed from metrics_service.py imports

## Work Log

| Date | Action | Learnings |
|------|--------|-----------|
| 2026-03-09 | Created from code review | Post-refactor cleanup |
