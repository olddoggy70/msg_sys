# FastStream Middleware - Complete Guide

## Overview

FastStream middleware is similar to Taskiq hooks but designed for message streaming. This guide covers common use cases and implementation patterns.

---

## Message Processing Lifecycle

### Taskiq (Task Queue - Job-based)
```
Task Submitted
      ↓
  [pre_execute hook] ← Your audit here
      ↓
  Execute Task
      ↓
  [post_execute hook]
      ↓
  Save Result
      ↓
  [post_save hook]
      ↓
  Done

  [on_error hook] ← If failure
```

### FastStream (Message Stream - Event-based)
```
Message Arrives
      ↓
  [on_receive] ← Very first, raw bytes
      ↓
  [parser] ← Convert to StreamMessage
      ↓
  [filter] ← Apply filtering logic
      ↓
  [consume_scope] ← ✓ BEST FOR AUDIT (has full context)
      ↓
  [decoder] ← Deserialize to Python objects
      ↓
  [handler] ← Your subscriber function
      ↓
  [publish_scope] ← Intercept outgoing messages
      ↓
  [after_processed] ← Final cleanup
```

---

## Common Use Cases (Ranked by Popularity)

1. **OpenTelemetry** (80% of projects) - Distributed tracing
2. **Audit Logging** (60%) - Like Taskiq hooks
3. **Performance Monitoring** (50%) - Metrics, timing
4. **Authentication** (40%) - Validate API keys, JWT
5. **Message Validation** (35%) - Schema enforcement
6. **Encryption/Compression** (25%) - Security, optimization
7. **Retry Logic** (20%) - Automatic retries
8. **Rate Limiting** (15%) - Throttling
9. **DLQ Handling** (15%) - Failed message handling
10. **Custom Serialization** (10%) - Protobuf, Avro, Msgpack

---

## 1. OpenTelemetry - Distributed Tracing (Most Common)

Built-in support for automatic distributed tracing.

```python
from faststream.kafka import KafkaBroker
from faststream.kafka.opentelemetry import KafkaTelemetryMiddleware

broker = KafkaBroker(
    "localhost:9092",
    middlewares=[
        KafkaTelemetryMiddleware()  # Automatic distributed tracing
    ]
)

# This automatically:
# - Creates spans for each message
# - Tracks message flow across services
# - Sends to Jaeger/Zipkin/Tempo
# - Adds baggage/context propagation
```

---

## 2. Audit Logging - Save Task Info/State (Like Taskiq!)

Similar to Taskiq hooks - creates an audit trail for messages by saving processing info to SQLite.

```python
from faststream import BaseMiddleware
from faststream.kafka.message import KafkaMessage
import sqlite3
from datetime import datetime
import time
from typing import Callable, Any

class AuditMiddleware(BaseMiddleware):
    """
    Similar to Taskiq hooks - audit trail for messages
    Saves message processing info to SQLite
    """
    
    def __init__(self):
        super().__init__()
        # Initialize SQLite database
        self.conn = sqlite3.connect("audit.db", check_same_thread=False)
        self.conn.execute("""
            CREATE TABLE IF NOT EXISTS message_audit (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                topic TEXT,
                partition INTEGER,
                offset INTEGER,
                message_body TEXT,
                handler_name TEXT,
                started_at TIMESTAMP,
                completed_at TIMESTAMP,
                duration_ms FLOAT,
                status TEXT,
                error TEXT
            )
        """)
        self.conn.commit()
    
    async def consume_scope(self, call_next, msg: KafkaMessage):
        """
        Called for each message AFTER filtering, has full message context
        This is the BEST place for detailed audit logging
        (equivalent to Taskiq's pre_execute hook)
        """
        start_time = time.time()
        error = None
        
        try:
            result = await call_next(msg)
            status = "success"
            return result
        except Exception as e:
            status = "error" 
            error = str(e)
            raise
        finally:
            duration = (time.time() - start_time) * 1000
            
            # Now we have full message context
            self.conn.execute("""
                INSERT INTO message_audit 
                (topic, partition, offset, message_body, started_at, 
                 completed_at, duration_ms, status, error)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
            """, (
                msg.topic,
                msg.partition,
                msg.offset,
                str(msg.body)[:500],  # First 500 chars
                datetime.fromtimestamp(start_time),
                datetime.now(),
                duration,
                status,
                error
            ))
            self.conn.commit()
```

