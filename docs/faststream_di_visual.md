# FastStream Dependency Injection - Visual Guide

## Message Flow with DI Concepts

```
MESSAGE ARRIVES → HANDLER EXECUTION → MESSAGE COMPLETED
     ↓                    ↓                    ↓
     
┌────────────────────────────────────────────────────────┐
│  LIFESPAN (runs once at app start/stop)                │
│  ┌──────────────────────────────────────────────────┐  │
│  │ @app.on_startup  →  Creates DB pool, cache, etc │  │
│  └──────────────────────────────────────────────────┘  │
└────────────────────────────────────────────────────────┘
                         ↓
┌────────────────────────────────────────────────────────┐
│  PER MESSAGE EXECUTION                                  │
│                                                         │
│  1. Depends() functions run                             │
│     ├─ get_config() → returns config                   │
│     ├─ get_database() → returns db connection          │
│     └─ get_session() → yields session (cleanup later)  │
│                                                         │
│  2. Handler executes with injected dependencies         │
│     @broker.subscriber("topic")                         │
│     async def handler(                                  │
│         msg: dict,                                      │
│         config=Depends(get_config),  ← Injected        │
│         logger: Logger,              ← Auto-injected   │
│         topic=Context("message.topic") ← Extracted     │
│     ):                                                  │
│         logger.info(f"Processing {topic}")             │
│         # ... your logic ...                            │
│                                                         │
│  3. Cleanup runs (if dependency used yield)             │
│     ├─ get_session() cleanup code executes             │
│     └─ Resources released                               │
└────────────────────────────────────────────────────────┘
                         ↓
┌────────────────────────────────────────────────────────┐
│  SCOPE DETERMINES REUSE                                 │
│                                                         │
│  Per-message scope: Steps 1-3 repeat for EACH message  │
│  Singleton scope: Reuse same instance across messages   │
└────────────────────────────────────────────────────────┘
```

## Concepts Summary Table

| Concept | Purpose | When to Use | Example |
|---------|---------|-------------|---------|
| **Depends()** | Inject custom dependencies | DB connections, services, config, business logic | `config=Depends(get_config)` |
| **Context()** | Access message metadata | Need message info (topic, offset, headers) or broker instance | `topic=Context("message.topic")` |
| **Logger** | Pre-configured structured logger | Logging/debugging - Always use this instead of print() | `logger: Logger` |
| **Lifespan** | Application startup/shutdown | One-time setup: DB pools, cache clients, load configs | `@app.on_startup` |
| **Scope** | Control dependency lifetime | Performance: Expensive resources = singleton, Cheap = per-message | Singleton pattern or factory functions |

## Dependency Features Comparison

### Depends()
- ✅ Can be sync or async
- ✅ Can have cleanup (yield pattern)
- ✅ Can be nested (dependencies of dependencies)
- ✅ Called per message (default) or singleton
- ⚠️ Requires explicit `Depends()` wrapper

### Context()
- ✅ Direct access to message metadata
- ✅ No function calls needed
- ✅ Type-safe with annotations
- ⚠️ Limited to message/broker context only

### Logger
- ✅ Automatically injected (no Depends needed)
- ✅ Pre-configured with structured logging
- ✅ Includes context automatically
- ✅ Just type hint: `logger: Logger`

### Lifespan
- ✅ Runs exactly once at startup/shutdown
- ✅ Perfect for expensive initialization
- ✅ Shared across all messages
- ⚠️ Not per-message, global only

## Real-World Example

