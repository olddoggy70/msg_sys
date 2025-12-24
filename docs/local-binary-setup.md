# Local Binary Setup (No Docker)

## 🎯 Goal
Run everything using local binaries instead of Docker. Perfect for development and learning.

**Advantages:**
- ✅ Faster startup (no container overhead)
- ✅ Easier debugging (direct access to processes)
- ✅ Lower resource usage (no Docker daemon)
- ✅ Simpler for single machine development

**When to switch to Docker:**
- When deploying to production
- When sharing with team (consistent environment)
- When running multiple instances/services

---

## Phase 1: Install Local Binaries

### 1.1 NATS Server (Local Binary)

**macOS:**
```bash
# Using Homebrew
brew install nats-server

# Or download binary
curl -L https://github.com/nats-io/nats-server/releases/download/v2.10.7/nats-server-v2.10.7-darwin-amd64.zip -o nats-server.zip
unzip nats-server.zip
sudo mv nats-server-v2.10.7-darwin-amd64/nats-server /usr/local/bin/
```

**Linux:**
```bash
# Download binary
curl -L https://github.com/nats-io/nats-server/releases/download/v2.10.7/nats-server-v2.10.7-linux-amd64.tar.gz -o nats-server.tar.gz
tar -xzf nats-server.tar.gz
sudo mv nats-server-v2.10.7-linux-amd64/nats-server /usr/local/bin/

# Or using package manager (Ubuntu/Debian)
curl -fsSL https://packagecloud.io/nats-io/nats-server/gpgkey | sudo apt-key add -
echo "deb https://packagecloud.io/nats-io/nats-server/ubuntu/ focal main" | sudo tee /etc/apt/sources.list.d/nats-server.list
sudo apt-get update
sudo apt-get install nats-server
```

**Windows:**
```powershell
# Download from GitHub releases
# https://github.com/nats-io/nats-server/releases
# Extract nats-server.exe to C:\Program Files\NATS\

# Or using Chocolatey
choco install nats-server
```

**Verify Installation:**
```bash
nats-server --version
# Output: nats-server: v2.10.7
```

### 1.2 NATS CLI (Optional but Useful)

**macOS/Linux:**
```bash
# macOS
brew install nats-io/nats-tools/nats

# Linux
curl -L https://github.com/nats-io/natscli/releases/download/v0.1.1/nats-0.1.1-linux-amd64.zip -o nats-cli.zip
unzip nats-cli.zip
sudo mv nats-0.1.1-linux-amd64/nats /usr/local/bin/
```

**Verify:**
```bash
nats --version
```

---

## Phase 2: Configuration Files

### 2.1 NATS Server Configuration

Create `nats-server.conf`:
```conf
# NATS Server Configuration (Local Development)

# Server settings
host: 127.0.0.1
port: 4222

# Enable JetStream (required for persistence)
jetstream {
    store_dir: "./nats-data"   # Local directory for storage
    max_memory_store: 1GB
    max_file_store: 10GB
}

# Monitoring
http: 8222   # Monitoring UI at http://localhost:8222

# Logging
debug: false
trace: false
logtime: true
log_file: "./logs/nats-server.log"

# Limits (adjust based on your needs)
max_connections: 100
max_payload: 1MB
max_pending: 64MB
```

### 2.2 Directory Structure

Create necessary directories:
```bash
mkdir -p nats-data logs
```

Your project structure:
```
project/
├── nats-data/          # JetStream storage (auto-created)
├── logs/               # Log files
├── nats-server.conf    # NATS configuration
├── app.py              # Your application
├── tasks.py
├── tasks.db            # SQLite database
└── requirements.txt
```

---

## Phase 3: Running Services

### 3.1 Start NATS Server (Local Binary)

