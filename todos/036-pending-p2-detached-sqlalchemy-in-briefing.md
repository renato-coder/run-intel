---
status: complete
priority: p2
issue_id: "036"
tags: [code-review, sqlalchemy, briefing]
dependencies: []
---

# Detached SQLAlchemy Instance in Briefing Route

## Problem Statement

`get_briefing()` in src/routes/briefing.py accesses the `profile` SQLAlchemy object (lines 150-210) after the `with get_session() as session:` block closes (block ends at line 138). Currently works because UserProfile has only Column attributes (eagerly loaded), but will break silently if relationships or deferred columns are added.

## Findings

- **Location**: `src/routes/briefing.py:89-138` (session block) and `src/routes/briefing.py:150-210` (profile access after close)
- **Evidence**: `profile.max_hr`, `profile.goal_marathon_time_min`, `profile.weight_lbs`, `profile.goal_body_fat_pct` accessed outside session
- **Impact**: Fragile — future schema changes could cause DetachedInstanceError

## Proposed Solutions

### Option A: Move all logic inside the session block
- **Pros**: Eliminates the issue entirely
- **Cons**: Larger indented block
- **Effort**: Small
- **Risk**: Low

### Option B: Extract needed values to a dict before closing session
- **Pros**: Explicit about what data is needed
- **Cons**: Slightly more code
- **Effort**: Small
- **Risk**: Low

## Acceptance Criteria

- [ ] All SQLAlchemy model access happens within session scope
- [ ] No DetachedInstanceError possible

## Work Log

| Date | Action | Learnings |
|------|--------|-----------|
| 2026-03-09 | Created from code review | Session scope vs object access timing |
