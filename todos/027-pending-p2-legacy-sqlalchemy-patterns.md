---
status: pending
priority: p2
issue_id: "027"
tags: [code-review, python, quality]
dependencies: []
---

# Legacy SQLAlchemy 1.x Patterns on SQLAlchemy 2.x

## Problem Statement

The codebase pins `sqlalchemy>=2.0,<3` but uses deprecated 1.x patterns: `declarative_base()`, `Column()`, and `typing.Generator` from the typing module. These work in 2.x but will be removed in 3.0.

## Findings

- **File:** `src/database.py:12,27,49-64`
- **Agent:** Python Quality Reviewer
- `declarative_base()` should be `DeclarativeBase` class
- `Column(...)` should be `mapped_column()` with `Mapped[]` type annotations
- `from typing import Generator` should be `collections.abc.Generator` or `Iterator[Session]`

## Proposed Solutions

### Solution A: Migrate to SQLAlchemy 2.0 style
Use `DeclarativeBase`, `Mapped[]`, and `mapped_column()`. This also adds type hints to model attributes for free.

- **Pros:** Future-proof, better type safety, modern patterns
- **Cons:** Larger diff
- **Effort:** Small-Medium
- **Risk:** Low

## Acceptance Criteria

- [ ] No `declarative_base()` usage
- [ ] Models use `Mapped[]` and `mapped_column()`
- [ ] No deprecated `typing` imports where `collections.abc` is available
