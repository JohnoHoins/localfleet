---
name: feedback_work_style
description: Johno's strict session rules — one file, test immediately, never modify schemas or working code
type: feedback
---

Absolute rules for every session:
1. SCHEMAS ARE GOD — all types from src/schemas.py. Never modify schemas. Fix the module.
2. ONE FILE per session (two max). Small, specific, testable.
3. TEST BEFORE MOVING ON — run it in this session.
4. NEVER REFACTOR WORKING CODE.
5. BUILD BOTTOM-UP — follow exact build order.

Also: read all dependency files before writing code. Import exactly from schemas, not redefine types.

**Why:** Prevents scope creep and regressions in a complex multi-module system.
**How to apply:** At session start, confirm which file to build. Read dependencies. Write module + tests. Run all tests. Stop.
