---
status: complete
priority: p2
issue_id: "012"
tags: [code-review, data-integrity]
dependencies: ["003"]
---

# Data Seeder (upload_history.py) Has No Duplicate Protection

## Problem Statement

Running `upload_history.py` twice inserts every CSV row again, doubling all data. All aggregate queries (averages, shoe mileage, briefing) return corrupted results.

## Findings

- **File:** `src/upload_history.py:49-74` (runs), `src/upload_history.py:87-100` (recovery)
- No existence check before INSERT
- No unique constraints to prevent duplicates at DB level
- Shoe mileage appears doubled, coaching insights corrupted
- **Agent:** Data Integrity Guardian

## Proposed Solutions

### Option A: Truncate-then-insert (Recommended for seeder)
- `session.query(Run).delete()` before inserting all rows
- Wrap in single transaction
- **Effort:** Small
- **Risk:** Low (this is a seeder, not incremental sync)

### Option B: Upsert with conflict handling
- After adding unique constraints (#003), use `ON CONFLICT DO NOTHING`
- **Effort:** Small
- **Risk:** Low

## Acceptance Criteria

- [ ] Running upload_history.py twice produces identical DB state
- [ ] Clear warning/confirmation before destructive operations

## Work Log

| Date | Action | Learnings |
|------|--------|-----------|
| 2026-03-06 | Created from code review | |
