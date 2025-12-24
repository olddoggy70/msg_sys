# Universal Priority Queue System Design

*Last updated: 2025-12-23*

## Overview

A flexible priority system for msg_sys covering:
- Task categories (ETL, webapp, report, alert)
- Priority levels (0-10)
- Multi-phase pipelines with bottleneck handling
- Urgent task upgrades

---

## Architecture

```
┌─────────────────────────────────────────────────────────────┐
│                    Task Dispatcher                          │
│                                                             │
│  await task.kiq(data, labels={                             │
│      "category": "etl",                                     │
│      "priority": 5,                                         │
│      "phase": "load",                                       │
│      "correlation_id": "etl-20231223-abc123"               │
│  })                                                         │
└─────────────────────────────────┬───────────────────────────┘
                                  │
                                  ▼
┌─────────────────────────────────────────────────────────────┐
│              NATS Subjects (Priority Buckets)               │
├─────────────────────────────────────────────────────────────┤
│  tasks.{category}.{phase}.high    (priority 8-10)          │
│  tasks.{category}.{phase}.normal  (priority 4-7)           │
│  tasks.{category}.{phase}.low     (priority 0-3)           │
└─────────────────────────────────────────────────────────────┘
                                  │
                                  ▼
┌─────────────────────────────────────────────────────────────┐
│              Priority-Aware Workers                         │
│                                                             │
│  1. Poll HIGH first → 2. Then NORMAL → 3. Then LOW         │
└─────────────────────────────────────────────────────────────┘
```

---

## Design Decisions

| Aspect | Decision | Rationale |
|--------|----------|-----------|
| **Priority levels** | 0-10 mapped to 3 buckets | Simple, effective, easy to reason about |
| **Subject pattern** | `tasks.{cat}.{phase}.{bucket}` | Flexible filtering per worker |
| **Upgrade mechanism** | Cancel + re-queue | Works with NATS, no custom broker needed |
| **Bottleneck handling** | Per-phase workers | Scale workers independently |

### Priority Levels (0-10)

| Level | Name | Bucket | Meaning |
|-------|------|--------|---------|
| **10** | Critical | high | 🚨 Production down, data loss imminent |
| **9** | Urgent | high | 🔥 Client waiting, SLA at risk |
| **8** | Prioritize | high | ⬆️ Needs attention soon (upgraded task) |
| **7** | High | normal | Important, but not emergency |
| **6** | Above Normal | normal | Slightly elevated priority |
| **5** | Normal | normal | ✅ Default for all tasks |
| **4** | Below Normal | normal | Can wait a bit |
| **3** | Low | low | Background work |
| **2** | Background | low | Run when idle |
| **1** | Maintenance | low | Cleanup, housekeeping |
| **0** | Lowest | low | Only if nothing else to do |

### Priority Buckets

| Range | Bucket | Processed |
|-------|--------|-----------|
| 8-10 | `high` | First |
| 4-7 | `normal` | Second |
| 0-3 | `low` | Last |

---

## Implementation

### 1. Smart Task Dispatcher

```python
# core/dispatcher.py
from enum import IntEnum, Enum

class Priority(IntEnum):
    CRITICAL = 10      # 🚨 Production down
    URGENT = 9         # 🔥 Client waiting
    PRIORITIZE = 8     # ⬆️ Upgraded task
    HIGH = 7           # Important
    ABOVE_NORMAL = 6   # Slightly elevated
    NORMAL = 5         # ✅ Default
    BELOW_NORMAL = 4   # Can wait
    LOW = 3            # Background work
    BACKGROUND = 2     # Run when idle
    MAINTENANCE = 1    # Cleanup
    LOWEST = 0         # Only if nothing else

class Category(str, Enum):
    ETL = "etl"
    WEBAPP = "webapp"
    REPORT = "report"
    ALERT = "alert"

class Phase(str, Enum):
    EXTRACT = "extract"
    TRANSFORM = "transform"
    LOAD = "load"
    NONE = "default"

def priority_to_bucket(priority: int) -> str:
    if priority >= 8:
        return "high"
    elif priority >= 4:
        return "normal"
    return "low"

async def dispatch_task(
    task_func,
    args: dict,
    category: Category,
    priority: int = Priority.NORMAL,
    phase: Phase = Phase.NONE,
    correlation_id: str = None
):
    """
    Routes task to appropriate priority subject.
    """
    bucket = priority_to_bucket(priority)
    subject = f"tasks.{category}.{phase}.{bucket}"
    
    await task_func.kicker() \
        .with_broker_subject(subject) \
        .with_labels({
            "category": category,
            "priority": priority,
            "phase": phase,
            "correlation_id": correlation_id,
            "bucket": bucket
        }).kiq(**args)
```

