# Run Demo: All-in-One Local Pipeline (Option 3)

This guide shows how to run the smart route planner with two demo intersections on a single machine using Docker Compose overrides, while keeping the main compose file production-ready and independent.

## Prerequisites
- Docker and Docker Compose installed.
- From the repo root, ensure paths exist:
  - `metro-ai-suite/route-planner/docker/compose.yaml`
  - `metro-ai-suite/route-planner/docker/compose.edge-a.yaml`
  - `metro-ai-suite/route-planner/docker/compose.edge-b.yaml`
- Optional: Smart Intersection app stack running to provide the external network and broker. If you do not run the full app, create the external network manually.

Create the external network if not using the full app:
```bash
# Create external network used by overrides if missing
docker network ls | grep metro-vision-ai-app-recipe_scenescape || \
  docker network create metro-vision-ai-app-recipe_scenescape
```

## Start the Planner (Central)
```bash
cd metro-ai-suite/route-planner/docker
# Start only the planner (central API/UI)
docker compose -f compose.yaml up -d ai-route-planner
```

Health check:
```bash
curl -s http://localhost:7864/health || true
```

## Option A: Start Smart Intersection App (Recommended)
This spins up broker, DLStreamer, web UI, DB, Grafana, Node-RED, etc.
```bash
cd metro-ai-suite/metro-vision-ai-app-recipe
# Choose appropriate compose and env per app docs
# Example (check README/install for exact steps):
docker compose -f compose-scenescape.yml up -d
```

## Option B: Create External Network Only
If you do not need the full smart-intersection stack, ensure the external scenescape network exists (see prerequisites).

## Start Demo Intersections
Start Intersection A pair:
```bash
cd metro-ai-suite/route-planner/docker
# Planner must already be up
# Start VLM + Traffic Intelligence for Intersection A
# Uses external network: metro-vision-ai-app-recipe_scenescape
# Calls planner via http://ai-route-planner:7860/plan-route

docker compose -f compose.yaml -f compose.edge-a.yaml \
  up -d vlm-openvino-serving-a traffic-intelligence-a
```

Start Intersection B pair:
```bash
cd metro-ai-suite/route-planner/docker

docker compose -f compose.yaml -f compose.edge-b.yaml \
  up -d vlm-openvino-serving-b traffic-intelligence-b
```

## Verify & Health Checks
```bash
# Planner
curl -s http://localhost:7864/health || true

# Intersection A agent API/UI
curl -s http://localhost:8082/health || true
curl -s http://localhost:7861 || true

# Intersection B agent API/UI
curl -s http://localhost:8083/health || true
curl -s http://localhost:7862 || true
```

## Stop Demo
```bash
# Stop a specific pair
docker compose -f compose.yaml -f compose.edge-a.yaml down
docker compose -f compose.yaml -f compose.edge-b.yaml down

# Stop planner
docker compose -f compose.yaml down
```

## Configuration Notes
- Planner URL: overrides pass `ROUTE_PLANNER_URL=http://ai-route-planner:7860/plan-route` inside the Docker network.
- Intersection identity: set via `INTERSECTION_ID=A` or `INTERSECTION_ID=B` in overrides.
- External network: overrides attach to `metro-vision-ai-app-recipe_scenescape` to interoperate with the smart-intersection stack. If not using that stack, you can still create the network manually.
- Secrets: overrides reference the smart-intersection CA cert to enable MQTT/TLS where applicable. If you do not need broker connectivity, you can remove the `secrets` stanza.

## Production Reuse (Option 1)
- Central planner host: run only `ai-route-planner` via `compose.yaml`.
- Edge nodes: deploy the two-container traffic agent (VLM + traffic-intelligence) similar to the overrides, pointing `ROUTE_PLANNER_URL` to the central planner (e.g., `http://planner-host:7864`).
- Keep `INTERSECTION_ID` unique per site. The planner uses it to partition traffic snapshots and decisions.

## Troubleshooting
- If compose complains about missing external network: create it manually as shown above.
- If secrets path is missing: remove the `secrets` section or update the path to your local smart-intersection certs.
- Ports in use: overrides map unique host ports (A: 8082/7861, B: 8083/7862). Adjust if you have conflicts.
