<!--
SPDX-FileCopyrightText: (C) 2026 Intel Corporation
SPDX-License-Identifier: Apache-2.0
-->

# POC: Loopback Device Agent Communication

Small proof-of-concept exercising the "Storefront (browser) ↔ local Device
Agent over HTTPS loopback with a cert" pattern described in
[`edge-ai-catalog-design.md`](../edge-ai-catalog-design.md), §3.1, §3.1.1 and
§4.5. It is a scripted simulation for local validation of the mechanics
described in the design, not a production implementation.

Uses the **opaque one-time install-token model** (browser relays only a
short-lived, single-use token; the Device Agent redeems it itself over its
own outbound connection) rather than an earlier KMS-signed-manifest
approach — this keeps the loopback leg simple and avoids needing
asymmetric signing/public-key provisioning to every device.

## What it proves

1. **Loopback-only binding** — Device Agent listens on `127.0.0.1:47100`
   only (never `0.0.0.0`).
2. **Real TLS termination** on that loopback port, using a leaf cert issued
   by a locally generated root CA — standing in for the doc's "pre-installed
   local root CA" (Docker Desktop-style) trust model. The client trusts only
   that CA (`pki/ca.crt`), not the system default trust store.
3. **CORS + Private Network Access (PNA) handling** — `OPTIONS` preflights
   are answered with `Access-Control-Allow-Private-Network: true` and an
   explicit `Access-Control-Allow-Origin` naming the exact Storefront origin.
4. **Strict Origin validation** — any request whose `Origin` header isn't the
   known Storefront origin is rejected with `403`, even for reads.
5. **The full v1 relay sequence (§3.1/§4.5), token model**:
   Browser → Device Agent (`GET /local/system-profile`) → Browser → Catalog
   Service (`POST /install`) → opaque, short-lived, single-use
   `install_token` returned in the same response → Browser → Device Agent
   (`POST /local/install {install_token}`) → **Device Agent redeems the
   token itself**, over its own outbound HTTP(S) call to Catalog Service
   (`GET /install/redeem/{install_token}`) → Catalog Service validates the
   token, marks it consumed, and returns the real install plan directly to
   the Device Agent → Device Agent checks compatibility rules locally →
   hands a "install plan" to a stubbed OEP Installer → status flows back to
   the browser via `GET /local/status`.
6. **Defense in depth** — replaying the same `install_token` a second time
   is rejected, because the token is single-use and the Device Agent's own
   redeem call fails server-side (`401`) — nothing the browser could forge
   or replay grants an install on its own.

## Layout

- `gen_cert.py` — generates `pki/ca.{key,crt}` (the "pre-installed root CA")
  and `pki/agent.{key,crt}` (Device Agent's loopback TLS cert, SAN =
  `localhost` / `127.0.0.1`).
- `device_agent.py` — mock Device Agent: HTTPS server on loopback,
  `/local/system-profile`, `/local/install`, `/local/status`. Redeems
  install tokens itself via an outbound call to the mock Catalog Service.
- `catalog_service.py` — mock Catalog Service: plain HTTP `/install` (issues
  an opaque single-use token) and `/install/redeem/{token}` (validates,
  consumes, returns the real install plan) — stands in for the real
  internet-facing `catalog.intel.com`, not part of the loopback leg.
- `browser_client.py` — simulates the Storefront browser relaying between
  the two, plus two negative-path checks.

## Running it

```bash
python3 gen_cert.py

python3 catalog_service.py &   # mock cloud Catalog Service, :8443
python3 device_agent.py &      # mock local Device Agent, loopback :47100

python3 browser_client.py
```

Expected output: system profile fetched, install token issued, Device Agent
redeems the token and installs "succeeds" against the stubbed OEP Installer
hand-off, status reads back `installed`, and both negative tests (`403`
forged origin, `401` replayed/already-consumed token) pass.

## Known limitations (not covered by this POC)

- **No real browser involved.** PNA preflight behavior, mixed-content
  blocking, and any user-facing permission prompts must still be verified in
  actual Chrome/Edge — the open question flagged in the design doc (§11,
  item 9) about the loopback cert provisioning strategy is not resolved by
  this script.
- Cert trust here is simulated by pointing a Python HTTPS client at a custom
  CA bundle; it does not model installing a root CA into an OS/browser trust
  store during OXM imaging, nor the wildcard-DNS-to-loopback alternative.
- The mock Catalog Service's token store is an in-memory dict with no
  persistence/replication — real implementation should use DynamoDB/Redis
  with TTL, per design doc §9.1.
- OEP Installer, driver/runtime provisioning, and `docker compose up` are
  stubbed with print statements — no real installation happens.
- No CLI (`eaictl`) client is simulated, only the browser-relay path.
