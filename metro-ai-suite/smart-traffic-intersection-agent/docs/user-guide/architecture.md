# Smart Traffic Intersection Agent - Architecture

## What Does This Agent Do?

The Smart Traffic Intersection Agent is an **edge-deployed AI system** that monitors a single traffic intersection. Think of it as a **smart traffic camera operator** that:
- **Watches** traffic through cameras (via MQTT messages)
- **Checks** the weather conditions
- **Analyzes** the scene using AI (Vision Language Model)
- **Reports** traffic density, alerts, and recommendations

---

## Type of Agent: Event-Driven Pipeline Agent

Unlike the Route Planning Agent (which uses a state machine), this agent uses an **event-driven pipeline** pattern:

```
┌──────────────────────────────────────────────────────────────────────────────┐
│                    TRAFFIC INTERSECTION AGENT                                │
│                                                                              │
│   ┌─────────────┐     ┌─────────────┐     ┌─────────────┐     ┌──────────┐  │
│   │   MQTT      │     │    Data     │     │    VLM      │     │   API    │  │
│   │  Service    │────▶│ Aggregator  │────▶│  Service    │────▶│ Response │  │
│   │ (Listener)  │     │ (Collector) │     │ (Analyzer)  │     │          │  │
│   └─────────────┘     └─────────────┘     └─────────────┘     └──────────┘  │
│         │                   │                   │                           │
│         │                   │                   │                           │
│   Camera Data          Combines:           AI Analysis:                     │
│   (4 directions)       - Traffic counts    - Traffic summary                │
│                        - Camera images     - Safety alerts                  │
│                        - Timestamps        - Recommendations                │
│                                                                              │
│                        ┌─────────────┐                                      │
│                        │   Weather   │                                      │
│                        │   Service   │──────────────────────────────────────│
│                        │   (NWS API) │  Provides weather context            │
│                        └─────────────┘                                      │
└──────────────────────────────────────────────────────────────────────────────┘
```

---

## The Agent's Components (Services)

| Service | What it Does | Real-World Analogy |
|---------|--------------|-------------------|
| `MQTTService` | Listens to camera data from SceneScape | Security guard watching monitors |
| `DataAggregatorService` | Collects data from all 4 cameras | Combining all camera feeds |
| `WeatherService` | Fetches weather from National Weather Service | Checking weather.gov |
| `VLMService` | AI analysis using Vision Language Model | Expert analyst reviewing footage |
| `ConfigService` | Manages all configuration settings | Settings control panel |

---

## Data Flow (Step by Step)

### 1. Camera Data Arrives (MQTT)
```
SceneScape System
      │
      │ Publishes to MQTT topics:
      │   - scenescape/data/camera/camera1 (South)
      │   - scenescape/data/camera/camera2 (West)
      │   - scenescape/data/camera/camera3 (North)
      │   - scenescape/data/camera/camera4 (East)
      ▼
┌─────────────────┐
│  MQTT Service   │  Subscribes & receives camera data
└─────────────────┘
```

### 2. Data Aggregation
```python
# What the Data Aggregator collects:
{
    "north_camera": 5,      # Vehicle count from north
    "south_camera": 3,      # Vehicle count from south
    "east_camera": 8,       # Vehicle count from east
    "west_camera": 2,       # Vehicle count from west
    "total_density": 18,    # Total vehicles at intersection
    "camera_images": {...}, # Base64 images from each camera
    "timestamp": "2026-01-28T10:30:00Z"
}
```

### 3. VLM Analysis (AI-Powered)
The VLM (Vision Language Model) receives:
- **Camera images** from all 4 directions
- **Vehicle counts** per direction
- **Weather data** (temperature, conditions)

And produces:
```python
{
    "traffic_summary": "Moderate traffic with 18 vehicles...",
    "alerts": [
        {
            "type": "CONGESTION",
            "level": "WARNING",
            "description": "High density on east approach"
        }
    ],
    "recommendations": [
        "Consider alternate routes from east",
        "Normal flow on north-south corridor"
    ]
}
```

### 4. API Response
External systems (like Route Planning Agent) call:
```
GET /traffic/current
```

And receive complete intersection intelligence.

---

## Weather Integration

The agent uses the **National Weather Service (NWS) API** for real weather data:

```
┌─────────────────────────────────────────────────────┐
│                  Weather Service                     │
│                                                     │
│  1. Get coordinates from config (lat, lon)          │
│  2. Call NWS API: api.weather.gov/points/{lat},{lon}│
│  3. Get hourly forecast URL                         │
│  4. Fetch current hour's weather                    │
│  5. Cache for 15 minutes                            │
│                                                     │
│  Returns:                                           │
│  - Temperature: 72°F                                │
│  - Conditions: "Partly Sunny"                       │
│  - Precipitation: false                             │
│  - Detailed forecast: "Partly sunny, high near 75"  │
└─────────────────────────────────────────────────────┘
```

Weather affects VLM analysis - rain, fog, or snow triggers additional safety alerts.

---

## How the VLM (AI) Works