### 2. Priority-Aware Worker

```python
# workers/priority_worker.py
import asyncio
from nats.aio.client import Client as NATS

class PriorityWorker:
    """
    Worker that always processes higher priority tasks first.
    """
    
    def __init__(self, category: str, phase: str):
        self.subjects = [
            f"tasks.{category}.{phase}.high",
            f"tasks.{category}.{phase}.normal",
            f"tasks.{category}.{phase}.low",
        ]
        self.nc = NATS()
    
    async def run(self):
        await self.nc.connect("nats://127.0.0.1:4222")
        
        while True:
            msg = await self._get_highest_priority()
            if msg:
                await self._process(msg)
            else:
                await asyncio.sleep(0.1)
    
    async def _get_highest_priority(self):
        """Check subjects in priority order."""
        for subject in self.subjects:  # high → normal → low
            msg = await self._try_get(subject)
            if msg:
                return msg
        return None
```

### 3. Upgrade Task Priority

```python
# core/upgrade.py
async def upgrade_task(
    task_id: str,
    new_priority: int,
    reason: str = None
):
    """
    Upgrades a pending task to higher priority.
    Works by: mark cancelled → re-queue at higher priority
    """
    # 1. Get original task from audit DB
    original = await get_task_from_audit(task_id)
    if not original:
        raise ValueError(f"Task {task_id} not found")
    
    if original.status != "queued":
        raise ValueError(f"Task already {original.status}")
    
    # 2. Mark as cancelled/upgraded
    await update_audit(
        task_id,
        status="upgraded",
        notes=f"Upgraded to priority {new_priority}: {reason}"
    )
    
    # 3. Re-dispatch with new priority
    await dispatch_task(
        task_func=get_task_func(original.task_name),
        args=original.args,
        category=original.category,
        priority=new_priority,
        phase=original.phase,
        correlation_id=original.correlation_id
    )
    
    return {"success": True, "new_priority": new_priority}
```

### 4. ETL Pipeline with Priority

```python
# pipelines/etl.py
async def run_etl_pipeline(
    source: str,
    destination: str,
    priority: int = Priority.NORMAL,
    urgent: bool = False
):
    job_id = create_job_id("etl")
    
    if urgent:
        priority = Priority.URGENT
    
    # Phase 1: Extract (usually fast)
    await dispatch_task(
        extract_task,
        args={"source": source},
        category=Category.ETL,
        phase=Phase.EXTRACT,
        priority=priority,
        correlation_id=job_id
    )
    
    # Phase 2 & 3 are triggered by completion of previous phase
    # (see event-driven chaining below)
    
    return job_id
```

### 5. Phase Completion → Next Phase

```python
# After extract completes, trigger transform
@broker.subscriber("events.etl.extract.completed")
async def on_extract_completed(event: ExtractCompleted):
    await dispatch_task(
        transform_task,
        args={"data": event.data},
        category=Category.ETL,
        phase=Phase.TRANSFORM,
        priority=event.priority,  # Preserve priority through pipeline
        correlation_id=event.correlation_id
    )
```

---

## Worker Deployment

```bash
# Critical/Urgent worker (priority 8-10)
taskiq worker tasks:broker --pattern "tasks.*.*.high"

# Normal worker (priority 4-7)
taskiq worker tasks:broker --pattern "tasks.*.*.normal"

# Background worker (priority 0-3)
taskiq worker tasks:broker --pattern "tasks.*.*.low"

# Or: Phase-specific workers for bottlenecks
taskiq worker tasks:broker --pattern "tasks.etl.load.*"
```

---

## Dash Dashboard Actions

| Button | Action | Function Called |
|--------|--------|-----------------|
| ⬆️ Upgrade | Boost priority | `upgrade_task(id, new_priority)` |
| ⏸️ Cancel | Stop pending | `cancel_task(id)` |
| 🔄 Retry | Re-run failed | `retry_task(id)` |
| 🚀 Rush | Immediate (priority 10) | `upgrade_task(id, 10)` |

