# msg_sys Architecture Guide

**Universal Message System for ETL, Reports, Events, and Web Apps**  
*Using Taskiq + NATS JetStream + FastStream + SQLite*

---

## 🎯 System Overview

```
┌──────────────────────────────────────────────────────┐
│            msg_sys (Universal Layer)                 │
├──────────────────────────────────────────────────────┤
│  ┌────────────┐  ┌────────────┐  ┌────────────┐    │
│  │  Taskiq    │  │ FastStream │  │  SQLite    │    │
│  │(Workers)   │  │(Events)    │  │(Audit)     │    │
│  └─────┬──────┘  └─────┬──────┘  └─────┬──────┘    │
│        └────────────────┴───────────────┘            │
│                    NATS JetStream                    │
│            (Persistence + Streaming)                 │
└──────────────────────────────────────────────────────┘
```

**Components:**
- **Taskiq**: Background task queue (pull model)
- **FastStream**: Event-driven handlers (push model)
- **NATS JetStream**: Message broker with persistence
- **SQLite**: Audit trail and task history

---

## ✅ Core Recommendations

### 1. Enable NATS JetStream from Day 1

**nats-server.conf:**
```conf
# NATS Server Configuration
host: 0.0.0.0
port: 4222

# Enable JetStream (required for persistence)
jetstream {
    store_dir: "./nats-data"
    max_memory_store: 1GB
    max_file_store: 10GB
}

# Monitoring
http: 8222

# Logging
debug: true
trace: false
logtime: true
log_file: "./logs/nats-server.log"

# Limits
max_connections: 100
max_payload: 1MB
max_pending: 64MB
```

**Why JetStream?**
- Message persistence (survive restarts)
- Replay capability (reprocess messages)
- Exactly-once delivery (critical for ETL)
- Stream analytics

---

### 2. Taskiq Middleware for Audit Logging

**audit_middleware.py:**
```python
import sqlite3
from datetime import datetime
from taskiq import TaskiqMiddleware
from typing import Optional

class AuditMiddleware(TaskiqMiddleware):
    """
    Tracks task lifecycle: start, completion, errors, duration.
    Stores in SQLite for audit trail and forensics.
    """
    
    def __init__(self, db_path='audit.db'):
        self.db_path = db_path
        self._init_db()
    
    def _init_db(self):
        """Initialize audit table"""
        with sqlite3.connect(self.db_path) as conn:
            conn.execute("""
                CREATE TABLE IF NOT EXISTS task_audit (
                    task_id TEXT PRIMARY KEY,
                    task_name TEXT,
                    status TEXT,
                    args TEXT,
                    started_at TEXT,
                    ended_at TEXT,
                    duration_ms REAL,
                    error TEXT,
                    retry_count INTEGER DEFAULT 0
                )
            """)
            # Index for common queries
            conn.execute("CREATE INDEX IF NOT EXISTS idx_started_at ON task_audit(started_at)")
            conn.execute("CREATE INDEX IF NOT EXISTS idx_status ON task_audit(status)")
    
    async def pre_execute(self, message):
        """Called before task execution"""
        with sqlite3.connect(self.db_path) as conn:
            conn.execute("""
                INSERT INTO task_audit (task_id, task_name, status, args, started_at) 
                VALUES (?, ?, ?, ?, ?)
            """, (
                message.task_id,
                message.task_name,
                'started',
                str(message.args),
                datetime.now().isoformat()
            ))
        return message
    
    async def post_execute(self, message, result):
        """Called after successful task execution"""
        with sqlite3.connect(self.db_path) as conn:
            # Calculate duration
            start = conn.execute(
                "SELECT started_at FROM task_audit WHERE task_id=?", 
                (message.task_id,)
            ).fetchone()
            
            if start:
                start_time = datetime.fromisoformat(start[0])
                duration = (datetime.now() - start_time).total_seconds() * 1000
            else:
                duration = None
            
            conn.execute("""
                UPDATE task_audit 
                SET status=?, ended_at=?, duration_ms=? 
                WHERE task_id=?
            """, ('completed', datetime.now().isoformat(), duration, message.task_id))
        return result
    
    async def on_error(self, message, exc: Exception):
        """Called when task fails"""
        with sqlite3.connect(self.db_path) as conn:
            conn.execute("""
                UPDATE task_audit 
                SET status=?, ended_at=?, error=?, retry_count=retry_count+1 
                WHERE task_id=?
            """, (
                'failed',
                datetime.now().isoformat(),
                str(exc),
                message.task_id
            ))
```

