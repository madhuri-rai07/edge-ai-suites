# MCP Proof of Concept: Smart Route Planning Agent

## Overview

This document describes the Model Context Protocol (MCP) proof-of-concept implementation for the Smart Route Planning Agent. This implementation demonstrates how to integrate live traffic data as an MCP tool, decoupling the route-planner from direct controller instantiation.

## Architecture

```
┌─────────────────────────────────────┐
│  traffic-intersection-agent         │
│  (Provides WebSocket API)           │
└────────────┬────────────────────────┘
             │
             │ WebSocket API
             ↓
┌─────────────────────────────────────┐
│  MCP Server (mcp_server.py)         │
│  - Tool: get_live_traffic()         │
│  - Transport: stdio                 │
└─────────────┬───────────────────────┘
              │
              │ MCP Protocol (stdio)
              ↓
┌─────────────────────────────────────┐
│  route-planner.py (MCP Client)      │
│  - Uses MCP client session          │
│  - Calls get_live_traffic tool      │
└──────────────┬──────────────────────┘
               ↓
           Gradio UI
```

## Components

### 1. MCP Server (`mcp_server.py`)

**Purpose:** Exposes the `get_live_traffic` tool via MCP protocol

**Location:** `src/mcp_server.py`

**Features:**
- Wraps `LiveTrafficController.fetch_route_status()`
- Handles WebSocket connections to traffic-intersection-agent
- Serializes Pydantic models to JSON for MCP transport
- Includes error handling and logging

**Running the server:**
```bash
cd src
python mcp_server.py
```

### 2. Route Planner Client (`route_planner.py`)

**Purpose:** Route planning agent that uses MCP to fetch live traffic data

**Location:** `src/agents/route_planner.py`

**Changes:**
- Added `_initialize_mcp_client()` method to set up MCP connection
- Added `_get_live_traffic_data()` method to call MCP tool with fallback
- Modified `update_optimal_route_realtime()` to use MCP instead of direct controller

**Fallback Behavior:**
- If MCP server is not running, automatically falls back to direct `LiveTrafficController` instantiation
- Logs warning message when fallback occurs
- Route planning continues without interruption

## Setup and Running

### Prerequisites

1. **Python 3.10+** (project requirement)
2. **MCP package installed** (added to `pyproject.toml`)
3. **traffic-intersection-agent running** (provides WebSocket API at `ws://localhost:8081/api/v1/traffic/current/ws`)

### Installation

```bash
cd metro-ai-suite/smart-route-planning-agent/src

# Install dependencies (includes new mcp>=0.9.0)
pip install -e .
```

### Running the Proof of Concept

#### Terminal 1: Start MCP Server

```bash
cd metro-ai-suite/smart-route-planning-agent/src
python mcp_server.py
```

Expected output:
```
Starting MCP Server for Route Planning Agent
Server: route-traffic-server
Available tools: get_live_traffic
Transport: stdio
```

#### Terminal 2: Start Route Planner (Gradio UI)

```bash
cd metro-ai-suite/smart-route-planning-agent/src
python main.py
```

Expected output:
```
Starting Route Planner application on 0.0.0.0:7860...
```

#### Terminal 3 (Optional): Monitor traffic-intersection-agent

```bash
# The traffic-intersection-agent should already be running
# If not, start it via Docker compose:
cd metro-ai-suite/smart-traffic-intersection-agent/docker
docker compose up
```

### Using the Application

1. Open Gradio UI at `http://localhost:7860`
2. Select source and destination locations
3. Click "Start Route Planning"
4. Observe the route optimization process in real-time

### Monitoring MCP Traffic

**Check server logs:** Terminal 1 will show MCP server activity
```
MCP Tool: get_live_traffic called
MCP Tool: Successfully fetched 3 traffic records
```

**Check client logs:** Terminal 2 (route-planner logs) will show:
```
Initializing MCP client...
MCP client initialized successfully
Fetching live traffic data via MCP tool...
Successfully fetched 3 traffic records via MCP
```

## Configuration

### Environment Variables

**MCP_ENABLED** (default: `true`)
- Set to `true` to enable MCP for live traffic (proof-of-concept)
- Set to `false` to use direct controller (legacy fallback)