**Terminal 1 - NATS Server:**
```bash
# Start with configuration file
nats-server -c nats-server.conf

# Or start with inline options
nats-server -js -m 8222 --store_dir ./nats-data

# Output:
# [1] 2024/01/15 10:30:00.000000 [INF] Starting nats-server
# [1] 2024/01/15 10:30:00.000000 [INF]   Version:  2.10.7
# [1] 2024/01/15 10:30:00.000000 [INF]   Git:      [not set]
# [1] 2024/01/15 10:30:00.000000 [INF]   Listening for client connections on 0.0.0.0:4222
# [1] 2024/01/15 10:30:00.000000 [INF]   Server is ready
```

**Verify NATS is running:**
```bash
# Check with NATS CLI
nats server list

# Or check monitoring UI
open http://localhost:8222
```

### 3.2 Start Your Application

**Terminal 2 - FastStream:**
```bash
# Activate virtual environment
source venv/bin/activate

# Start FastStream
faststream run app:app

# Output:
# INFO:     Started server process
# INFO:     Waiting for application startup.
# INFO:     Application startup complete.
```

**Terminal 3 - Taskiq Worker:**
```bash
# Activate virtual environment
source venv/bin/activate

# Start Taskiq worker
taskiq worker tasks:broker

# Output:
# [INFO] Starting worker...
# [INFO] Worker started successfully
```

**Terminal 4 - Dashboard (Optional):**
```bash
# Activate virtual environment
source venv/bin/activate

# Start dashboard
uvicorn dashboard:app --port 8000 --reload

# Open http://localhost:8000
```

### 3.3 Process Management Scripts

Create helper scripts to manage everything:

**`start.sh` (Linux/macOS):**
```bash
#!/bin/bash

# Create necessary directories
mkdir -p nats-data logs

# Start NATS in background
echo "Starting NATS server..."
nats-server -c nats-server.conf > logs/nats.log 2>&1 &
NATS_PID=$!
echo "NATS PID: $NATS_PID"

# Wait for NATS to be ready
sleep 2

# Start FastStream in background
echo "Starting FastStream..."
source venv/bin/activate
faststream run app:app > logs/faststream.log 2>&1 &
FASTSTREAM_PID=$!
echo "FastStream PID: $FASTSTREAM_PID"

# Start Taskiq worker in background
echo "Starting Taskiq worker..."
taskiq worker tasks:broker > logs/taskiq.log 2>&1 &
TASKIQ_PID=$!
echo "Taskiq PID: $TASKIQ_PID"

# Start dashboard
echo "Starting dashboard..."
uvicorn dashboard:app --port 8000 > logs/dashboard.log 2>&1 &
DASHBOARD_PID=$!
echo "Dashboard PID: $DASHBOARD_PID"

# Save PIDs to file for stopping later
echo "$NATS_PID" > .pids
echo "$FASTSTREAM_PID" >> .pids
echo "$TASKIQ_PID" >> .pids
echo "$DASHBOARD_PID" >> .pids

echo ""
echo "All services started!"
echo "NATS Monitoring: http://localhost:8222"
echo "Dashboard: http://localhost:8000"
echo ""
echo "To stop all services: ./stop.sh"
```

**`stop.sh` (Linux/macOS):**
```bash
#!/bin/bash

if [ -f .pids ]; then
    echo "Stopping services..."
    while read pid; do
        if ps -p $pid > /dev/null; then
            echo "Killing process $pid"
            kill $pid
        fi
    done < .pids
    rm .pids
    echo "All services stopped"
else
    echo "No PID file found. Services may not be running."
fi
```

**`start.bat` (Windows):**
```batch
@echo off

REM Create directories
mkdir nats-data 2>nul
mkdir logs 2>nul

REM Start NATS
echo Starting NATS server...
start "NATS Server" nats-server -c nats-server.conf

REM Wait for NATS to start
timeout /t 2 /nobreak

REM Start FastStream
echo Starting FastStream...
start "FastStream" cmd /k "venv\Scripts\activate && faststream run app:app"

REM Start Taskiq
echo Starting Taskiq...
start "Taskiq" cmd /k "venv\Scripts\activate && taskiq worker tasks:broker"

REM Start Dashboard
echo Starting Dashboard...
start "Dashboard" cmd /k "venv\Scripts\activate && uvicorn dashboard:app --port 8000"

echo.
echo All services started!
echo NATS Monitoring: http://localhost:8222
echo Dashboard: http://localhost:8000
```

