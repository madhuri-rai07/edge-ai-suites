<!--
SPDX-FileCopyrightText: (C) 2026 Intel Corporation
SPDX-License-Identifier: Apache-2.0
-->

# Worked Example: Onboarding `smart-traffic-intersection-agent`

A concrete walkthrough of the **B1 — ISV: Create & Submit an App** flow
(`technical-flows.md`) using a real application from this monorepo:
[`metro-ai-suite/smart-traffic-intersection-agent`](../../metro-ai-suite/smart-traffic-intersection-agent).
Intended as a template/reference for other ISVs onboarding similar
compose-based edge AI apps, and to surface concrete gaps the generic flow
doc doesn't cover.

Source app inspected: `docker/agent-compose.yaml`, `README.md`,
`docs/user-guide/get-started/system-requirements.md`, `chart/`,
`security-results/`, `src/Dockerfile`.

## 0. Pre-work (before touching the Catalog UI)

Findings specific to this app that must be resolved *before* submission:

| Finding | Why it matters | Action |
|---|---|---|
| App ships **both** a compose file (`docker/agent-compose.yaml`) and a Helm `chart/` | Catalog v1 is compose-primary (design doc §4.1); Helm is not a supported deployment_kind yet | Submit the compose file only; park the Helm chart for a future phase |
| Compose references a **vendored nested repo** `deps/metro-vision/...` via `${RI_DIR}`/`${APP_DIR}`, which has its own `LICENSE.txt` | The app isn't self-contained; a third-party license is bundled inside it, distinct from the app's own license | Either inline/vendor cleanly, or explicitly declare `deps/metro-vision` as a third-party dependency with its own license terms surfaced to the SI at install time |
| `collector` service runs `privileged: true`, `pid: host`, and mounts `/sys`, `/dev`, `/proc`, `/run` from the host | Effectively unrestricted host access — far beyond the declared-device-passthrough model (`/dev/dri`, `/dev/accel`) the design assumes (§8 "Image sourcing") | **Likely review blocker.** Flag to the app owner now; either re-architect to drop `privileged`/`pid: host`, or get an explicit written governance exception before submitting |
| `collector` image is `docker.io/intel/vippet-collector:2026.0.0` — pulled directly from Docker Hub | Not on the catalog-hosted registry → weaker gating guarantee (§8) | Declare this image's `source: external_url` at submission; expect an "unscanned/external" flag at review |
| No license file at the app's own root (only nested under `deps/`) | A `license_id` is required to create the app listing (§5 data model) | ISV must register/select a license for the top-level app before `POST /apps` |
| `security-results/` already contains Trivy (image/fs/config), Bandit, CodeQL, and ClamAV reports | These largely satisfy the "test evidence" and vulnerability-scan requirements | Reuse directly — don't regenerate from scratch |