```bash
# Force legacy mode
export MCP_ENABLED=false
python src/main.py
```

## Data Flow

### Successful MCP Integration

```
1. route-planner calls update_optimal_route_realtime()
2. Calls _get_live_traffic_data()
3. Initializes MCP client (subprocess to mcp_server.py)
4. Calls mcp_client.call_tool("get_live_traffic", {})
5. MCP Server receives request
6. Server instantiates LiveTrafficController
7. Controller connects to traffic-intersection-agent via WebSocket
8. Traffic data returned as JSON through MCP protocol
9. Client deserializes to LiveTrafficData objects
10. Route optimization uses live traffic data
```

### Fallback to Direct Controller

```
1. If MCP server not running or connection fails
2. Client logs warning: "MCP tool call failed, falling back..."
3. Direct LiveTrafficController is instantiated
4. Same logic continues, ensuring no service interruption
```

## Testing

### Manual Testing

1. **Verify MCP server starts:**
   ```bash
   python mcp_server.py
   # Should print: "Starting MCP Server for Route Planning Agent"
   ```

2. **Verify MCP client connects:**
   ```bash
   python main.py
   # Logs should show: "Initializing MCP client..."
   ```

3. **Verify data flows:**
   - Route planning should produce same results as before
   - Live traffic updates should work correctly
   - No errors in either server or client terminals

### Automated Testing (Future)

```bash
# Run pytest with MCP enabled
MCP_ENABLED=true pytest tests/test_route_planner.py

# Run with fallback mode
MCP_ENABLED=false pytest tests/test_route_planner.py
```

## Implementation Details

### MCP Server Tool Definition

```python
@server.tool()
async def get_live_traffic() -> dict[str, Any]:
    """
    Fetch real-time live traffic data from all configured intersections.
    
    Returns:
        dict with keys:
        - success: bool
        - traffic_data: list of LiveTrafficData (as dicts)
        - count: int (number of records)
        - error: str (if success is False)
    """
```

### MCP Client Initialization

```python
# Subprocess-based transport
mcp_process = subprocess.Popen(
    [sys.executable, "-m", "mcp_server"],
    stdin=subprocess.PIPE,
    stdout=subprocess.PIPE,
    stderr=subprocess.PIPE,
    text=True
)

mcp_transport = StdioClientTransport(
    mcp_process.stdin,
    mcp_process.stdout
)

mcp_client = ClientSession(mcp_transport)
```

## Troubleshooting

### MCP Server won't start

**Error:** `ModuleNotFoundError: No module named 'mcp'`

**Solution:**
```bash
pip install -e .  # Install dependencies including mcp>=0.9.0
```

### MCP client fails to connect

**Error:** `Failed to initialize MCP client: ...`

**Solution:**
1. Ensure MCP server is running in another terminal
2. Check that port/process communication is working
3. Verify `mcp_server.py` is executable

### Fallback happening unexpectedly

**Symptom:** Client logs show fallback to direct controller

**Action:**
```bash
# Check MCP server logs for errors
# Restart MCP server
python mcp_server.py

# Restart route-planner
python main.py
```

### Traffic data not showing

**Verify** traffic-intersection-agent is running:
```bash
# Check if WebSocket is accessible
curl -i http://localhost:8081/health

# Should return 200 OK
```

## Next Steps (Future Extensions)

1. **Add more tools to MCP server:**
   - `get_weather` - Fetch weather data
   - `get_planned_events` - Fetch planned events
   - `get_traffic_trends` - Fetch historical traffic

2. **Persistent MCP connection:**
   - Keep MCP server running continuously
   - Handle reconnection logic

3. **Tool discovery:**
   - Auto-register tools in MCP server
   - Dynamic tool loading

4. **Production deployment:**
   - Package MCP server as separate service
   - Docker containerization
   - Kubernetes configuration

## References

- [MCP Protocol Specification](https://modelcontextprotocol.io/)
- [route_planner.py](/src/agents/route_planner.py) - Route planning agent
- [mcp_server.py](/src/mcp_server.py) - MCP server implementation
- [LiveTrafficController](/src/controllers/live_traffic.py) - Wrapped controller
