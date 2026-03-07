---
status: complete
priority: p3
issue_id: "014"
tags: [code-review, performance]
dependencies: []
---

# Frontend: Eliminate Runtime Babel Transpilation

## Problem Statement

The frontend loads ~800KB of Babel standalone to transpile JSX in the browser at runtime, adding ~200-400ms to every page load. This is explicitly not recommended for production by the Babel team.

## Findings

- **File:** `src/static/index.html:11`
- `@babel/standalone` (~320KB gzipped, ~800KB uncompressed) loaded on every page view
- Total synchronous render-blocking JS: ~438KB gzipped (React + ReactDOM + Babel + Chart.js)
- CDN versions not pinned to exact semver
- **Agents:** Performance Oracle, Code Simplicity Reviewer, Security Sentinel

## Proposed Solutions

### Option A: Switch to htm tagged templates (Recommended)
- Replace JSX with `htm` (~1KB, JSX-like syntax, no build step)
- Drop Babel dependency entirely
- **Effort:** Medium
- **Risk:** Low

### Option B: Pre-compile with build step
- `npx babel src/static/app.jsx --out-file src/static/app.js`
- One-time build, serve pre-compiled JS
- **Effort:** Small
- **Risk:** Low

### Option C: Switch to Preact + htm
- Preact (~3KB) + htm (~1KB) replaces React (48KB) + Babel (320KB)
- Same API, 99% smaller
- **Effort:** Medium
- **Risk:** Low-Medium

## Acceptance Criteria

- [ ] No runtime transpilation in production
- [ ] Page JS payload reduced by at least 300KB
- [ ] CDN versions pinned with exact semver

## Work Log

| Date | Action | Learnings |
|------|--------|-----------|
| 2026-03-06 | Created from code review | |
