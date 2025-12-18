# Traffic Intelligence Service - AI Coding Assistant Guide

## System Architecture

This is a **real-time traffic intelligence microservice** for single intersection monitoring. The architecture follows an event-driven pattern with clear service boundaries:

```
MQTT Camera Data → DataAggregator → {WeatherService, VLMService} → REST API
```

### Core Services Layer
- **`services/data_aggregator.py`** - Central orchestrator that coordinates all data flows, maintains state, and triggers analysis
- **`services/mqtt_service.py`** - Handles MQTT subscriptions for 4 camera topics (north/south/east/west directions)  
- **`services/weather_service.py`** - Integrates with National Weather Service API for road condition analysis
- **`services/vlm_service.py`** - Triggers Vision Language Model analysis during high traffic periods
- **`services/config.py`** - Configuration management with env vars + JSON file fallback

### Key Data Flows
1. **Camera Data Ingestion**: MQTT messages → `process_camera_data()` → intersection state update → potential VLM trigger
2. **Analysis Triggers**: High traffic density OR sustained traffic patterns → VLM analysis with weather context
3. **Response Assembly**: Current state + weather + VLM analysis → `TrafficIntelligenceResponse`

## Critical Development Patterns

### Configuration Management
Use the ConfigService pattern for all settings. Config precedence: **Environment Variables → JSON file → defaults**
```python
# Always use ConfigService, not direct os.getenv()
config = ConfigService()
threshold = config.get_high_density_threshold()
```

### Data Models (`models/__init__.py`)
All data structures are **strongly typed dataclasses**. Key models:
- `CameraDataMessage` - MQTT input format  
- `IntersectionData` - Core traffic state (matches expected data.json schema)
- `TrafficIntelligenceResponse` - Complete API response format
- `VLMAnalysisData` - Structured AI analysis

### Async Service Patterns
Services use **structured logging** and **graceful error handling**:
```python
# Standard service method pattern
async def service_method(self) -> Optional[ResultType]:
    try:
        logger.info("Starting operation", context=value)
        # operation logic
        logger.debug("Operation completed", result=data)
        return result
    except Exception as e:
        logger.error("Operation failed", error=str(e))
        return None
```

### Background Task Management
DataAggregator runs **periodic analysis** and **cleanup tasks**. Use the standard pattern:
```python
self.task = asyncio.create_task(self._periodic_method())
# Cleanup in stop method
if self.task:
    self.task.cancel()
```

## Development Workflow

### UV-Based Commands (Preferred)
```bash
# Setup and run (uses ./dev.sh which wraps uv)
./dev.sh setup    # Create venv + install deps
./dev.sh run      # Start service on port 8081
./dev.sh dev      # Debug mode with LOG_LEVEL=DEBUG

# Alternative: use Makefile shortcuts
make setup && make dev
```

### Key Configuration Files
- **`config/traffic_intelligence.json`** - Main config with intersection details, MQTT topics, thresholds
- **`pyproject.toml`** - UV-managed dependencies, requires Python 3.10+
- **Environment variables** override JSON config values

### Local Development Tips
- **MQTT**: TLS is enabled by default, set `MQTT_USE_TLS=false` for local broker testing
- **VLM Service**: Expects external service at `localhost:9764` 
- **Weather API**: Uses NWS API with required User-Agent header

## API Integration Patterns

### FastAPI Service Dependencies
API routes use dependency injection to access services:
```python
def get_data_aggregator(request): return request.app.state.data_aggregator
# Use in route: async def endpoint(request: Request):
```

### Response Format
All API responses follow the **data.json schema** with these sections:
- `data` - Core intersection traffic state
- `camera_images` - Base64 images by direction  
- `weather_data` - Current conditions + road impact
- `vlm_analysis` - AI insights with structured alerts

### Error Handling
Services return `None` on failure, API layer converts to appropriate HTTP status:
```python
result = await service.get_data()
if not result:
    raise HTTPException(status_code=404, detail="No data available")
```

## Testing and Monitoring

### Health Checks
- **`/health`** - Basic service status
- **`/api/v1/status`** - Detailed metrics including MQTT connection, active cameras, analysis status

### Debugging
- Enable debug logging: `LOG_LEVEL=DEBUG ./dev.sh run`
- MQTT connection issues: Check TLS settings and certificate paths
- VLM analysis not triggering: Verify traffic density vs `high_density_threshold`

### Key Metrics to Monitor  
- Active camera count (should be 4 for all directions)
- Traffic density vs threshold (triggers analysis)
- VLM analysis frequency
- Weather API response times and cache hits