**Usage:**
```python
from taskiq_nats import NatsBroker
from audit_middleware import AuditMiddleware

broker = NatsBroker(["nats://127.0.0.1:4222"])
broker.add_middlewares(AuditMiddleware(db_path='audit.db'))
```

---

### 3. Subject/Channel Organization

Use NATS subjects to separate concerns:

```python
# ETL Jobs (long-running, retriable)
"etl.extract.salesforce"
"etl.transform.dedupe"
"etl.load.warehouse"

# Reports (scheduled, resource-intensive)
"reports.daily.sales"
"reports.monthly.finance"
"reports.weekly.analytics"

# Events (real-time, reactive)
"events.user.registered"
"events.order.placed"
"events.payment.completed"

# Web App Tasks (user-triggered, async)
"webapp.email.send"
"webapp.image.resize"
"webapp.video.transcode"
```

**Benefits:**
- ✅ Clear separation of concerns
- ✅ Easy monitoring per domain
- ✅ Selective worker subscriptions
- ✅ Scale specific domains independently

---

### 4. Task vs Event Pattern

**Use Taskiq Tasks (Pull Model):**
```python
@broker.task
async def generate_monthly_report(month: str):
    """
    Long-running, retriable, needs audit trail.
    Triggered on-demand or via scheduler.
    """
    data = await fetch_data(month)
    report = await create_report(data)
    await save_to_s3(report)
    return report
```

**Use FastStream Events (Push Model):**
```python
@broker.subscriber("events.user.registered")
async def on_user_registered(user_id: int):
    """
    React immediately to events.
    Fire-and-forget or trigger other tasks.
    """
    await send_welcome_email(user_id)
    await create_user_profile(user_id)
```

**Decision Matrix:**

| Characteristic | Use Taskiq Task | Use FastStream Event |
|----------------|-----------------|----------------------|
| Initiated by | Code/Scheduler | Another service |
| Response needed? | Often yes | Usually no |
| Retry logic | Important | Nice-to-have |
| Duration | Minutes+ | Seconds |
| Examples | ETL, Reports | Webhooks, Notifications |

---

### 5. Recommended Project Structure

```
msg_sys/
├── core/
│   ├── __init__.py
│   ├── broker.py           # Shared NATS broker config
│   ├── middleware.py       # Audit + retry logic
│   └── config.py           # Environment settings
│
├── tasks/
│   ├── __init__.py
│   ├── etl.py              # ETL Taskiq tasks
│   ├── reports.py          # Report generation
│   └── webapp.py           # Web app background jobs
│
├── events/
│   ├── __init__.py
│   ├── handlers.py         # FastStream event handlers
│   └── schemas.py          # Pydantic event models
│
├── audit/
│   ├── __init__.py
│   ├── db.py               # SQLite audit operations
│   └── queries.py          # Audit queries/reports
│
├── scheduler.py            # Cron/scheduled tasks
├── worker.py               # Worker entry point
├── app.py                  # FastStream app
├── pyproject.toml
└── start.bat               # Local development launcher
```

---

### 6. Environment-Aware Configuration

**core/config.py:**
```python
from pydantic_settings import BaseSettings
from typing import Optional

class Settings(BaseSettings):
    # NATS
    nats_url: str = "nats://127.0.0.1:4222"
    
    # Audit
    audit_db: str = "audit.db"
    
    # Logging
    log_level: str = "INFO"
    
    # ETL-specific
    etl_retry_count: int = 3
    etl_retry_delay: int = 60  # seconds
    
    # Report-specific
    report_output_dir: str = "./reports"
    
    # Environment
    environment: str = "development"  # development, staging, production
    
    class Config:
        env_file = ".env"

settings = Settings()
```

**.env (development):**
```bash
NATS_URL=nats://127.0.0.1:4222
AUDIT_DB=dev_audit.db
LOG_LEVEL=DEBUG
ENVIRONMENT=development
```