Make scripts executable:
```bash
chmod +x start.sh stop.sh
```

---

## Phase 4: Future Upgrades (Still No Docker Required!)

### 4.1 Add SigNoz (Local Binary)

When you're ready for observability, you can run SigNoz locally:

**Option 1: SigNoz Binary (Lightweight)**
```bash
# Download SigNoz
git clone https://github.com/SigNoz/signoz.git
cd signoz/deploy

# Run install script (uses Docker Compose internally)
./install.sh

# Or use standalone mode (if available)
```

**Option 2: Jaeger (Lighter Alternative)**
```bash
# Download Jaeger all-in-one binary
# macOS/Linux
curl -LO https://github.com/jaegertracing/jaeger/releases/download/v1.52.0/jaeger-1.52.0-linux-amd64.tar.gz
tar -xzf jaeger-1.52.0-linux-amd64.tar.gz
cd jaeger-1.52.0-linux-amd64

# Run Jaeger (in-memory, no persistence)
./jaeger-all-in-one --collector.otlp.enabled=true

# Or with persistence (badger DB)
./jaeger-all-in-one \
  --collector.otlp.enabled=true \
  --badger.ephemeral=false \
  --badger.directory-value=./jaeger-data \
  --badger.directory-key=./jaeger-data

# Access UI: http://localhost:16686
```

Update `start.sh`:
```bash
# Add Jaeger to startup
echo "Starting Jaeger..."
./jaeger-all-in-one --collector.otlp.enabled=true > logs/jaeger.log 2>&1 &
JAEGER_PID=$!
echo "$JAEGER_PID" >> .pids
```

### 4.2 Add Prometheus (Local Binary)

**Download Prometheus:**
```bash
# macOS
brew install prometheus

# Linux
wget https://github.com/prometheus/prometheus/releases/download/v2.48.0/prometheus-2.48.0.linux-amd64.tar.gz
tar -xzf prometheus-2.48.0.linux-amd64.tar.gz
cd prometheus-2.48.0.linux-amd64
```

**Create `prometheus.yml`:**
```yaml
global:
  scrape_interval: 15s

scrape_configs:
  - job_name: 'faststream-app'
    static_configs:
      - targets: ['localhost:9090']
  
  - job_name: 'nats'
    static_configs:
      - targets: ['localhost:8222']
```

**Run Prometheus:**
```bash
prometheus --config.file=prometheus.yml

# Access UI: http://localhost:9090
```

### 4.3 Add Grafana (Local Binary)

**Download Grafana:**
```bash
# macOS
brew install grafana

# Linux
wget https://dl.grafana.com/enterprise/release/grafana-enterprise-10.2.2.linux-amd64.tar.gz
tar -xzf grafana-enterprise-10.2.2.linux-amd64.tar.gz
cd grafana-10.2.2
```

**Run Grafana:**
```bash
./bin/grafana-server

# Access UI: http://localhost:3000
# Default login: admin/admin
```

---

## Phase 5: Comparison - Docker vs Local Binaries

### Resources (Typical Development Machine)

| Component | Docker | Local Binary | Savings |
|-----------|--------|--------------|---------|
| NATS | ~100MB RAM | ~50MB RAM | 50% |
| SigNoz/Jaeger | ~1GB RAM | ~200MB RAM | 80% |
| Prometheus | ~200MB RAM | ~100MB RAM | 50% |
| Grafana | ~150MB RAM | ~80MB RAM | 47% |
| **Total** | **~1.5GB** | **~430MB** | **71%** |

### Startup Time

| Action | Docker | Local Binary |
|--------|--------|--------------|
| Start NATS | 2-3s | <1s |
| Start SigNoz | 30-60s | 5-10s |
| Total startup | 40-90s | 6-15s |

