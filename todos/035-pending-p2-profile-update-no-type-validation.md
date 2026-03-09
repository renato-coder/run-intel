---
status: complete
priority: p2
issue_id: "035"
tags: [code-review, validation, api, profile]
dependencies: []
---

# Profile Update Sets Raw Values Without Type Checking

## Problem Statement

PUT /api/profile (src/routes/profile.py:23-59) uses `setattr(profile, k, v)` to set user-provided values directly on the SQLAlchemy model. If a user sends `{"age": "not_a_number"}`, it gets set on the model and fails at DB commit with an unhelpful IntegrityError from the CHECK constraint.

## Findings

- **Location**: `src/routes/profile.py:51-52`
- **Evidence**: `for k, v in updates.items(): setattr(profile, k, v)` — no type coercion
- **Impact**: Non-numeric values cause 500 errors instead of 400 with clear message

## Proposed Solutions

### Option A: Add type coercion/validation for each field
- **Pros**: Clear error messages, prevents DB errors
- **Cons**: More code
- **Effort**: Small
- **Risk**: Low

## Acceptance Criteria

- [ ] Numeric fields are validated/coerced before setting on model
- [ ] Invalid types return 400 with descriptive error message
- [ ] CHECK constraint violations are caught gracefully

## Work Log

| Date | Action | Learnings |
|------|--------|-----------|
| 2026-03-09 | Created from code review | setattr pattern bypasses validation |