**.env.production:**
```bash
NATS_URL=nats://nats-cluster.prod.internal:4222
AUDIT_DB=/var/lib/msg_sys/audit.db
LOG_LEVEL=INFO
ENVIRONMENT=production
```

---

### 7. Type-Safe Task Parameters

**Use Pydantic models for task inputs:**

```python
from pydantic import BaseModel, Field
from datetime import datetime
from typing import Optional

class ETLConfig(BaseModel):
    source: str = Field(..., description="Data source identifier")
    destination: str = Field(..., description="Target location")
    batch_size: int = Field(1000, ge=1, le=10000)
    start_date: Optional[datetime] = None
    end_date: Optional[datetime] = None

@broker.task
async def etl_job(config: ETLConfig):
    """
    Type-safe! Pydantic validates on entry.
    Auto-generates OpenAPI docs.
    """
    for batch in fetch_batches(
        config.source, 
        config.batch_size,
        config.start_date,
        config.end_date
    ):
        await process_batch(batch)
        await save_to(config.destination, batch)
```

---

## ⚠️ Pitfalls to Avoid

### 1. Don't Mix Fast and Slow Tasks in Same Worker

**❌ Bad:**
```python
# Same worker handles both
@broker.task
async def quick_email():  # 100ms
    await send_email()

@broker.task
async def huge_etl_job():  # 30 minutes
    await process_millions_of_rows()
```

**Problem:** Quick tasks get blocked behind slow ones.

**✅ Good:**
```python
# Separate workers by task type
# Start workers with subject filtering:

# Terminal 1: Fast worker
taskiq worker tasks:broker --subjects "webapp.*,events.*"

# Terminal 2: ETL worker
taskiq worker tasks:broker --subjects "etl.*,reports.*"
```

---

### 2. Always Design for Idempotency

Tasks may retry—ensure safe re-execution:

```python
@broker.task
async def process_payment(order_id: str):
    # ❌ Bad: May double-charge on retry
    await charge_card(order_id)
    
    # ✅ Good: Check state first
    if await is_already_charged(order_id):
        return {"status": "already_processed"}
    
    result = await charge_card(order_id)
    await mark_as_charged(order_id)
    return result
```

---

### 3. Monitor SQLite Audit DB Growth

Your audit DB will grow. Plan for:

**Archival Script (monthly cron):**
```python
# archive_audit.py
import sqlite3
from datetime import datetime, timedelta

def archive_old_records(days_to_keep=90):
    cutoff = datetime.now() - timedelta(days=days_to_keep)
    
    with sqlite3.connect('audit.db') as conn:
        # Export old records
        old_records = conn.execute(
            "SELECT * FROM task_audit WHERE started_at < ?",
            (cutoff.isoformat(),)
        ).fetchall()
        
        # Save to archive file/S3
        save_to_archive(old_records)
        
        # Delete from main DB
        conn.execute(
            "DELETE FROM task_audit WHERE started_at < ?",
            (cutoff.isoformat(),)
        )
        
        # VACUUM to reclaim space
        conn.execute("VACUUM")
```

---

## 🚀 Quick Wins

### 1. Dead Letter Queue Pattern

```python
@broker.task(retry=3, retry_delay=60)
async def risky_task(data):
    try:
        result = await process(data)
        return result
    except Exception as e:
        # After 3 retries, send to DLQ
        if get_retry_count() >= 3:
            await publish_to_dlq("risky_task", data, error=str(e))
        raise
```

---

### 2. Task Result Storage

```python
# For expensive computations
from taskiq import TaskiqResult

@broker.task
async def expensive_calculation(params):
    result = await compute(params)
    
    # Store in Redis/SQLite for caching
    await cache.set(f"calc:{params}", result, ttl=3600)
    
    return result

# Retrieve results later
async def get_or_compute(params):
    cached = await cache.get(f"calc:{params}")
    if cached:
        return cached
    
    # Kick off task if not cached
    task = await expensive_calculation.kiq(params)
    result = await task.wait_result()
    return result
```

---

### 3. Task Composition (Pipelines)