```python
from faststream import FastStream, Depends, Context, Logger
from faststream.kafka import KafkaBroker
from typing import Annotated

# ============= SINGLETON (created once) =============
class DatabasePool:
    _instance = None
    def __new__(cls):
        if cls._instance is None:
            cls._instance = super().__new__(cls)
            print("✓ Created DB pool (singleton)")
        return cls._instance

# ============= PER-MESSAGE (created each time) =============
async def get_user_repository(db=Depends(DatabasePool)):
    """New repository instance per message"""
    return UserRepository(db)

async def get_config():
    """Load config per message"""
    return {"api_key": "secret", "timeout": 30}

# ============= SETUP =============
broker = KafkaBroker("localhost:9092")
app = FastStream(broker)

# ============= LIFESPAN =============
@app.on_startup
async def init():
    """Runs once when app starts"""
    print("🚀 App starting - initialize resources")
    
@app.on_shutdown
async def cleanup():
    """Runs once when app stops"""
    print("🛑 App stopping - cleanup resources")

# ============= HANDLER USING ALL CONCEPTS =============
@broker.subscriber("user_events")
async def process_user_event(
    event: dict,
    
    # 1. AUTO-INJECTED LOGGER (no Depends needed)
    logger: Logger,
    
    # 2. DEPENDS - Custom dependency
    repo=Depends(get_user_repository),
    config=Depends(get_config),
    
    # 3. CONTEXT - Message metadata
    topic: Annotated[str, Context("message.topic")],
    partition: Annotated[int, Context("message.partition")],
    offset: Annotated[int, Context("message.offset")]
):
    """
    Execution flow:
    1. get_config() runs → config injected
    2. DatabasePool() returns singleton → db injected
    3. get_user_repository(db) runs → repo injected
    4. Handler executes with all dependencies
    5. Logger automatically has context
    """
    
    logger.info(
        f"Processing event from {topic}:{partition}@{offset}",
        extra={"event_id": event.get("id")}
    )
    
    # Use injected dependencies
    if config["api_key"]:
        user = await repo.get_user(event["user_id"])
        await repo.update(user)
    
    logger.info("Event processed successfully")
```

## Lifecycle Timeline

```
APP START
  │
  ├─> @app.on_startup runs (ONCE)
  │   └─> Initialize DB pool, cache, etc.
  │
  ├─> App ready, waiting for messages...
  │
MESSAGE 1 ARRIVES
  │
  ├─> Depends() functions run
  │   ├─> get_config() → new instance
  │   ├─> DatabasePool() → reuses singleton
  │   └─> get_user_repository() → new instance
  │
  ├─> Handler executes
  │   └─> Uses: logger, repo, config, topic, partition
  │
  └─> Cleanup (if dependencies used yield)
  
MESSAGE 2 ARRIVES
  │
  ├─> Depends() functions run AGAIN
  │   ├─> get_config() → new instance (per-message)
  │   ├─> DatabasePool() → reuses singleton (same as before)
  │   └─> get_user_repository() → new instance (per-message)
  │
  ├─> Handler executes
  │
  └─> Cleanup
  
...more messages...

APP SHUTDOWN
  │
  └─> @app.on_shutdown runs (ONCE)
      └─> Close connections, cleanup resources
```

## Quick Decision Guide

**Need to inject something?**
- Is it message metadata (topic, offset, headers)? → Use `Context()`
- Is it logging? → Use `Logger` type hint
- Is it custom logic/service? → Use `Depends()`

**When to create the dependency?**
- Once at startup? → Use `@app.on_startup` + singleton pattern
- Once per message? → Use `Depends()` with regular function
- Share across messages? → Use singleton pattern in `Depends()`

**Need cleanup after handler?**
- Yes → Use `yield` in dependency function
- No → Use regular `return` in dependency function

## Common Patterns

### Pattern 1: Database Session with Cleanup
```python
async def get_db_session():
    session = await db.create_session()
    try:
        yield session  # Provide to handler
    finally:
        await session.close()  # Always cleanup

@broker.subscriber("topic")
async def handler(msg: dict, session=Depends(get_db_session)):
    await session.execute(...)
    # session.close() called automatically after this
```

### Pattern 2: Shared Connection Pool
```python
class RedisPool:
    _instance = None
    def __new__(cls):
        if cls._instance is None:
            cls._instance = super().__new__(cls)
        return cls._instance

@broker.subscriber("topic")
async def handler(msg: dict, redis=Depends(RedisPool)):
    # Same redis instance for all messages
    await redis.set(key, value)
```

### Pattern 3: Nested Dependencies
```python
async def get_db():
    return Database()

async def get_user_repo(db=Depends(get_db)):
    return UserRepository(db)

async def get_user_service(repo=Depends(get_user_repo)):
    return UserService(repo)

@broker.subscriber("topic")
async def handler(msg: dict, service=Depends(get_user_service)):
    # All nested dependencies resolved automatically
    await service.process(msg)
```

---

**Key Takeaway**: FastStream's DI is simpler than full-featured containers (like Dishka), but these 5 concepts cover 90% of use cases elegantly!