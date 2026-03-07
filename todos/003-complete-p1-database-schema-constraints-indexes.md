---
status: complete
priority: p1
issue_id: "003"
tags: [code-review, performance, architecture, data-integrity]
dependencies: []
---

# Database Schema: Missing Constraints, Indexes, and Migration Strategy

## Problem Statement

The database schema has no unique constraints, no indexes on queried columns, and no migration strategy. This causes race conditions, potential data duplication, cartesian join products, and full table scans on every request.

## Findings

### 1. Missing UNIQUE constraint on Recovery.date (CRITICAL)
- **File:** `src/database.py:71`
- Multiple recovery rows per date are possible, causing cartesian products in the `outerjoin` at `src/app.py:405`
- Background refresh + API request can both insert for the same date (race condition)
- **Agents:** Data Integrity Guardian, Performance Oracle, Architecture Strategist

### 2. No indexes on any queried column (HIGH)
- **File:** `src/database.py:27-92`
- `Recovery.date`, `Run.date`, `Run.shoes` are frequently filtered/joined but have no indexes
- Every API endpoint performs full sequential scans
- **Agent:** Performance Oracle

### 3. No migration strategy (HIGH)
- **File:** `src/database.py:94-96`
- `create_all` only creates tables that don't exist; it cannot add columns, constraints, or indexes to existing tables
- Any schema fix requires manual SQL or Alembic
- **Agents:** Data Integrity Guardian, Architecture Strategist

### 4. No connection pool configuration
- **File:** `src/database.py:21`
- No pool_size, pool_recycle, or pool_pre_ping configured
- Stale connections on cloud-hosted PostgreSQL cause intermittent 500 errors
- **Agent:** Performance Oracle

## Proposed Solutions

### Option A: Add constraints + indexes + Alembic (Recommended)
1. Add `unique=True, index=True` on `Recovery.date`
2. Add `index=True` on `Run.date`
3. Configure connection pool with `pool_pre_ping=True, pool_recycle=300`
4. Install Alembic, generate initial migration
5. Deduplicate existing recovery data before adding constraint
- **Effort:** Medium
- **Risk:** Low (additive changes)

### Option B: Constraints + indexes without Alembic
- Apply schema changes via raw SQL migration script
- **Effort:** Small
- **Risk:** Medium (no migration history tracking)

## Acceptance Criteria

- [ ] `Recovery.date` has UNIQUE constraint
- [ ] `Recovery.date` and `Run.date` have indexes
- [ ] Connection pool configured with pre_ping and recycle
- [ ] Existing duplicate recovery data deduplicated
- [ ] Alembic configured for future migrations

## Work Log

| Date | Action | Learnings |
|------|--------|-----------|
| 2026-03-06 | Created from code review | 4 agents flagged schema issues independently |