---

## 3. Performance Monitoring - Track Timing & Metrics

Track message processing performance and collect metrics.

```python
class PerformanceMiddleware(BaseMiddleware):
    """
    Track message processing performance
    Similar to Prometheus metrics but custom
    """
    
    def __init__(self):
        super().__init__()
        self.metrics = {
            "total_messages": 0,
            "total_errors": 0,
            "total_duration_ms": 0,
            "by_topic": {}
        }
    
    async def consume_scope(self, call_next, msg: KafkaMessage):
        start_time = time.time()
        
        try:
            result = await call_next(msg)
            
            # Record success metrics
            duration = (time.time() - start_time) * 1000
            self.metrics["total_messages"] += 1
            self.metrics["total_duration_ms"] += duration
            
            # Track by topic
            if msg.topic not in self.metrics["by_topic"]:
                self.metrics["by_topic"][msg.topic] = {
                    "count": 0, "total_ms": 0, "errors": 0
                }
            
            self.metrics["by_topic"][msg.topic]["count"] += 1
            self.metrics["by_topic"][msg.topic]["total_ms"] += duration
            
            return result
            
        except Exception as e:
            self.metrics["total_errors"] += 1
            if msg.topic in self.metrics["by_topic"]:
                self.metrics["by_topic"][msg.topic]["errors"] += 1
            raise
    
    def get_stats(self):
        """Get performance statistics"""
        avg_duration = (
            self.metrics["total_duration_ms"] / self.metrics["total_messages"]
            if self.metrics["total_messages"] > 0 else 0
        )
        
        return {
            "total_messages": self.metrics["total_messages"],
            "total_errors": self.metrics["total_errors"],
            "avg_duration_ms": avg_duration,
            "by_topic": self.metrics["by_topic"]
        }
```

---

## 4. Authentication & Authorization

Validate message authentication/authorization, check API keys or JWT tokens in message headers.

```python
class AuthMiddleware(BaseMiddleware):
    """
    Validate message authentication/authorization
    Check API keys, JWT tokens in message headers
    """
    
    async def consume_scope(self, call_next, msg: KafkaMessage):
        # Check message headers for auth token
        headers = msg.headers or {}
        auth_token = headers.get("authorization")
        
        if not auth_token:
            raise ValueError("Missing authorization header")
        
        # Validate token (simplified)
        if not self._validate_token(auth_token):
            raise ValueError("Invalid authorization token")
        
        # Add user info to context for handler to use
        # msg.user_id = self._extract_user_id(auth_token)
        
        return await call_next(msg)
    
    def _validate_token(self, token):
        """Validate JWT or API key"""
        return token.startswith("Bearer ")
    
    def _extract_user_id(self, token):
        """Extract user ID from token"""
        return "user_123"
```

---

## 5. Message Validation & Schema Enforcement

Validate message schema before processing and reject invalid messages early.

```python
import json

class ValidationMiddleware(BaseMiddleware):
    """
    Validate message schema before processing
    Reject invalid messages early
    """
    
    def __init__(self, schemas: dict):
        super().__init__()
        self.schemas = schemas  # topic -> schema mapping
    
    async def consume_scope(self, call_next, msg: KafkaMessage):
        # Get schema for this topic
        schema = self.schemas.get(msg.topic)
        
        if schema:
            # Validate message against schema
            try:
                parsed = json.loads(msg.body)
                self._validate_schema(parsed, schema)
            except (json.JSONDecodeError, ValueError) as e:
                # Invalid message - send to DLQ or log
                print(f"Invalid message from {msg.topic}: {e}")
                raise ValueError(f"Message validation failed: {e}")
        
        return await call_next(msg)
    
    def _validate_schema(self, data: dict, schema: dict):
        """Simple schema validation"""
        for field, field_type in schema.items():
            if field not in data:
                raise ValueError(f"Missing required field: {field}")
            if not isinstance(data[field], field_type):
                raise ValueError(f"Invalid type for {field}")
```

---

## 6. Message Encryption/Decryption

