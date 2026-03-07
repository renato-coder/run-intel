---
status: complete
priority: p3
issue_id: "013"
tags: [code-review, simplicity]
dependencies: []
---

# Dead Code: CSV-Based CLI Scripts and Unused API Methods

## Problem Statement

Three CLI scripts (783 lines total) operate exclusively on CSV files that the web app no longer uses. Three Whoop API methods are defined but never called. This is dead weight from the pre-database era.

## Findings

### 1. Dead CLI scripts
- `src/log_run.py` (155 lines) - writes to CSV, web app uses PostgreSQL
- `src/backfill.py` (181 lines) - writes to CSV, web app uses PostgreSQL
- `src/trends.py` (447 lines) - reads from CSV, web dashboard provides same data
- None are imported by any other module
- **Agents:** Code Simplicity Reviewer, Architecture Strategist

### 2. Unused Whoop API methods
- `src/whoop.py:264` - `get_sleep()` never called
- `src/whoop.py:268` - `get_cycles()` never called
- `src/whoop.py:276` - `get_body()` never called
- **Agent:** Code Simplicity Reviewer

## Proposed Solutions

### Option A: Delete dead code (Recommended)
- Delete `log_run.py`, `backfill.py`, `trends.py`
- Remove unused Whoop API methods
- **Effort:** Small
- **Risk:** Low (code is in git history if ever needed)

## Acceptance Criteria

- [ ] Dead CLI scripts removed
- [ ] Unused API methods removed
- [ ] ~870 lines of dead code eliminated

## Work Log

| Date | Action | Learnings |
|------|--------|-----------|
| 2026-03-06 | Created from code review | |
