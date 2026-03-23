---
name: project_build_order
description: LocalFleet build order progress — tracking which steps are complete
type: project
---

Build order progress as of 2026-03-23:
- Step 1: schemas.py — DONE
- Step 2: drone_dynamics.py — DONE
- Step 3: gps_denied.py — DONE
- Step 4: ollama_client.py — DONE
- Step 5: fleet_manager.py — DONE (completed 2026-03-23)
- Step 6: fleet_commander.py — DONE (completed 2026-03-23)
- Step 7+: drone_coordinator → formations/task_allocator → API server → dashboard → voice → logging

**Why:** Strict bottom-up build order ensures each module can be tested in isolation before being composed.
**How to apply:** Always check what step is next before writing code. Never skip ahead.