### When to Use Each

**Use Local Binaries When:**
- ✅ Developing alone
- ✅ Learning/experimenting
- ✅ Limited RAM (<8GB)
- ✅ Want faster startup
- ✅ Debugging (easier to attach debugger)

**Use Docker When:**
- ✅ Team collaboration (consistency)
- ✅ CI/CD pipelines
- ✅ Production deployment
- ✅ Multiple environments (dev/staging/prod)
- ✅ Complex multi-service setups

---

## Phase 6: Hybrid Approach (Recommended)

**Best Practice:** Use local binaries for core services, Docker for optional ones:

```bash
# Local binaries (always running)
✅ NATS Server (fast, lightweight)
✅ Python app (your code)
✅ SQLite (file-based, no process)

# Docker (only when needed)
✅ SigNoz/Jaeger (complex setup)
✅ Prometheus + Grafana (optional)
```

**`docker-compose-optional.yml`:**
```yaml
# Optional services for observability
version: '3.8'

services:
  jaeger:
    image: jaegertracing/all-in-one:latest
    ports:
      - "16686:16686"  # UI
      - "4317:4317"    # OTLP
    environment:
      - COLLECTOR_OTLP_ENABLED=true
  
  prometheus:
    image: prom/prometheus:latest
    ports:
      - "9090:9090"
    volumes:
      - ./prometheus.yml:/etc/prometheus/prometheus.yml
  
  grafana:
    image: grafana/grafana:latest
    ports:
      - "3000:3000"
    environment:
      - GF_SECURITY_ADMIN_PASSWORD=admin
```

**Usage:**
```bash
# MVP: Local binaries only
./start.sh

# With observability: Add Docker for monitoring
docker-compose -f docker-compose-optional.yml up -d
./start.sh
```

---

## Phase 7: Production Considerations

### When Moving to Production

**You'll eventually want Docker because:**
1. **Consistency:** Same environment everywhere
2. **Orchestration:** Kubernetes, Docker Swarm
3. **Scaling:** Easy to add replicas
4. **Monitoring:** Standard container metrics
5. **Updates:** Rolling deployments

**Migration Path:**
```
Week 1-4:  Local binaries (development)
           ↓
Week 5-8:  Local binaries + Docker optional services
           ↓
Week 9+:   Full Docker (staging/production)
```

**But you can develop entirely with local binaries and only containerize for deployment!**

---

## 📋 Quick Command Reference

### Local Binary Setup
```bash
# One-time setup
brew install nats-server          # or download binary
mkdir -p nats-data logs
python -m venv venv
source venv/bin/activate
pip install -r requirements.txt

# Start services (manual)
nats-server -c nats-server.conf   # Terminal 1
faststream run app:app            # Terminal 2
taskiq worker tasks:broker        # Terminal 3
uvicorn dashboard:app --port 8000 # Terminal 4

# Or use helper script
chmod +x start.sh stop.sh
./start.sh                        # Start all
./stop.sh                         # Stop all
```

### Docker Setup (For Comparison)
```bash
# One-time setup
python -m venv venv
source venv/bin/activate
pip install -r requirements.txt

# Start services
docker-compose up -d              # All infrastructure
faststream run app:app            # Your app
taskiq worker tasks:broker        # Your worker
```

---

## ✅ Recommended Approach

**For MVP (Weeks 1-4):**
```bash
✅ Local binaries for everything
✅ No Docker at all
✅ Faster, simpler, easier to debug
```

**When Adding Observability (Weeks 5+):**
```bash
✅ Keep NATS as local binary (fast)
✅ Keep your app as local Python (easy debugging)
✅ Add Docker only for Jaeger/Prometheus (complex setup)
```

**Production Deployment:**
```bash
✅ Containerize everything with Docker
✅ Use Kubernetes or Docker Swarm
✅ But keep developing locally with binaries!
```

**Bottom Line:** You can develop the **entire project** without Docker. Only add it when deploying to production or when you need specific tools that are easier in Docker (like SigNoz).
