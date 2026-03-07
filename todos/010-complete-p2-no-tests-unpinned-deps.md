---
status: complete
priority: p2
issue_id: "010"
tags: [code-review, quality]
dependencies: []
---

# No Tests and Unpinned Dependencies

## Problem Statement

Zero test files exist in the repository, making refactoring dangerous. All 7 dependencies are unpinned, making builds non-reproducible.

## Findings

### 1. No tests (HIGH)
- No `tests/` directory, no `test_*.py`, no pytest in requirements
- Many pure functions are easily testable: pace conversions, briefing logic, coaching insights
- **Agents:** Architecture Strategist, Python Reviewer

### 2. Unpinned dependencies (HIGH)
- **File:** `requirements.txt`
- All 7 packages have no version specifiers
- `werkzeug` is imported directly but not listed
- SQLAlchemy 1.x vs 2.x has breaking API changes
- **Agents:** Python Reviewer, Security Sentinel

## Proposed Solutions

### Option A: Add pytest + pin deps (Recommended)
1. Pin dependencies with `>=min,<max` ranges
2. Add `werkzeug` to requirements
3. Add pytest with tests for pure functions first
- **Effort:** Medium
- **Risk:** Low

## Acceptance Criteria

- [ ] All dependencies pinned with version ranges
- [ ] `werkzeug` listed in requirements.txt
- [ ] pytest configured with at least: test_utils, test_briefing
- [ ] Tests pass in CI

## Work Log

| Date | Action | Learnings |
|------|--------|-----------|
| 2026-03-06 | Created from code review | |