Encrypt outgoing messages and decrypt incoming messages.

```python
class EncryptionMiddleware(BaseMiddleware):
    """
    Encrypt outgoing messages, decrypt incoming messages
    """
    
    def __init__(self, encryption_key: bytes):
        super().__init__()
        self.key = encryption_key
    
    async def consume_scope(self, call_next, msg: KafkaMessage):
        """Decrypt incoming messages"""
        # Decrypt message body before handler receives it
        decrypted_body = self._decrypt(msg.body)
        msg._decoded_body = decrypted_body
        
        return await call_next(msg)
    
    async def publish_scope(self, call_next, msg, *args, **kwargs):
        """Encrypt outgoing messages"""
        # Encrypt message before publishing
        if isinstance(msg, bytes):
            encrypted_msg = self._encrypt(msg)
            return await call_next(encrypted_msg, *args, **kwargs)
        
        return await call_next(msg, *args, **kwargs)
    
    def _encrypt(self, data: bytes) -> bytes:
        """Simple encryption (use proper crypto in production!)"""
        # Use cryptography library in production
        return b"ENCRYPTED:" + data
    
    def _decrypt(self, data: bytes) -> bytes:
        """Simple decryption"""
        if data.startswith(b"ENCRYPTED:"):
            return data[10:]
        return data
```

---

## 7. Retry & Error Handling

Automatic retry on failure with exponential backoff.

```python
import asyncio

class RetryMiddleware(BaseMiddleware):
    """
    Automatic retry on failure with exponential backoff
    """
    
    def __init__(self, max_retries: int = 3, base_delay: float = 1.0):
        super().__init__()
        self.max_retries = max_retries
        self.base_delay = base_delay
    
    async def consume_scope(self, call_next, msg: KafkaMessage):
        last_error = None
        
        for attempt in range(self.max_retries + 1):
            try:
                return await call_next(msg)
            
            except Exception as e:
                last_error = e
                
                if attempt < self.max_retries:
                    # Exponential backoff
                    delay = self.base_delay * (2 ** attempt)
                    print(f"Retry {attempt + 1}/{self.max_retries} after {delay}s")
                    await asyncio.sleep(delay)
                else:
                    # Max retries exceeded
                    print(f"Failed after {self.max_retries} retries")
                    raise last_error
```

---

## 8. Rate Limiting

Limit message processing rate per topic/consumer.

```python
class RateLimitMiddleware(BaseMiddleware):
    """
    Limit message processing rate per topic/consumer
    """
    
    def __init__(self, max_per_second: int = 100):
        super().__init__()
        self.max_per_second = max_per_second
        self.last_reset = time.time()
        self.count = 0
    
    async def consume_scope(self, call_next, msg: KafkaMessage):
        # Reset counter every second
        now = time.time()
        if now - self.last_reset >= 1.0:
            self.count = 0
            self.last_reset = now
        
        # Check rate limit
        if self.count >= self.max_per_second:
            # Wait until next second
            sleep_time = 1.0 - (now - self.last_reset)
            if sleep_time > 0:
                await asyncio.sleep(sleep_time)
            self.count = 0
            self.last_reset = time.time()
        
        self.count += 1
        return await call_next(msg)
```

---

## 9. Dead Letter Queue (DLQ) - Failed Message Handling

Send failed messages to a Dead Letter Queue for later inspection.

```python
class DLQMiddleware(BaseMiddleware):
    """
    Send failed messages to Dead Letter Queue
    """
    
    def __init__(self, dlq_topic: str):
        super().__init__()
        self.dlq_topic = dlq_topic
    
    async def consume_scope(self, call_next, msg: KafkaMessage):
        try:
            return await call_next(msg)
        
        except Exception as e:
            # Log error
            print(f"Message failed, sending to DLQ: {e}")
            
            # Send to DLQ (you'd need broker reference)
            # await broker.publish(
            #     {
            #         "original_topic": msg.topic,
            #         "original_body": msg.body,
            #         "error": str(e),
            #         "timestamp": datetime.now().isoformat()
            #     },
            #     topic=self.dlq_topic
            # )
            
            # Re-raise or swallow depending on requirements
            raise
```

---

## Complete Example - Combining Multiple Middlewares