```python
from taskiq import gather

@broker.task
async def extract_data(source):
    return await fetch(source)

@broker.task
async def transform_data(data):
    return await clean(data)

@broker.task
async def load_data(data, destination):
    await save(data, destination)

# Compose into pipeline
async def etl_pipeline(source, destination):
    data = await extract_data.kiq(source)
    data = await data.wait_result()
    
    transformed = await transform_data.kiq(data)
    transformed = await transformed.wait_result()
    
    await load_data.kiq(transformed, destination)
```

---

## 📚 Implementation Timeline

### Week 1-2: Foundation
- [x] Set up NATS with JetStream
- [x] Create core broker configuration
- [ ] Implement audit middleware
- [ ] Create project structure
- [ ] Add configuration management

### Week 3: First Use Case (ETL)
- [ ] Build one ETL job with Taskiq
- [ ] Test audit trail
- [ ] Verify retry logic
- [ ] Add monitoring

### Week 4: Event Handlers
- [ ] Add FastStream app
- [ ] Create event subscribers
- [ ] Test pub/sub patterns
- [ ] Integrate with tasks (event → task trigger)

### Week 5: Scheduling
- [ ] Add scheduler for reports
- [ ] Create cron jobs
- [ ] Test scheduled task execution

### Week 6: Production Readiness
- [ ] Load testing (simulate 1000s of tasks)
- [ ] Set up monitoring dashboards
- [ ] Document deployment procedures
- [ ] Create runbooks for common issues

---

## 🔧 Observability Stack

### Logs
```python
import structlog

logger = structlog.get_logger()

@broker.task
async def my_task(data):
    logger.info("task_started", task="my_task", data_size=len(data))
    result = await process(data)
    logger.info("task_completed", task="my_task", result_count=len(result))
    return result
```

### Metrics
- **NATS Monitoring**: `http://localhost:8222`
- **Custom Metrics**: Track task counts, durations, error rates in audit DB

### Audit Queries
```sql
-- Tasks by status (last 24h)
SELECT status, COUNT(*) 
FROM task_audit 
WHERE started_at > datetime('now', '-1 day')
GROUP BY status;

-- Average duration by task type
SELECT task_name, AVG(duration_ms) as avg_ms
FROM task_audit
WHERE status='completed'
GROUP BY task_name
ORDER BY avg_ms DESC;

-- Failure rate by task
SELECT 
    task_name,
    COUNT(*) as total,
    SUM(CASE WHEN status='failed' THEN 1 ELSE 0 END) as failures,
    ROUND(100.0 * SUM(CASE WHEN status='failed' THEN 1 ELSE 0 END) / COUNT(*), 2) as failure_rate
FROM task_audit
GROUP BY task_name
HAVING total > 10
ORDER BY failure_rate DESC;
```

---

## 🚀 Deployment Strategy

### Phase 1: Local Development (Current)
```bash
# Single machine, local binaries
./start.bat
```

### Phase 2: Single Server Production
```bash
# systemd services (Linux)
sudo systemctl start nats
sudo systemctl start msg_sys-worker
sudo systemctl start msg_sys-events
sudo systemctl start msg_sys-scheduler
```

### Phase 3: Distributed (Future)
- NATS cluster (3+ nodes for HA)
- Multiple worker machines by domain
- Load balancer for FastStream apps
- PostgreSQL for audit (replace SQLite)
- Centralized logging (ELK/Grafana Loki)

---

## 📖 Additional Resources

- **Taskiq Docs**: https://taskiq-python.github.io/
- **NATS Docs**: https://docs.nats.io/
- **FastStream Docs**: https://faststream.airt.ai/
- **JetStream Guide**: https://docs.nats.io/nats-concepts/jetstream

---

## 🎓 Key Takeaways

1. **Separation of Concerns**: Tasks (pull) vs Events (push)
2. **Always Audit**: Middleware makes this automatic
3. **Type Safety**: Pydantic everywhere
4. **Idempotency**: Design for retries from day 1
5. **Subject Organization**: Namespace by domain
6. **Scale Gradually**: Start simple, add complexity as needed

---

**Next Steps:**
1. Implement audit middleware
2. Create one working ETL example
3. Test end-to-end with FastStream event
4. Measure and optimize

Good luck building your universal msg_sys! 🚀