---

## Complexity vs Performance

| Concern | Assessment |
|---------|------------|
| **Complexity** | Medium - 3 bucket approach is simple |
| **Performance** | Good - NATS handles routing, workers poll efficiently |
| **Scalability** | Excellent - add workers per subject as needed |
| **Maintainability** | Good - clear patterns, enum-based config |

### Tradeoffs Made

1. **3 buckets vs 10 levels** → Simpler > Granular
2. **Cancel+re-queue vs in-place update** → Works with any broker
3. **Per-phase subjects** → Adds subjects but enables targeted scaling

---

## Priority History Tracking

Track all priority changes for audit/analytics:

```sql
CREATE TABLE priority_history (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    task_id TEXT,              -- Original task ID (preserved)
    changed_at TEXT,
    from_priority INTEGER,
    to_priority INTEGER,
    from_bucket TEXT,
    to_bucket TEXT,
    action TEXT,               -- 'prioritize', 'urgent', 'critical'
    reason TEXT,
    changed_by TEXT            -- user_id from RBAC
);

-- Index for quick lookups
CREATE INDEX idx_priority_task ON priority_history(task_id);
```

**Query example:**
```sql
SELECT changed_at, from_priority, to_priority, action, reason, changed_by
FROM priority_history 
WHERE task_id = 'etl-20231223-abc123' 
ORDER BY changed_at;
```

---

## Predefined Upgrade Actions

Instead of users picking arbitrary 0-10 values, provide **named actions**:

| Action | Button | Priority | Bucket | Use Case |
|--------|--------|----------|--------|----------|
| **Prioritize** | ⬆️ | 8 | →high | "Do this sooner, jump queue" |
| **Urgent** | 🔥 | 9 | →high | "Client waiting" |
| **Critical** | 🚨 | 10 | →high | "Production issue" |

**Implementation:**
```python
# core/upgrade.py
from enum import Enum

class UpgradeAction(str, Enum):
    PRIORITIZE = "prioritize"  # → priority 8
    URGENT = "urgent"          # → priority 9
    CRITICAL = "critical"      # → priority 10

ACTION_TO_PRIORITY = {
    UpgradeAction.PRIORITIZE: 8,
    UpgradeAction.URGENT: 9,
    UpgradeAction.CRITICAL: 10,
}

async def upgrade_task(
    task_id: str,
    action: UpgradeAction,
    reason: str,
    user_id: str
):
    new_priority = ACTION_TO_PRIORITY[action]
    original = await get_task(task_id)
    
    # Log to priority_history
    await db.execute("""
        INSERT INTO priority_history 
        (task_id, changed_at, from_priority, to_priority, 
         from_bucket, to_bucket, action, reason, changed_by)
        VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
    """, (
        task_id, now(), 
        original.priority, new_priority,
        original.bucket, priority_to_bucket(new_priority),
        action.value, reason, user_id
    ))
    
    # Re-queue with new priority
    await requeue_task(task_id, new_priority)
```

---

## Role-Based Access Control (RBAC)

### Database Schema

```sql
-- Users
CREATE TABLE users (
    user_id TEXT PRIMARY KEY,
    username TEXT UNIQUE,
    email TEXT,
    password_hash TEXT,
    role TEXT,                 -- 'viewer', 'operator', 'manager', 'admin'
    created_at TEXT
);

-- Roles and permissions
CREATE TABLE role_permissions (
    role TEXT,
    permission TEXT,
    PRIMARY KEY (role, permission)
);

-- Insert default permissions
INSERT INTO role_permissions VALUES
    ('viewer', 'view_tasks'),
    ('viewer', 'view_dashboard'),
    ('operator', 'view_tasks'),
    ('operator', 'view_dashboard'),
    ('operator', 'prioritize_tasks'),      -- Can use Prioritize button
    ('manager', 'view_tasks'),
    ('manager', 'view_dashboard'),
    ('manager', 'prioritize_tasks'),
    ('manager', 'urgent_tasks'),           -- Can use Urgent button
    ('manager', 'cancel_tasks'),
    ('admin', 'view_tasks'),
    ('admin', 'view_dashboard'),
    ('admin', 'prioritize_tasks'),
    ('admin', 'urgent_tasks'),
    ('admin', 'critical_tasks'),           -- Can use Critical button
    ('admin', 'cancel_tasks'),
    ('admin', 'manage_users');
```

