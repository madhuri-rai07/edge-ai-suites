# SPDX-FileCopyrightText: (C) 2026 Intel Corporation
# SPDX-License-Identifier: Apache-2.0

# Edge AI Catalog — Local Reference Implementation

A runnable, end-to-end reference implementation of the architecture in
`../edge-ai-catalog-design.md` and `../technical-flows.md`, built to run
entirely locally with **zero real cloud infrastructure and zero real
credentials**. It exists to validate the design (does the token-based
install flow actually work end-to-end? does the 2-screen onboarding wizard
actually produce a submittable app?), not to be deployed as-is.

## What's real vs. mocked

| Piece | Status | Notes |
|---|---|---|
| Data model (§5) | **Real** | SQLAlchemy models, 1:1 with the ER diagram in the design doc |
| Onboarding validation/state machine (§6) | **Real** | draft → pending_review → listed/sent_back/rejected, enforced server-side |
| Docker-compose parsing (flow B1 step 4) | **Real** | actual YAML parsing, extracts images/env vars/volume-mounted files |
| Install-token issue/redeem (§4.5, flow D2) | **Real logic**, mocked store | opaque/single-use/short-lived semantics fully implemented; stored in a SQLite table instead of DynamoDB/Redis TTL |
| Device Agent loopback + TLS + CORS/PNA + Origin validation (§3.1.1) | **Real** | genuine HTTPS server, genuine self-signed CA, genuine browser-facing preflight handling |
| Auth (flow A1) | **Mocked** | `X-Debug-User-Email`/`X-Debug-Role` headers instead of SSO/Cognito — see `catalog-service/app/auth.py` docstring |
| S3 uploads (icons, compose files, evidence) | **Mocked** | local `/dev/storage/{key}` instead of pre-signed S3 URLs — see `catalog-service/app/storage.py` |
| ECR push + EventBridge webhook + vuln scan | **Mocked** | fake credentials, and a manual `/dev/simulate-ecr-push/{imageId}` endpoint stands in for the real async webhook — see `catalog-service/app/registry.py` |
| OEP Installer / `docker compose up` | **Not implemented** | Device Agent writes the resolved `.env` + install plan to disk; actually running containers is left as an extension point (see `device_agent.py`'s `render_and_apply_plan`) |

Every mocked module has a docstring explaining exactly what it stands in
for and what would need to change for production (mostly: swap a function
body for a real AWS SDK call; no caller-facing contract changes).

## Layout

```
impl/
  catalog-service/   # Tier 2 cloud API (FastAPI) — see openapi/catalog-service.openapi.yaml
    app/
    tests/           # pytest, full B1->C1->D1->D2 flow + negative cases
  device-agent/      # Tier 3 local runtime — see openapi/device-agent.openapi.yaml
    device_agent.py
    gen_cert.py      # generates the loopback TLS cert (reused from ../poc-loopback-device-agent)
  storefront/        # minimal static HTML/JS UI exercising B1 (2-screen wizard), C1, D1/D2
  run-all.sh         # starts all three together
```

## Running it

```bash
cd impl
./run-all.sh
```

This creates a venv (first run only), generates the Device Agent's TLS
cert, starts:
- Catalog Service on `http://127.0.0.1:8000`
- Device Agent on `https://127.0.0.1:47100` (loopback only)
- Storefront static UI on `http://127.0.0.1:5500`

and seeds three demo users (one ISV, one Admin, one SI — see
`catalog-service/app/seed.py`). Open `http://127.0.0.1:5500`, use the role
switcher at the top to act as each persona, and walk through:
1. **ISV Onboarding tab** — fill Screen 1, upload any `docker-compose.yml`,
   review Screen 2 (auto-extracted images/settings), submit.
2. **Admin Review tab** — approve the submitted version.
3. **Catalog tab** — see it listed, click Install; watch the log show the
   token being issued, relayed to the Device Agent, and redeemed by the
   Device Agent's own outbound call.

### Known limitation: the loopback TLS cert isn't in your browser's trust
store yet. The Device Agent presents a cert signed by a locally-generated
root CA (`device-agent/pki/ca.crt`) — per design doc §3.1.1, in production
this CA would be pre-installed by OEP Installer/OXM imaging. For manual
testing, open `https://127.0.0.1:47100/local/status` directly once and
accept the browser's security exception before using the Catalog tab's
Install button — this exact gap was flagged earlier in this project's
design discussion and remains open (see `edge-ai-catalog-design.md` §11).

## Running the automated tests

```bash
cd impl/catalog-service
source ../.venv/bin/activate
python -m pytest tests/ -v
```

Covers: full B1 (onboarding, including the pending-scan submit block and
the simulated ECR webhook unblocking it) → C1 (review/approve) → D1
(discover) → D2 (license gate, token issue, outbound redeem, replay
rejection, telemetry), plus a couple of negative-path unit tests.

The Device Agent's loopback/TLS/CORS/Origin-validation behavior was
additionally verified manually against the real running Catalog Service
(forged Origin → 403, bogus/replayed token → 401, real install → 200) —
see this session's transcript for the exact commands; it isn't (yet)
wrapped in an automated test because it requires two live TLS/HTTP
servers rather than an in-process TestClient.

## Path to production

None of this is meant to be deployed. To move toward production per
§9.1 of the design doc:
1. Point `CATALOG_DB_URL` at RDS Postgres (SQLAlchemy models are already
   Postgres-compatible — no SQLite-specific features used).
2. Replace `storage.py`'s local-file stand-in with real S3 pre-signed URLs.
3. Replace `registry.py`'s fake credentials with real
   `ecr.get_authorization_token` calls + a real EventBridge rule +
   webhook handler + Fargate/Trivy scan worker.
4. Replace `auth.py`'s header-based shim with real SSO/Cognito + signed
   session cookies (every router already depends only on the
   `CurrentUser` dataclass, so this is a single-file swap).
5. Replace the in-memory/SQLite `install_tokens` table with DynamoDB/Redis
   with a native TTL, exactly as described in §9.1.
6. Implement the real OEP Installer hand-off in `device_agent.py`'s
   `render_and_apply_plan` (currently a documented extension point).