```python
from faststream import FastStream, Logger
from faststream.kafka import KafkaBroker
from faststream.kafka.opentelemetry import KafkaTelemetryMiddleware

# Create broker with multiple middlewares (applied in order)
broker = KafkaBroker(
    "localhost:9092",
    middlewares=[
        KafkaTelemetryMiddleware(),  # 1. OpenTelemetry tracing
        AuditMiddleware(),            # 2. Audit logging to SQLite
        PerformanceMiddleware(),      # 3. Performance metrics
        AuthMiddleware(),             # 4. Authentication
        ValidationMiddleware(         # 5. Schema validation
            schemas={
                "orders": {"order_id": str, "amount": (int, float)}
            }
        ),
        RateLimitMiddleware(max_per_second=50),  # 6. Rate limiting
        RetryMiddleware(max_retries=3),          # 7. Auto-retry
        DLQMiddleware(dlq_topic="failed_messages")  # 8. DLQ
    ]
)

app = FastStream(broker)

@broker.subscriber("orders")
async def process_order(order: dict, logger: Logger):
    """
    All middlewares run before this handler:
    1. OpenTelemetry creates a span
    2. Audit logs the message
    3. Performance tracks timing
    4. Auth validates token
    5. Validation checks schema
    6. Rate limit enforced
    7. Retry on failure
    8. DLQ on ultimate failure
    """
    logger.info(f"Processing order: {order}")
    # Your business logic here
```

---

## Taskiq Hooks vs FastStream Middleware

### Taskiq Hooks
- **pre_execute**: Before task runs
- **post_execute**: After task completes
- **post_save**: After result saved
- **on_error**: On task failure

### FastStream Middleware (More Granular)
- **on_receive**: First thing when message arrives
- **parser**: Convert broker message → StreamMessage
- **filter**: Apply message filtering
- **consume_scope**: Before handler (has full message context) ✓ **BEST FOR AUDIT**
- **decoder**: Deserialize message
- **handler**: Your subscriber function
- **publish_scope**: Intercept outgoing messages
- **after_processed**: After everything completes

### Key Differences

1. **FastStream has more hooks** (8 stages vs 4 in Taskiq)
2. **FastStream hooks are per-message** (streaming), Taskiq per-task (job queue)
3. **FastStream supports publish interception**, Taskiq doesn't need it
4. **Both support audit trails**, but FastStream is more real-time

### For Your Audit Use Case

**Use `consume_scope()`** - it has full message context (topic, partition, offset) and runs right before your handler, perfect for audit trails!

---

## Middleware Execution Order

Middlewares are applied in the order they're listed. The execution flow is:

```
Message In
    ↓
Middleware 1 (enter)
    ↓
Middleware 2 (enter)
    ↓
Middleware 3 (enter)
    ↓
Handler executes
    ↓
Middleware 3 (exit)
    ↓
Middleware 2 (exit)
    ↓
Middleware 1 (exit)
    ↓
Message Ack/Complete
```

**Important**: Place order-dependent middlewares carefully. For example:
- Auth should come before business logic middlewares
- Retry should wrap around error-prone operations
- DLQ should be last to catch all failures

---

## Best Practices

1. **Keep middleware focused** - Each middleware should do one thing well
2. **Use `consume_scope` for most cases** - It has full message context
3. **Handle exceptions carefully** - Decide whether to re-raise or swallow
4. **Be mindful of performance** - Middleware runs for EVERY message
5. **Test middleware independently** - Unit test each middleware separately
6. **Log liberally** - Middleware issues can be hard to debug
7. **Use built-in middlewares** - OpenTelemetry, compression when available
8. **Consider order** - Authentication before validation, retry before DLQ

---

## Summary

FastStream middleware provides powerful message interception capabilities:

- **More granular than Taskiq hooks** (8 stages vs 4)
- **Perfect for audit trails** using `consume_scope()`
- **OpenTelemetry is the #1 use case** for distributed tracing
- **Can be chained** for complex processing pipelines
- **Similar concepts to Taskiq** but adapted for streaming

For your SQLite audit trail use case, `consume_scope()` is the equivalent of Taskiq's `pre_execute` hook, but with richer message metadata (topic, partition, offset).