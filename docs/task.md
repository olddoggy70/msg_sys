*Last updated: 2025-12-24 13:42 EST*

# CLS Integration Tasks

## Phase 1: Core Setup
- [ ] `core/config.py` — env-aware settings
- [ ] `core/broker.py` — embedded NATS launch
- [ ] `core/middleware.py` — audit logging
- [ ] `core/priority.py` — Priority, Category, UpgradeAction enums
- [ ] `core/dispatcher.py` — priority bucket routing

## Phase 2: CLS Integration
- [ ] Copy CLS_Allscripts into msg_sys
- [ ] `pipelines/cls_all/models.py`
- [ ] `pipelines/cls_all/tasks.py`
- [ ] Update CLS orchestrators with return values

## Phase 3: Dash Dashboard
- [ ] `dashboard/app.py` — layout
- [ ] `dashboard/callbacks/pipeline_cb.py` — run triggers
- [ ] `dashboard/callbacks/upgrade_cb.py` — priority buttons
- [ ] Status polling + audit viewer

## Phase 4: Entry Point
- [ ] `run_dashboard.py`
- [ ] End-to-end test
- [ ] PyInstaller (optional)
