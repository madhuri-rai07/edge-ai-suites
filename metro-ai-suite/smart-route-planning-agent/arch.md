# Unified Route Planner Architecture

This document outlines two minimal deployment options for the Smart Route Planner pipeline under a unified docker-compose stack.

## Option A: HTTP-Only (No New Infra)

- Components
  - `smart-intersection`: Simulates/collects telemetry; pushes via HTTP.
  - `smart-traffic-intersection-agent`: Ingests telemetry; processes/enriches; calls planner.
  - `ai-route-planner`: Exposes HTTP API for route planning.

- Data Flow
```
+---------------------+         HTTP POST /ingest          +-------------------------------+
|  smart-intersection |  --------------------------------> | smart-traffic-intersection-   |
|     (Scenescape)    |                                     |           agent               |
+---------------------+                                     +-------------------------------+
                                                                    |         
                                                                    | HTTP POST /plan-route
                                                                    v         
                                                           +-------------------------------+
                                                           |        ai-route-planner       |
                                                           |        (API: 7860/7864)       |
                                                           +-------------------------------+
```

- Compose anchors
  - `smart-intersection` env: `TRAFFIC_AGENT_URL=http://smart-traffic-intersection-agent:9000/ingest`
  - `smart-traffic-intersection-agent` env: `ROUTE_PLANNER_URL=http://ai-route-planner:7860/plan-route`
  - `ai-route-planner` exposes API on container `7860`, host `7864` (compose ports map)

- Pros/Cons
  - Pros: Simplest, easy debugging, no extra services
  - Cons: Tighter coupling, retries/backpressure must be implemented in services

## Option B: Minimal MQTT Broker

- Components
  - `mqtt-broker` (Mosquitto): Single lightweight message bus
  - `smart-intersection`: Publishes raw telemetry to MQTT
  - `smart-traffic-intersection-agent`: Subscribes to raw, processes; either publishes processed or calls planner HTTP
  - `ai-route-planner`: Subscribes to processed topic or offers HTTP API

- Data Flow (HTTP to planner)
```
+---------------------+            MQTT pub                +-------------------+
|  smart-intersection |  ------------------------------->  |   mqtt-broker     |
|     (Scenescape)    |                                   +-------------------+
                                                         MQTT sub |
                                                                   v
                                                   +-------------------------------+
                                                   | smart-traffic-intersection-   |
                                                   |           agent               |
                                                   +-------------------------------+
                                                            |
                                                            | HTTP POST /plan-route
                                                            v
                                                   +-------------------------------+
                                                   |        ai-route-planner       |
                                                   +-------------------------------+
```

- Alternative Data Flow (planner subscribes)
```
smart-intersection --MQTT pub--> mqtt-broker --MQTT sub--> smart-traffic-intersection-agent --MQTT pub (processed)--> mqtt-broker --MQTT sub--> ai-route-planner
```

- Topics & env (example)
  - Raw: `intersection/raw/{INTERSECTION_ID}`
  - Processed: `intersection/traffic/{INTERSECTION_ID}`
  - `MQTT_HOST=mqtt-broker`, `MQTT_PORT=1883`

- Pros/Cons
  - Pros: Decoupled producers/consumers, QoS/backpressure, easy fan-out
  - Cons: Adds one service, topic management, optional TLS setup

## Suggested Compose Layouts

- HTTP-only: 3 services on one network (`routeplanner`), env-driven URLs.
- With MQTT: Add `mqtt-broker` service; point apps to broker and topics.

## Configuration Contracts

- HTTP-only
  - `smart-intersection`: `TRAFFIC_AGENT_URL`, `INTERSECTION_ID`
  - `smart-traffic-intersection-agent`: `INGEST_PATH=/ingest`, `ROUTE_PLANNER_URL`, `INTERSECTION_ID`
  - `ai-route-planner`: `API_PORT`, optional tuning flags

- MQTT
  - Broker: `1883` port
  - `smart-intersection`: `MQTT_HOST`, `MQTT_PORT`, publish `intersection/raw/{id}`
  - `smart-traffic-intersection-agent`: subscribe raw, optionally publish processed
  - `ai-route-planner`: subscribe processed or keep HTTP endpoint

## Run Notes

- HTTP-only quick start
```
cd metro-ai-suite/route-planner/docker
docker compose up -d
curl -s http://localhost:7864/health || true
```

- Minimal MQTT (if chosen) quick start (compose must include broker)
```
cd metro-ai-suite/route-planner/docker
docker compose up -d
# Validate broker (if exposing 1883); attach client as needed
```

## Next Steps
- Choose Option A (simplest) or Option B (more decoupled).
- Align endpoints or topics if existing services differ; adjust compose envs accordingly.
- Optionally add healthchecks to gate `depends_on` with `service_healthy`.
