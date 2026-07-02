<!--- SPDX-FileCopyrightText: (C) 2026 Intel Corporation -->
<!--- SPDX-License-Identifier: Apache-2.0 -->

# Smart Traffic Intersection Agent — Agent Guide

> This file is a **coding-agent-friendly companion** to `manifest.yaml`. It expresses
> the same information as natural-language instructions so an AI coding agent
> (e.g. GitHub Copilot) can read it directly and act on it, without needing
> custom logic to parse the YAML schema. `manifest.yaml` remains the source of
> truth for the `oep` CLI; this file is generated/maintained alongside it for
> agent consumption.

## What this app does

Real-time traffic intersection analytics powered by a Vision Language Model
(VLM) running on Intel hardware via OpenVINO. It connects to a live video feed
(SceneScape / MQTT), analyzes frames at a configurable interval, and reports:

- Vehicle density (low / moderate / high)
- Incident and anomaly detection
- Weather-aware context (live API or mock mode)
- Live system metrics (CPU, GPU, memory)

It ships a FastAPI backend and a Gradio UI dashboard, and can be deployed via
Docker Compose or Helm (Kubernetes).

## Where the code lives

- Suite: `metro-ai-suite`
- Source directory: `metro-ai-suite/smart-traffic-intersection-agent`
- Repo: https://github.com/intel/edge-ai-suites (branch: `main`)
- App README: `metro-ai-suite/smart-traffic-intersection-agent/README.md`
- License: Apache-2.0

## Requirements before installing

- OS: Ubuntu 22.04 or 24.04
- Software: `docker >= 24.0`, `docker-compose-plugin >= 2.20`
- Optional (Kubernetes only): `helm >= 3.12`
- Hardware:
  - CPU: required, 4+ cores (default inference device)
  - GPU: optional (Intel Arc / Iris Xe) — set `VLM_TARGET_DEVICE=GPU`
  - NPU: optional, on supported Intel platforms

## Environment variables

Required:
- `VLM_MODEL_NAME` — HuggingFace model ID, e.g. `OpenVINO/Phi-3.5-vision-instruct-int8-ov`

Optional:
- `VLM_TARGET_DEVICE` (default `CPU`) — `CPU | GPU | NPU`
- `HUGGINGFACE_TOKEN` — required only for private/gated models
- `INTERSECTION_NAME` (default `intersection_1`) — logical name used in MQTT topics
- `INTERSECTION_LATITUDE` (default `37.51358`)
- `INTERSECTION_LONGITUDE` (default `-122.25591`)
- `WEATHER_MOCK` (default `false`) — use mocked weather instead of a live API
- `REFRESH_INTERVAL` (default `15`) — VLM analysis interval, in seconds

## How to install/run (pick one path)

### 1. Quickstart via Make (recommended default)
```bash
git clone https://github.com/intel/edge-ai-suites.git
cd edge-ai-suites/metro-ai-suite/smart-traffic-intersection-agent
make setup     # downloads/prepares models
make deploy    # deploys via Docker Compose
```

### 2. Via the `oep` CLI
```bash
oep install smart-traffic-intersection-agent
# with GPU inference:
oep install smart-traffic-intersection-agent --set VLM_TARGET_DEVICE=GPU
```

### 3. Via Helm (Kubernetes)
```bash
helm install smart-traffic \
  oci://ghcr.io/intel/oep-charts/smart-traffic-intersection-agent \
  --version 2026.1.0-helm \
  --set trafficAgent.env.vlmTargetDevice=GPU
```

### Underlying install handler
`oep install` delegates to `setup.sh` in the app directory:
- Install: `bash setup.sh --setup`
- Start:   `bash setup.sh --run`
- Stop:    `bash setup.sh --stop`
- Clean:   `bash setup.sh --clean`

## Container images used

| Image | Registry | Tag |
|---|---|---|
| smart-traffic-intersection-agent | docker.io/intel | 2026.1.0 |
| live-metrics-service | docker.io/intel | 2026.1.0 |
| ovms (OpenVINO Model Server) | docker.io/openvino/model_server | 2026.1 |

## Deployment artifacts

- Docker Compose file: `metro-ai-suite/smart-traffic-intersection-agent/docker/agent-compose.yaml`
- Env template: `metro-ai-suite/smart-traffic-intersection-agent/docker/.env.template`
- Helm chart: `oci://ghcr.io/intel/oep-charts/smart-traffic-intersection-agent` (version `2026.1.0-helm`)

## Version / changelog

- Current version: `2026.1.0` (app version `1.0.0`)
- 2026-06-27 — Initial catalog publication

## Notes for an AI agent acting on this app

- Treat `VLM_MODEL_NAME` and `VLM_TARGET_DEVICE` as the two most important knobs
  a user is likely to want changed; ask for target device (CPU/GPU/NPU) before
  installing if not specified.
- Prefer the `make setup && make deploy` path for local/dev installs, and the
  Helm path only if the user explicitly mentions Kubernetes.
- Do not hardcode `HUGGINGFACE_TOKEN` — instruct the user to export it as an
  environment variable if a gated model is requested.
- If asked to "install this app," confirm hardware target and whether
  Docker Compose or Kubernetes is desired before running commands.
