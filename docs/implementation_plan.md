*Last updated: 2025-12-24 13:42 EST*

# CLS_ALL Integration with msg_sys

## Architecture

**Distributed-first, centralized-ready** with priority queue system.

```
┌────────────────────────────────────────────────────────────────┐
│                    Operator's Machine                          │
│  ┌──────────────────────────────────────────────────────────┐ │
│  │ Dash UI (:8050)                                           │ │
│  │ [Run Sync] [Run Integrate] [⬆️ Prioritize] [🔥 Urgent]   │ │
│  └─────────────────────────┬────────────────────────────────┘ │
│                            ▼                                   │
│  ┌──────────────────────────────────────────────────────────┐ │
│  │ msg_sys Core                                              │ │
│  │  ┌───────────┐  ┌───────────┐  ┌───────────┐            │ │
│  │  │Dispatcher │→ │ Priority  │→ │ Workers   │            │ │
│  │  │(routing)  │  │ Buckets   │  │ (h/n/l)   │            │ │
│  │  └───────────┘  └───────────┘  └───────────┘            │ │
│  │          NATS (embedded) ← → SQLite (audit)              │ │
│  └─────────────────────────┬────────────────────────────────┘ │
│                            ▼                                   │
│  ┌──────────────────────────────────────────────────────────┐ │
│  │ CLS_Allscripts (direct import)                            │ │
│  └──────────────────────────────────────────────────────────┘ │
└────────────────────────────────────────────────────────────────┘
```

---

## File Structure (Including Priority System)

```
msg_sys/
├── core/
│   ├── __init__.py
│   ├── broker.py           # Shared NATS broker + embedded launch
│   ├── config.py           # Pydantic settings (NATS_URL, AUDIT_DB, etc.)
│   ├── middleware.py       # Audit middleware (task lifecycle)
│   ├── dispatcher.py       # Smart routing to priority buckets
│   └── priority.py         # Priority, Category, Phase, UpgradeAction enums
│
├── pipelines/cls_all/
│   ├── __init__.py
│   ├── tasks.py            # Taskiq tasks (cls_sync, cls_integrate, etc.)
│   ├── events.py           # Pipeline chaining (sync.completed → integrate)
│   └── models.py           # CLSSyncParams, CLSPipelineResult
│
├── workers/
│   ├── __init__.py
│   ├── priority_worker.py  # Priority-aware consumer (high → normal → low)
│   └── phase_workers.py    # Optional: per-phase scaling
│
├── dashboard/
│   ├── __init__.py
│   ├── app.py              # Dash main app
│   ├── auth.py             # RBAC decorators (@require_permission)
│   ├── layouts/
│   │   ├── home.py         # Status overview
│   │   ├── pipeline.py     # Run/monitor pipelines
│   │   └── audit.py        # Task history + priority_history
│   ├── callbacks/
│   │   ├── pipeline_cb.py  # [Run Sync], [Run All]
│   │   └── upgrade_cb.py   # [⬆️ Prioritize], [🔥 Urgent], [🚨 Critical]
│   └── assets/style.css
│
├── db/
│   ├── audit.db            # task_audit + priority_history tables
│   └── users.db            # RBAC (users + role_permissions) - for later
│
├── cls_allscripts/         # [COPY] from D:\Projects\data-science\CLS_Allscripts
│   ├── main.py
│   └── src/{sync,integrate,classify,export}
│
├── run_dashboard.py        # Entry point (starts NATS + workers + Dash)
├── pyproject.toml          # Merged dependencies
└── .env                    # Config overrides
```

---

## Priority System Summary

| Level | Name | Bucket | Dash Button |
|-------|------|--------|-------------|
| 10 | Critical | high | 🚨 Critical |
| 9 | Urgent | high | 🔥 Urgent |
| 8 | Prioritize | high | ⬆️ Prioritize |
| 5 | Normal | normal | (default) |
| 0-3 | Low | low | — |

**RBAC**: Viewer → Operator (prioritize) → Manager (urgent) → Admin (critical)

---

## Implementation Phases

### Phase 1: Core Setup
- [ ] `core/config.py` — env-aware settings
- [ ] `core/broker.py` — embedded NATS launch
- [ ] `core/middleware.py` — audit logging
- [ ] `core/priority.py` — Priority, Category, UpgradeAction enums
- [ ] `core/dispatcher.py` — priority bucket routing

### Phase 2: CLS Integration
- [ ] Copy CLS_Allscripts into msg_sys
- [ ] `pipelines/cls_all/models.py`
- [ ] `pipelines/cls_all/tasks.py` — direct import wrappers
- [ ] Minor CLS mods: add return values

### Phase 3: Dash Dashboard
- [ ] `dashboard/app.py` — layout with action buttons
- [ ] `dashboard/callbacks/pipeline_cb.py` — run triggers
- [ ] `dashboard/callbacks/upgrade_cb.py` — priority upgrade buttons
- [ ] Status polling + audit log viewer

### Phase 4: Entry Point
- [ ] `run_dashboard.py` — orchestrates startup
- [ ] End-to-end test
- [ ] PyInstaller (optional)
