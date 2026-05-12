# TaskIQ Monitor

A high-performance, real-time dashboard for NATS-backed TaskIQ workers, featuring a deeply integrated SQLite WAL backend for persistent historical queries and real-time NATS JetStream telemetry using WebSockets.


## Features

- **Real-time WebSockets:** Pushes task and broker events down to Dash Mantine components using a `dcc.Store` architecture, bypassing Dash's standard 1-second interval limits.
- **SQLite WAL:** High-concurrency background SQLite writers maintain full task state natively without locking the frontend read-replica queries.
- **NATS Telemetry:** Fully instrumented NATS JetStream metrics (Broker connections, CPU, memory, stream lag, and redelivery tracking to detect poison messages).
- **Priority Routing:** 3-bucket priority system (high/normal/low) with per-message subject routing via `PriorityNatsBroker`.
- **Tree Task Model:** Hierarchical SYSTEM → STAGE → TASK tree with bubble-up completion tracking.
- **Dead Letter Queue:** Automated DLQ with configurable retry limits and dashboard replay.
- **Mantine v7 UI:** Fully modernized `dash-mantine-components` UI with glassmorphism, responsive grids, and AG-Grid.

## Setup & Installation

This project utilizes `uv` for lightning-fast dependency management.

1. **Install NATS Server**: Download the `nats-server` binary and ensure it is in your PATH.
2. **Sync Dependencies**:
   ```bash
   uv sync
   ```

## Running the Application

A single startup script is provided to boot the entire stack in the correct dependency order.

```bash
.\start.bat
```

The script will launch four separate command windows:
1. **NATS Server:** Boots on `nats://localhost:4222` and enables the HTTP monitor on `:8222`.
2. **TaskIQ Monitor:** The FastAPI + Dash web application (`http://localhost:8050`).
3. **TaskIQ Worker:** The background worker executing your Python functions.
4. **TaskIQ Scheduler:** The cron scheduler pushing periodic tasks.

## Configuration

All connection strings are centralized in `core/config.py` and can be overridden via environment variables:

```bash
set NATS_URL=nats://your-nats-host:4222
set DB_PATH=db/results.sqlite
```

## Architecture

```mermaid
graph TD
    A[TaskIQ Scheduler] -->|Enqueues Tasks| B[NATS JetStream]
    C[FastAPI Backend /api/actions] -->|Manual Trigger Only| B
    B -->|Consumes Tasks| D[TaskIQ Worker]
    
    D -->|Executes & Logs| E[(SQLite WAL db/results.sqlite)]
    
    D -->|taskiq.events.>| F[NATS Event Bus]
    D -->|taskiq.workers.presence| F
    
    F -->|Polled Async| G[FastAPI NATS Poller Thread]
    G -->|Updates In-Memory| H[StateStore]
    G -->|Updates Running State| E
    
    H -->|Pushes JSON| I[WebSockets /ws/tasks & /ws/broker]
    E -->|Queried by REST| J[REST /api/tasks]
    
    I -->|dcc.Store| K[Dash UI (Mantine Components)]
    J -->|HTTP GET| K
```

> **Note:** The `FastAPI Backend /api/actions` path is the manual trigger endpoint (`POST /api/actions/tasks/enqueue`) used for dashboard testing. In normal operation, only the Scheduler and application code enqueue tasks.

## Directory Structure

```
taskiq_monitor/
├── core/                    # Shared domain logic
│   ├── config.py            # Centralized NATS_URL, DB_PATH
│   ├── broker.py            # FastStream broker + stream definitions
│   ├── messages.py          # Pydantic event models
│   ├── priority.py          # Priority enums + bucket mapping
│   ├── dispatcher.py        # Task routing + registration
│   ├── kv.py                # NATS KV helpers (state + cancel)
│   ├── exceptions.py        # SoftCancelException etc.
│   ├── app_state.py         # Task function registry
│   ├── upgrade.py           # Task upgrade logic
│   ├── replay.py            # Task replay logic
│   └── nats_setup.py        # Stream provisioning
├── workers/                 # TaskIQ workers + middleware
│   ├── __init__.py          # AppState task registry
│   ├── broker.py            # PriorityNatsBroker + middleware chain
│   ├── result_backend.py    # SQLiteResultBackend (task_results table)
│   ├── monitor_middleware.py # Heartbeats + task lifecycle events → NATS
│   ├── middleware.py        # SoftCancelMiddleware
│   ├── dlq_middleware.py    # DLQMiddleware (dead letter queue)
│   ├── demo_tasks.py        # Demo tasks (add, random_job, etc.)
│   ├── scheduler.py         # TaskiqScheduler config
│   ├── system_worker.py     # SYSTEM coordinator
│   ├── stage_worker.py      # STAGE coordinator
│   ├── load_worker.py       # Leaf task definitions
│   ├── state_worker.py      # Bubble-up completion logic
│   ├── calendar_poller.py   # SQLite-driven cron scheduler
│   └── safety_net.py        # Stuck task scanner
├── monitor/                 # Dashboard
│   ├── main.py              # FastAPI + Dash application
│   ├── nats_poller.py       # Background NATS listener thread
│   ├── state_store.py       # Thread-safe in-memory state
│   ├── routers/             # REST API endpoints
│   └── dash_app/            # Dash Mantine UI + AG-Grid
├── app/                     # FastStream event processor
│   └── main.py              # Event subscriber for tree bubble-up
├── db/                      # SQLite schema + repository
│   ├── repository.py        # TaskRepository (async wrapper)
│   └── migrations/          # Schema migrations
├── tests/                   # Test suites
│   ├── test_milestone_9_e2e.py
│   └── milestones/          # Historical milestone verification scripts
├── docs/                    # Architecture docs + walkthroughs
├── scratch/                 # Throwaway scripts (gitignored)
├── pyproject.toml
├── start.bat
├── nats-server.conf
└── README.md
```