The VLM Service uses **OpenVINO** to run a Vision Language Model locally:

```
┌──────────────────────────────────────────────────────────────┐
│                      VLM Service                              │
│                                                              │
│  Input:                                                      │
│  ┌─────────┐ ┌─────────┐ ┌─────────┐ ┌─────────┐            │
│  │ North   │ │ South   │ │ East    │ │ West    │            │
│  │ Camera  │ │ Camera  │ │ Camera  │ │ Camera  │            │
│  │ Image   │ │ Image   │ │ Image   │ │ Image   │            │
│  └─────────┘ └─────────┘ └─────────┘ └─────────┘            │
│       │           │           │           │                  │
│       └───────────┴───────────┴───────────┘                  │
│                       │                                      │
│                       ▼                                      │
│              ┌─────────────────┐                             │
│              │  Structured     │                             │
│              │  Prompt +       │  "Analyze this intersection │
│              │  Weather Data   │   with 18 vehicles,         │
│              │                 │   weather: Partly Sunny..." │
│              └─────────────────┘                             │
│                       │                                      │
│                       ▼                                      │
│              ┌─────────────────┐                             │
│              │  OpenVINO VLM   │  Local AI inference         │
│              │  (GPU/CPU)      │  (no cloud needed)          │
│              └─────────────────┘                             │
│                       │                                      │
│                       ▼                                      │
│              ┌─────────────────┐                             │
│              │  Structured     │  Traffic summary + Alerts   │
│              │  Response       │  + Recommendations          │
│              └─────────────────┘                             │
└──────────────────────────────────────────────────────────────┘
```

---

## Key Data Models

```python
# Traffic data from each camera
CameraDataMessage = {
    "camera_id": "camera1",
    "direction": "north",
    "vehicle_count": 5,
    "pedestrian_count": 2,
    "timestamp": "2026-01-28T10:30:00Z"
}

# Complete intersection snapshot
IntersectionData = {
    "intersection_id": "abc123",
    "intersection_name": "Main St & 1st Ave",
    "latitude": 33.309,
    "longitude": -111.935,
    "north_camera": 5,
    "south_camera": 3,
    "east_camera": 8,
    "west_camera": 2,
    "total_density": 18,
    "intersection_status": "MODERATE"  # NORMAL, MODERATE, HIGH
}

# VLM analysis output
VLMAnalysisData = {
    "traffic_summary": "Moderate congestion...",
    "alerts": [...],
    "recommendations": [...]
}
```

---

## Trigger Conditions for VLM Analysis

The agent doesn't analyze every single message. It triggers VLM analysis when:

| Condition | Trigger |
|-----------|---------|
| **High Traffic** | `total_density >= threshold` (default: 5) |
| **Time-based** | Every 30 seconds for low traffic |
| **All Cameras Ready** | Data received from all 4 directions |

---

## Multi-Agent Integration

This agent is designed to work with other agents:

```
┌─────────────────────────────────────┐
│      Route Planning Agent           │
│      (The Consumer)                 │
└──────────────┬──────────────────────┘
               │
               │ HTTP GET /traffic/current
               ▼
┌─────────────────────────────────────┐
│   Traffic Intersection Agent        │
│   (This Agent - The Provider)       │
│                                     │
│   Returns:                          │
│   - Traffic density                 │
│   - Weather conditions              │
│   - AI-generated alerts             │
│   - Camera images (optional)        │
└─────────────────────────────────────┘
```

---

## Topics to Read (For Beginners)

| Topic | Why It's Relevant | Resource |
|-------|-------------------|----------|
| **MQTT Protocol** | How camera data is streamed | Search "MQTT beginner tutorial" |
| **Event-Driven Architecture** | Core pattern of this agent | Search "Event-driven systems" |
| **Vision Language Models (VLM)** | AI that understands images + text | Search "VLM explained" |
| **OpenVINO** | Intel's AI inference toolkit | [OpenVINO Docs](https://docs.openvino.ai/) |
| **FastAPI** | The web framework for the API | [FastAPI Tutorial](https://fastapi.tiangolo.com/) |
| **asyncio** | Python async programming | Search "Python asyncio tutorial" |

---

## Key Differences from Route Planning Agent

| Aspect | Route Planning Agent | Traffic Intersection Agent |
|--------|---------------------|---------------------------|
| **Pattern** | State Machine (LangGraph) | Event-Driven Pipeline |
| **Scope** | City-wide routing | Single intersection |
| **Input** | User requests | MQTT camera streams |
| **AI Type** | Rule-based decisions | VLM image analysis |
| **Deployment** | Central server | Edge (at intersection) |
| **Role** | Consumer of traffic data | Provider of traffic data |

---

## Key Insight

This agent is an **AI-powered edge device** that:
- Runs **locally at the intersection** (no cloud dependency for inference)
- Uses **real AI (VLM)** to understand traffic scenes from images
- Provides **structured data** for other agents to consume
- Combines **multiple data sources** (cameras, weather) for context

It's the "eyes and brain" at each intersection, while the Route Planning Agent is the "navigator" that uses this intelligence!
