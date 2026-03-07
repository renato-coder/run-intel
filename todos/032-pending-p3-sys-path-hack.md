---
status: pending
priority: p3
issue_id: "032"
tags: [code-review, architecture, python]
dependencies: []
---

# `sys.path` Manipulation for Gunicorn Compatibility

## Problem Statement

`app.py` uses `sys.path.insert(0, ...)` to make sibling module imports work under gunicorn. This creates a dual-identity problem where modules can be imported as both `src.database` and `database`, potentially causing duplicate singletons.

## Findings

- **File:** `src/app.py:22`
- **Agents:** Architecture Strategist (Tier 1), Python Quality Reviewer
- Gunicorn loads `src.app:app` (package-style), but internal imports use bare names (`from config import ...`)
- `src/__init__.py` exists but is empty
- Could cause duplicate module objects in `sys.modules`

## Proposed Solutions

### Solution A: Convert to relative imports
Use `from .config import ...` throughout `src/` package.

- **Pros:** Clean, standard Python packaging
- **Cons:** Breaks `python src/app.py` direct execution; requires `python -m src.app`
- **Effort:** Medium
- **Risk:** Medium (all import statements change)

### Solution B: Keep sys.path hack, document it
Add a comment explaining why it exists and what would break without it.

- **Pros:** Zero risk, zero effort
- **Cons:** Hack remains
- **Effort:** Small
- **Risk:** None

## Acceptance Criteria

- [ ] No dual-module-identity risk, OR hack is explicitly documented