### Permission Matrix

| Role | View | Prioritize (→8) | Urgent (→9) | Critical (→10) | Cancel | Manage Users |
|------|------|-----------------|-------------|----------------|--------|--------------|
| Viewer | ✅ | ❌ | ❌ | ❌ | ❌ | ❌ |
| Operator | ✅ | ✅ | ❌ | ❌ | ❌ | ❌ |
| Manager | ✅ | ✅ | ✅ | ❌ | ✅ | ❌ |
| Admin | ✅ | ✅ | ✅ | ✅ | ✅ | ✅ |

### Dash Integration

```python
# dashboard/auth.py
from functools import wraps

def require_permission(permission: str):
    def decorator(func):
        @wraps(func)
        def wrapper(*args, **kwargs):
            user = get_current_user()
            if not has_permission(user.role, permission):
                return html.Div("Access Denied", className="error")
            return func(*args, **kwargs)
        return wrapper
    return decorator

# Usage in callbacks
@callback(Output('result', 'children'), Input('urgent-btn', 'n_clicks'))
@require_permission('urgent_tasks')
def make_urgent(n_clicks, task_id):
    if n_clicks:
        return upgrade_task(task_id, UpgradeAction.URGENT, "User request", current_user.id)
```

### Dash UI Based on Role

```python
# dashboard/layout.py
def get_action_buttons(user_role: str, task_id: str):
    buttons = []
    
    if has_permission(user_role, 'prioritize_tasks'):
        buttons.append(html.Button("⬆️ Prioritize", id={'type': 'prioritize', 'task': task_id}))
    
    if has_permission(user_role, 'urgent_tasks'):
        buttons.append(html.Button("🔥 Urgent", id={'type': 'urgent', 'task': task_id}))
    
    if has_permission(user_role, 'critical_tasks'):
        buttons.append(html.Button("🚨 Critical", id={'type': 'critical', 'task': task_id}))
    
    if has_permission(user_role, 'cancel_tasks'):
        buttons.append(html.Button("⏸️ Cancel", id={'type': 'cancel', 'task': task_id}))
    
    return html.Div(buttons)
```

---

## Updated Dashboard Actions

| Button | Permission Required | Action | Priority |
|--------|---------------------|--------|----------|
| ⬆️ Prioritize | `prioritize_tasks` | `upgrade_task(id, PRIORITIZE, reason, user)` | →8 |
| 🔥 Urgent | `urgent_tasks` | `upgrade_task(id, URGENT, reason, user)` | →9 |
| 🚨 Critical | `critical_tasks` | `upgrade_task(id, CRITICAL, reason, user)` | →10 |
| ⏸️ Cancel | `cancel_tasks` | `cancel_task(id)` | N/A |
| 🔄 Retry | `prioritize_tasks` | `retry_task(id)` | Original |

---

## Updated Files to Create

```
msg_sys/
├── core/
│   ├── dispatcher.py      # Smart routing
│   ├── priority.py        # Enums (Priority, UpgradeAction)
│   ├── upgrade.py         # Priority upgrade + history logging
│   └── middleware.py      # Audit with priority tracking
├── workers/
│   ├── priority_worker.py # Priority-aware consumer
│   └── phase_workers.py   # ETL phase-specific workers
├── pipelines/
│   └── etl.py             # ETL pipeline orchestration
├── dashboard/
│   ├── app.py             # Dash main app
│   ├── auth.py            # RBAC decorators
│   ├── layout.py          # Role-aware UI components
│   └── actions.py         # Upgrade/cancel callbacks
└── db/
    ├── audit.db           # Task audit + priority_history
    └── users.db           # RBAC tables (users, permissions)
```

---

## Recommendation

**Start with:**
1. ✅ 3-bucket priority system (high/normal/low)
2. ✅ Priority value 0-10 stored in audit for analytics
3. ✅ Priority history table for change tracking
4. ✅ Predefined actions (Prioritize/Urgent/Critical)
5. ✅ RBAC skeleton (users + role_permissions tables)

**Add later (if needed):**
- Custom priority worker (for fine-grained control)
- Per-phase workers for bottlenecks
- Advanced RBAC (page-level permissions, audit log for auth)