## 1. Create app draft
`POST /apps`
```json
{
  "name": "Smart Traffic Intersection Agent",
  "category": "Cities & Infrastructure",
  "description": "Analyzes traffic scenarios at an intersection: driving suggestions, alerts, and a plug-in interface for other agents.",
  "tags": ["traffic", "vlm", "scenescape", "metro"],
  "org_id": "<isv-org-id>"
}
```
- Upload an icon via `POST /apps/{appId}/assets/icon-upload-url`.
- Register/select a license via `POST /licenses` (see pre-work finding above —
  none exists at the app's own root today).

## 2. Create app version
`POST /apps/{appId}/versions`
```json
{
  "deployment_file_url": "<uploaded docker/agent-compose.yaml>",
  "deployment_kind": "compose",
  "version": "1.0.0"
}
```

## 3. Parse deployment
`POST /apps/{appId}/versions/{versionId}/parse-deployment` extracts 4 services
from `agent-compose.yaml`:

| Service | Role |
|---|---|
| `ovms-service` | OpenVINO Model Server — serves the VLM/inference models |
| `traffic-agent` | The app's own backend + UI (built from `src/Dockerfile`) |
| `live-metrics-service` | WebSocket relay for live system metrics |
| `collector` | Telegraf-based host metrics collector |

It also surfaces the referenced secret `scenescape-ca.pem` (TLS root cert,
mounted at `/app/secrets/certs/scenescape-ca.pem`) as a referenced file
needing upload.

## 4. Set image source per service
`PUT /apps/{appId}/versions/{versionId}/images/{imageId}` for each:

| Service | image_ref (from compose) | source | Notes |
|---|---|---|---|
| `ovms-service` | `openvino/model_server:2026.1` | `external_url` (as-is) or push to hosted registry | Public OpenVINO image; ISV's choice |
| `traffic-agent` | built from `src/Dockerfile` | `hosted_registry` | Preferred — enables click-to-accept gating; see push mechanism below |
| `live-metrics-service` | built from a sibling `live-video-analysis/live-metrics-service` path | `hosted_registry` | Same push mechanism as `traffic-agent` |
| `collector` | `docker.io/intel/vippet-collector:2026.0.0` | `external_url` | Docker Hub image — lower-trust flag applies (§8) |

### How the `hosted_registry` push actually works (concrete, for `traffic-agent`)
The catalog never builds anything itself — it only provisions a private ECR
repo and issues short-lived push credentials for it. The ISV still builds
and pushes the image exactly like any other ECR workflow:

1. **ISV builds the image** themselves, in their own CI or locally — the
   catalog does not run this build:
   ```bash
   docker build -t traffic-agent:1.0.0 ./src
   ```
2. **ISV requests push credentials**:
   `POST /apps/{appId}/versions/{versionId}/images/{imageId}/push-credentials`
   → `{ registry_uri, repository, auth_token, expires_at }` — a short-lived
   ECR auth token scoped to a repo the catalog pre-provisioned, e.g.
   `<catalog-registry>/<isv-org-slug>/smart-traffic-intersection-agent/traffic-agent`.
3. **ISV logs in with the temp token** (standard ECR docker-login pattern):
   ```bash
   echo "<auth_token>" | docker login --username AWS --password-stdin <registry_uri>
   ```
4. **ISV tags and pushes**:
   ```bash
   docker tag traffic-agent:1.0.0 <registry_uri>/<repository>:1.0.0
   docker push <registry_uri>/<repository>:1.0.0
   ```
5. **Catalog detects the push asynchronously** — an ECR EventBridge rule
   fires a webhook back to the catalog, which sets
   `app_version_images.source = hosted_registry`, updates
   `registry_or_url` to the real pushed tag/digest, and queues the async
   vulnerability-scan job (Trivy/ECR native scan). **The ISV never calls an
   explicit "I pushed" API** — this step is event-driven, not
   request/response, which is why step 8 (submit) can be blocked on
   `scan_status: passed` without the ISV needing to poll anything manually
   in between (the Storefront UI polls/displays scan status for them).
6. Same mechanism applies to `live-metrics-service` — separate
   `push-credentials` call, separate repo, same 5 steps.

## 5. Settings (env vars)
`PUT /apps/{appId}/versions/{versionId}/settings` — bulk upsert. Key entries
from `agent-compose.yaml`'s `environment:` block:

| env_key | fill_at_install | is_secret | Notes |
|---|---|---|---|
| `VLM_MODEL_NAME` | true | false | Compute/model choice, SI decides |
| `VLM_TARGET_DEVICE` | true | false | `CPU` default; SI may set `GPU` if iGPU present |
| `HF_TOKEN` *(not in compose today — recommended addition)* | true | **true** | Required per `system-requirements.md` to pull VLM model weights; currently undeclared as a setting in the compose file — flag to the ISV to add it explicitly rather than relying on an ambient env var |
| `INTERSECTION_NAME` | true | false | Site-specific |
| `INTERSECTION_LATITUDE` / `INTERSECTION_LONGITUDE` | true | false | Site-specific |
| `MQTT_HOST` | false | false | Defaults to the bundled broker; fine as shipped |
| `WEATHER_MOCK`, `HIGH_DENSITY_THRESHOLD`, etc. | false | false | Sensible defaults per compose file |

## 6. Hardware requirements
From `docs/user-guide/get-started/system-requirements.md`:
```json
{
  "cpu": "Intel Core i5 or equivalent (Core Ultra 2/3 w/ iGPU or Xeon recommended)",
  "memory_gb": 16,
  "gpu": "Intel integrated GPU (optional, for accelerated VLM inference)",
  "disk_gb": 50
}
```
Declare `/dev/dri` device passthrough (already present in the compose file
for `ovms-service`) so the Device Agent/OEP Installer wires it through
correctly.

## 7. Evidence
`POST /apps/{appId}/versions/{versionId}/evidence` — point at the existing
`security-results/` bundle:
- `trivy-image-smart-traffic-intersection-agent.{html,json}`
- `trivy-fs-smart-traffic-intersection-agent.{html,json}`
- `trivy-config-smart-traffic-intersection-agent.{html,json}`
- `bandit-report-smart-traffic-intersection-agent.{html,json}`
- `codeql-python-smart-traffic-intersection-agent.{csv,json}`
- `clamav-smart-traffic-intersection-agent-*.txt`

This mostly satisfies the "tested-on hardware"/vulnerability evidence
requirement without regenerating anything — a strong argument for ISVs in
this monorepo whose CI already produces these artifacts to just carry them
forward.

## 8. Submit for review
`POST /apps/{appId}/versions/{versionId}/submit` → `pending_review`, gated on:
- All required fields present (name, category, license, hardware_requirements).
- Hosted-registry images (`traffic-agent`, `live-metrics-service`) showing
  `scan_status: passed`.

**Expected outcome given the findings above: this submission should NOT pass
review as-is.** The `collector` service's `privileged: true` + `pid: host` +
full `/sys /dev /proc /run` host mounts is a governance-level blocker under
the current design's device-passthrough model, independent of whether the
scans themselves come back clean. Recommend resolving that with the app
owner *before* formal submission, not discovering it at C1 review time.

---

# Worked Example: Installing `smart-traffic-intersection-agent` (flow D2)

Continuing the example, assuming the app has cleared review (i.e. the
`collector` privileged-container issue above has been resolved and
`app_versions.status = listed`). This walks the **D2 — SI: Install an
application** flow (`technical-flows.md`) with this app's real shape,
using the token-based install model (§4.5).

## Preconditions
- SI is signed in to the Storefront, browsing from the edge device they
  intend to install onto (this device is the traffic-intersection edge box
  itself — an Intel Core Ultra or Xeon box with an iGPU, per
  `system-requirements.md`).
- Device Agent is already running on that device (loopback `127.0.0.1:<port>`).

## 1. SI clicks "Install on this device"
On the app detail page for "Smart Traffic Intersection Agent" v1.0.0.

## 2. Storefront queries the local Device Agent for a SystemProfile
`GET https://127.0.0.1:<port>/local/system-profile` (loopback) →
```json
{
  "os": "Ubuntu 22.04",
  "cpu": "Intel Core Ultra 7",
  "gpu": "Intel Arc iGPU",
  "memory_gb": 32,
  "edge_pack_version": "2026.1.0"
}
```

## 3. Storefront calls Catalog Service
`POST /install {app_version_id, system_profile}`.

- **Compatibility pre-check (advisory)**: `memory_gb=32 ≥ 16` (min) ✓,
  CPU matches "Core Ultra" tier ✓. Passes.
- **License gate**: this SI's org hasn't accepted this app_version's
  license yet → Catalog Service returns
  `{ requires_acceptance: true, license_id, license_text_url }` instead of
  a token.
  - Storefront shows the EULA (and, per the pre-work note above, should
    also surface the nested `deps/metro-vision` third-party license terms
    if that dependency wasn't fully inlined during onboarding).
  - SI clicks "Accept" → `POST /apps/{id}/versions/{v}/accept-license` →
    writes `license_acceptances` row.
  - Storefront re-calls `POST /install` → now passes the gate → Catalog
    Service issues `{ install_token, expires_in: 120 }`.

## 4. Storefront hands the token to the Device Agent
`POST https://127.0.0.1:<port>/local/install {install_token}` (loopback).

## 5. Device Agent redeems the token itself
`GET /install/redeem/{install_token}` — own outbound HTTPS call to Catalog
Service (ordinary public-CA TLS, no PKI needed). Catalog Service validates,
consumes the token, and returns the install plan:
```json
{
  "app_version_id": "smart-traffic-intersection-agent@1.0.0",
  "compose_url": "<pre-signed S3 URL for agent-compose.yaml>",
  "images": [
    { "service_name": "ovms-service", "image_ref": "openvino/model_server:2026.1", "pull_token": null },
    { "service_name": "traffic-agent", "image_ref": "<catalog-ecr>/.../traffic-agent:1.0.0", "pull_token": "<ecr-temp-token>" },
    { "service_name": "live-metrics-service", "image_ref": "<catalog-ecr>/.../live-metrics-service:1.0.0", "pull_token": "<ecr-temp-token>" },
    { "service_name": "collector", "image_ref": "docker.io/intel/vippet-collector:2026.0.0", "pull_token": null }
  ],
  "settings": [
    { "env_key": "VLM_TARGET_DEVICE", "value": "GPU" },
    { "env_key": "HF_TOKEN", "value": "<encrypted>" },
    { "env_key": "INTERSECTION_NAME", "value": "" },
    { "env_key": "INTERSECTION_LATITUDE", "value": "" },
    { "env_key": "INTERSECTION_LONGITUDE", "value": "" }
  ],
  "license_terms_url": "...",
  "compatibility_rules": { "min_ram_gb": 16, "gpu_optional": true }
}
```
Device Agent independently re-checks the SystemProfile against
`compatibility_rules` **locally**.

## 6. Missing site-specific settings → `needs_input`
`INTERSECTION_NAME`/`LATITUDE`/`LONGITUDE` and `HF_TOKEN` are typically not
known ahead of time (per the pre-work note, `HF_TOKEN` isn't in the compose
file today and must be added as a declared setting). Device Agent responds
`needs_input: [...]` to the Storefront, which prompts the SI for:
- Intersection name and GPS coordinates (site-specific — this device's
  physical location).
- A Hugging Face access token (to pull the VLM model weights).

Storefront re-calls `/local/install` with these merged in (a fresh
`install_token` is issued for this retry, since the first was consumed).

## 7. Device Agent hands the resolved plan to OEP Installer
OEP Installer:
- Pulls `ovms-service`, `collector` from their external registries as-is.
- Pulls `traffic-agent`, `live-metrics-service` from the catalog ECR using
  the temp pull tokens.
- Writes the `scenescape-ca.pem` secret file (declared during onboarding
  step 3) to `/app/secrets/certs/scenescape-ca.pem`.
- Renders all resolved settings as environment variables.
- Runs `docker compose up -d` with `/dev/dri` passthrough for
  `ovms-service` (GPU-accelerated VLM inference).
- **Flag**: if the `collector` service's `privileged: true`/`pid: host`
  configuration wasn't actually resolved before listing, this is also where
  it would concretely manifest — OEP Installer would need to grant the
  container privileged host access, which most real device security
  postures (and probably the SI's own IT policy) would reject or require a
  manual override for. This is the practical, install-time consequence of
  the review-time blocker flagged above.

## 8. Status flows back
OEP Installer exit code → Device Agent → Storefront (polls
`GET /local/install/{job_id}/status` over loopback) → UI shows "Installing...
→ App available". No `launch_url` field exists yet in the data model (open
item, see `technical-flows.md`); SI would need to know the UI is on
`AGENT_UI_PORT` (7860) and the backend on `AGENT_BACKEND_PORT` (8081) from
the app's own docs until that's added.

## 9. Telemetry
Storefront optionally posts `POST /install/{install_token}/telemetry
{action: "install", result: "success"}` → aggregate-only, no device identity
retained.

## TP1 fallback
Same as the generic D2 fallback: SI runs `oep-cli install --token
<install-token>` manually from a terminal on the device, after accepting
the license in-browser.

## Cross-references
- Generic flow steps: `technical-flows.md` §B1 (onboarding), §D2 (install).
- Architecture/data-model context: `edge-ai-catalog-design.md` §4.2 (ISV
  onboarding), §4.5 (install orchestration, token model), §5 (data model),
  §8 (image sourcing / compatibility).
- API contract: `openapi/catalog-service.openapi.yaml` (`/apps`, `/apps/{id}
  /versions`, `.../submit`, `/install`, `/install/redeem/{token}`) and
  `openapi/device-agent.openapi.yaml` (`/local/install`).
- Loopback/cert mechanics: `edge-ai-catalog-design.md` §3.1.1;
  `poc-loopback-device-agent/` for a working scripted simulation.

