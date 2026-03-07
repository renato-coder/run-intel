---
status: complete
priority: p3
issue_id: "016"
tags: [code-review, quality]
dependencies: []
---

# Project Hygiene: Package Structure, Gitignore, README

## Problem Statement

The project lacks proper Python packaging, has a 150-line Node.js-focused .gitignore, a stale README, no __init__.py, and sys.path hacks.

## Findings

### 1. No __init__.py / sys.path hacks
- `src/` has no `__init__.py`
- `app.py:26` and `upload_history.py:15` hack `sys.path.insert`
- **Agents:** Python Reviewer, Architecture Strategist

### 2. .gitignore is 90% irrelevant Node.js boilerplate
- **File:** `.gitignore` (150 lines)
- ~130 lines for Gatsby, Nuxt, Vuepress, Sveltekit, etc.
- Could be ~10 lines
- **Agent:** Code Simplicity Reviewer

### 3. README documents stale architecture
- **File:** `README.md`
- No mention of web app, PostgreSQL, briefing, coaching, shoe tracking
- Documents CSV-based CLI workflow only
- **Agent:** Architecture Strategist

### 4. Inconsistent timezone handling
- `app.py:575` uses `datetime.now()` (local time)
- `app.py:579` uses `datetime.now(timezone.utc)` (UTC)
- These can produce different dates depending on server timezone
- **Agents:** Data Integrity Guardian

## Proposed Solutions

### Option A: Clean up incrementally
1. Add `src/__init__.py`, remove sys.path hacks
2. Replace .gitignore with Python-focused version
3. Update README to reflect current architecture
4. Standardize on UTC for all date operations
- **Effort:** Small
- **Risk:** Low

## Acceptance Criteria

- [ ] `src/__init__.py` exists
- [ ] No `sys.path.insert` calls in any file
- [ ] .gitignore is Python-focused (~10-15 lines)
- [ ] README accurately describes current architecture
- [ ] All date operations use consistent timezone handling

## Work Log

| Date | Action | Learnings |
|------|--------|-----------|
| 2026-03-06 | Created from code review | |
