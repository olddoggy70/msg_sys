# ============================================================
# agent.py  —  full async agent: perceive → decide → act → remember → loop
# ============================================================
from enum import Enum
from dataclasses import dataclass, field
import aiosqlite
import taskiq
from faststream.nats import NatsBroker
from pydantic import BaseModel

# ── 1. Types ────────────────────────────────────────────────

class Action(Enum):
    ESCALATE = "escalate"
    RETRY    = "retry"
    DONE     = "done"

ACTION_SUBJECT = {                          # Action → NATS subject
    Action.ESCALATE: "events.escalate",
    Action.RETRY:    "events.retry",
    Action.DONE:     "events.done",
}

class MyEvent(BaseModel):
    key: str
    payload: dict

@dataclass
class AgentState:
    retries:     int  = 0
    last_result: str  = ""
    status:      str  = "idle"
    results:     list = field(default_factory=list)

# ── 2. Infrastructure ────────────────────────────────────────

broker = NatsBroker("nats://localhost:4222")
DB_PATH = "agent_state.db"

async def load_state(key: str) -> AgentState:
    async with aiosqlite.connect(DB_PATH) as db:
        db.row_factory = aiosqlite.Row
        async with db.execute(
            "SELECT * FROM agent_state WHERE key = ?", [key]
        ) as cur:
            row = await cur.fetchone()
            if row is None:
                return AgentState()
            return AgentState(
                retries     = row["retries"],
                last_result = row["last_result"],
                status      = row["status"],
            )

async def update_state(key: str, patch: dict) -> None:
    async with aiosqlite.connect(DB_PATH) as db:
        await db.execute(
            """INSERT INTO agent_state (key, retries, last_result, status)
               VALUES (:key, :retries, :last_result, :status)
               ON CONFLICT(key) DO UPDATE SET
                 retries=excluded.retries,
                 last_result=excluded.last_result,
                 status=excluded.status""",
            {"key": key, **patch},
        )
        await db.commit()

# ── 3. Brain (pure, no side-effects, easy to unit-test) ─────

async def decide(msg: MyEvent, state: AgentState) -> list[Action]:
    if state.retries > 3:
        return [Action.ESCALATE]
    if state.last_result == "incomplete":
        return [Action.RETRY]
    return [Action.DONE]

# ── 4. Dispatch (Taskiq task + NATS loop-back) ───────────────

@taskiq.task
async def run_task(msg_dict: dict) -> str:
    # your actual business logic here
    return "incomplete"             # or "done", "failed", …

async def dispatch(action: Action, msg: MyEvent) -> str:
    task   = await run_task.kiq(msg.model_dump())   # Taskiq async kick
    result = await task.wait_result(timeout=30)      # wait or fire-and-forget
    subject = ACTION_SUBJECT[action]
    await broker.publish(msg, subject)               # loop-back → next cycle
    return result.return_value

# ── 5. Subscriber (the agent loop) ───────────────────────────

@broker.subscriber("events.input")
async def handler(msg: MyEvent) -> None:

    # PERCEIVE — load memory from SQLite
    state = await load_state(msg.key)

    # DECIDE — brain isolated, returns typed Actions
    actions = await decide(msg, state)

    # PRE-ACT — persist intent before dispatch (crash-safe)
    await update_state(msg.key, {
        "retries":     state.retries,
        "last_result": state.last_result,
        "status":      "dispatching",
    })

    # ACT — dispatch each action, record outcome
    results = []
    for action in actions:
        try:
            outcome = await dispatch(action, msg)
            results.append({"action": action.value, "status": "ok", "outcome": outcome})
        except Exception as e:
            results.append({"action": action.value, "status": "failed", "error": str(e)})
            await broker.publish(msg, "events.dead_letter")   # dead-letter on failure

    # REMEMBER — post-dispatch write with real outcome
    await update_state(msg.key, {
        "retries":     state.retries + 1,
        "last_result": results[-1]["outcome"] if results else "failed",
        "status":      "done",
    })
    # loop-back is inside dispatch() → publish to next subject
```

The structure in one picture:
```
events.input
     │
     ▼
 handler()          ← FastStream @subscriber (the agent shell)
     │
     ├─ load_state()         PERCEIVE  — SQLite read
     ├─ decide()             DECIDE    — pure fn, no I/O, returns Action enum
     ├─ update_state(intent) PRE-ACT   — crash-safe intent write
     │
     └─ for action in actions:
           dispatch()        ACT       — Taskiq kick + NATS publish (loop-back)
              └─ on error → events.dead_letter
     │
     └─ update_state(result) REMEMBER  — post-dispatch outcome write
