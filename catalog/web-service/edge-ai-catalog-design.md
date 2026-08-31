# Edge AI Catalog — Technical Design Draft (MVP / Tech Preview)

> **Revision note:** This revision reconciles the design with the authoritative
> "Edge AI Catalog MVP – Persona View" doc and "Edge AI App Catalog" architecture
> deck. Key corrections from the previous draft are called out inline as
> **[CORRECTED]**. See §11 for a full list of what changed and why.

## 1. Goals & Scope
The Open Edge Catalog is a cloud service (API + data store) consumed by a **web
storefront** and a **CLI (`eaictl`)**, where ISVs publish edge AI applications,
Intel reviews and governs them, and System Integrators (SIs) discover and deploy
them onto edge devices with near one-click installation. OXMs/OEMs ship devices
pre-provisioned to be "catalog-ready." Delivery is rolled out in iterative **Tech
Previews (TP1, TP2, TP3...)** with increasing automation.

Confirmed scope for this revision: external ISVs upload apps via the web app;
SIs discover and click-install; **download/pull of app artifacts is gated per-SI
by a recorded click-to-accept (license) event**; SSO login; backend manages app
metadata, artifacts, and container images on **AWS** (Tier 2 implementation
choice — see §9).

**v1 scope decision — [CONFIRMED]:** No fleet management in this first version.
The Storefront is a single website **hosted at an Intel domain**; the SI opens
it **from a browser running on the edge device itself** (not a remote fleet
console). All install actions are scoped to *that one device, in that one
browser session* — the Storefront talks to Catalog Service over normal HTTPS,
and separately talks to the **local Device Agent via loopback** to trigger the
actual install on click. There is no cloud-to-device leg, no device inventory,
and no cross-device dashboard in v1 — see §3.2 and §4.5 (updated).

## 2. Personas

| Persona | Goal | Key capabilities |
|---|---|---|
| **OXM/OEM** *(new — [CORRECTED])* | Ship Intel Edge AI devices "catalog-ready" | Install Ubuntu + Edge Pack (which declares Device Agent + OEP Installer as hard dependencies from an Intel APT repo, or a prebuilt image); configure catalog URL + signing key in the image |
| **ISV** | Get apps listed & adopted | Onboard app, update app, track status via dashboard |
| **SI** (may also be OXM) | Deploy apps to edge devices | Prep device (fallback if OXM didn't), discover apps, install/upgrade/uninstall, view local installed-app status |
| **Intel Admin** | Govern catalog quality & access | Approve/reject/send-back, suspend/resume/remove listings, invite users & assign roles |

A user may hold multiple roles (e.g. an SI who also publishes apps). Intel Admin
is an Intel-only role.

## 3. High-Level Architecture — 3 Tiers *(replaces prior architecture — [CORRECTED])*

### 3.1 v1 flow — no fleet management, single-device browser session *(new — [CONFIRMED])*

```
                      Edge Device (SI's browser + local runtime)
   ┌──────────────────────────────────────────────────────────────────┐
   │  Browser: Storefront SPA (loaded from catalog.intel.com)          │
   │       │                                    │                     │
   │       │ HTTPS (normal internet)             │ HTTPS loopback (cert)│
   │       ▼                                    ▼                     │
   │  ┌───────────────────┐              ┌───────────────────────┐    │
   │  │ Catalog Service     │◄────────────┤ Device Agent (local)    │    │
   │  │ (cloud, Tier 2)     │  browser     │  - answers SystemProfile│   │
   │  │ - listings, review  │  relays an   │    query from browser   │   │
   │  │ - issues opaque      │  opaque      │  - receives token from  │   │
   │  │   one-time install   │  install     │    browser, redeems it  │   │
   │  │   token on /install   │  token       │    itself (outbound)    │   │
   │  │   request             │─────────────►│  - hands install plan  │   │
   │  │ - redeem endpoint     │◄─────────────┤    to OEP Installer     │   │
   │  │   returns real plan   │  agent's OWN │                         │   │
   │  │   directly to agent   │  outbound    │                         │   │
   │  │   (normal outbound     │  HTTPS call  │                         │   │
   │  │   HTTPS, no PKI)       │  (redeem)   │                         │   │
   │  └───────────────────┘              └──────────┬──────────────┘    │
   │                                                  │ install plan       │
   │                                       ┌──────────▼──────────────┐    │
   │                                       │  OEP Installer            │    │
   │                                       │  (existing bootstrap tool)│   │
   │                                       └──────────┬──────────────┘    │
   │                                                  │ docker compose up │
   │                                       ┌──────────▼──────────────┐    │
   │                                       │     App Containers        │    │
   │                                       └───────────────────────┘    │
   └──────────────────────────────────────────────────────────────────┘
```

For v1, **the browser is the only bridge between cloud and device** — Catalog
Service never needs inbound reachability to the device. Sequence:
1. Browser (Storefront) loads from the Intel-hosted domain.
2. Browser asks the local Device Agent (loopback) for a SystemProfile.
3. Browser calls Catalog Service `POST /install {app_version_id, system_profile}`.
4. Catalog Service does the license/entitlement/compatibility checks and
   returns a **short-lived, single-use opaque install token** to the browser
   (same HTTPS response) — **not** the install payload itself.
5. Browser hands the token to the Device Agent over the same loopback
   connection (`POST /local/install {install_token}`).
6. Device Agent redeems the token itself, over its own normal **outbound**
   HTTPS connection to Catalog Service (`GET /install/redeem/{install_token}`)
   — ordinary public-CA-trusted TLS, no custom signing/PKI involved. Catalog
   Service validates the token (unexpired, unused), marks it consumed, and
   returns the real install plan (compose file URL, image refs, settings,
   license terms, compatibility rules) directly to the Device Agent. Device
   Agent checks the SystemProfile it already has against the plan's
   compatibility rules **locally**, then hands the plan to the OEP Installer.
7. OEP Installer pulls artifacts and runs `docker compose up`.
8. Device Agent reports status back to the browser (loopback); browser shows
   "App available" and optionally posts an aggregate install-telemetry event
   to Catalog Service — no per-device record is created or retained.

This resolves the open transport question from the prior revision (§11.3 #1
below) for v1: **no WebSocket/long-poll/direct cloud→agent connection is
needed** — the browser relay is sufficient because the user is physically
using the device they're installing onto.

### 3.1.1 How "HTTPS loopback with a cert" technically works *(new — detail)*

This pattern (browser page ↔ local daemon) is used by tools like Docker
Desktop, Plex, and Spotify Connect. It requires solving three distinct browser
security constraints, not just "call localhost":

**a) Device Agent binds only to loopback.** It runs an HTTPS server on
`https://127.0.0.1:<fixed-port>` (e.g. `47100`), bound to the loopback
interface only — never `0.0.0.0`. No firewall rule or NAT traversal is
involved; nothing external can reach this port. This is precisely what makes
"no cloud-to-device inbound connection required" true: the cloud never talks
to the device — only the browser, already running *on* that same device,
talks to a socket on that machine.

**b) It must be HTTPS, not HTTP, and the cert must be browser-trusted.** The
Storefront page is served over HTTPS from `catalog.intel.com`; browsers block
**mixed content**, so an HTTPS page cannot call a plain `http://` endpoint —
Device Agent must terminate real TLS locally. A naive self-signed cert for
`127.0.0.1` triggers browser warnings and `fetch()` rejection, so one of two
provisioning strategies is needed (decided once, during device setup — not
something the browser session can bootstrap itself):
- **Wildcard-DNS-to-loopback + real public CA cert** (the approach Plex uses
  with `*.plex.direct`): register something like
  `*.local.catalog.intel.com` in public DNS resolving to `127.0.0.1`, and
  issue Device Agent a real CA-signed cert for that hostname during
  provisioning. The browser sees a normal, publicly trusted cert with no
  warnings, even though the connection never leaves the loopback interface.
- **Pre-installed local root CA** (Docker Desktop's approach): install a
  private root CA into the OS/browser trust store during OXM imaging or OEP
  Installer setup; Device Agent presents a cert signed by that CA for
  `localhost`. Ties naturally into the existing Edge Pack/Device Agent
  provisioning step (§10).

**c) Browser CORS + Private Network Access (PNA) policy.** Even with a
trusted cert, Chrome/Edge treat a request from a public page to a private
address (`127.0.0.1`) as a **Private Network Access** request: the browser
sends a preflight with `Access-Control-Request-Private-Network: true`, and
Device Agent must answer with `Access-Control-Allow-Private-Network: true`
plus CORS headers naming the exact calling origin (`https://catalog.intel.com`).
Depending on browser version this may also trigger a user-facing permission
prompt — PNA is an evolving spec and must be explicitly tested against the
two browsers named in the source deck (Chrome, Edge).

**d) Defense-in-depth on the Device Agent side.** Since the loopback port is
technically reachable by any local process/tab on that machine, Device Agent
should still (i) validate the `Origin` header strictly equals the known
catalog domain, and (ii) never act on a bare token's *contents* — the token
is opaque and meaningless on its own; the actual install plan only exists
after the Device Agent independently redeems it over its own outbound HTTPS
connection to Catalog Service (§4.5). So even a malicious local page hitting
the loopback port can, at worst, get the Device Agent to redeem a token it
doesn't itself possess — it cannot forge or replay a valid install (tokens
are single-use and short-lived server-side).

**Illustrative sequence:**
```
Browser (https://catalog.intel.com)
   │ fetch("https://127.0.0.1:47100/local/system-profile", {mode:"cors"})
   │  — TLS trusted (via DNS-trick cert or pre-installed root CA)
   │  — PNA preflight satisfied by Device Agent's CORS headers
   ▼
Device Agent (127.0.0.1:47100, loopback-only)
   │ validates Origin header, responds with SystemProfile
   ▼
Browser → POST /install to Catalog Service (normal internet) → opaque
          short-lived install_token (not the install payload)
Browser → POST {install_token} to Device Agent over the same loopback
          HTTPS connection
Device Agent → GET /install/redeem/{install_token} to Catalog Service
          (normal OUTBOUND internet, ordinary public-CA TLS — no PKI
          bootstrapping needed) → real install plan returned directly
Device Agent verifies plan's compatibility rules locally → hands plan to
          OEP Installer
```

### 3.2 Full 3-tier component view (target state, includes future Federation)

```
 Tier 1 — Catalog UI/UX              Tier 2 — Catalog Cloud Service           Tier 3 — Edge Runtime
┌───────────────────────┐          ┌─────────────────────────────────┐     ┌───────────────────────────┐
│  Storefront (browser  │  HTTPS   │      Catalog Service (cloud)     │     │   Device Agent            │
│  SPA)                 │◄────────►│  REST API + MCP | DB | Container │     │   - reports SystemProfile │
│                       │  Catalog │  Registry | Hosted Artifacts     │     │   - redeems install token │
│  CLI (`eaictl`)       │  API     │                                   │     │     directly (outbound)   │
└──────────┬────────────┘          └───────────────┬─────────────────┘     │   - hands install plan to │
           │  loopback HTTPS (cert)                 │ (future: direct       │     OEP Installer         │
           │  SystemProfile, install trigger token   │  cloud→agent leg,     │   - manages app lifecycle │
           └─────────────────────────────────────────┼  not needed for v1) ─►│                           │
                                                       │                      └──────────┬────────────────┘
                                          Federation   │                                 │ install plan
                                       (signed indexes,│                      ┌──────────▼────────────────┐
                                          future)      │                      │   OEP Installer            │
                                    ┌──────────────────▼──────┐               │   (existing module/profile │
                                    │  Partner Catalog Services │             │    bootstrap engine)      │
                                    └────────────────────────┘               └──────────┬────────────────┘
                                                                                          │ pulls images, runs
                                                                                          ▼ docker compose
                                                                              ┌────────────────────────────┐
                                                                              │      App Containers        │
                                                                              └────────────────────────────┘
```

**Tier 1 — Catalog UI/UX**: Storefront (browser SPA) and CLI `eaictl`, both
first-class clients talking to the Catalog Service over HTTPS/REST/MCP, and to
the local Device Agent over **HTTPS loopback with a cert** for system profiling
and passing along the opaque install token.

**Tier 2 — Catalog Cloud Service**: REST API + MCP, Catalog DB, Container
Registry, Hosted Artifacts, and (future) Federation with Partner Catalogs via
signed indexes. This is the tier implemented on AWS (§9).

**Tier 3 — Edge Runtime**: **Device Agent** (reports system profile, redeems
install tokens directly with Catalog Service over its own outbound HTTPS
connection, orchestrates app lifecycle) **and the existing OEP
Installer** (module/profile-based bootstrap engine — the same tool reviewed
separately in this workstream) which performs the actual dependency/app
installation once handed the install plan by the Device Agent. **[CORRECTED]** —
the previous draft conflated these into one generic "device agent that runs
docker compose"; the real design keeps them as two distinct, collaborating
components, and Tier 3 still depends on the existing OEP Installer's
capabilities/limitations (see §11.2).

### 3.3 Key design decisions (carried over verbatim from source deck)
- Base system = Edge Pack + OEP Installer + Device Agent + config. First choice:
  OXM images this. Fallback: SI runs install scripts on top of Ubuntu.
- One-click install uses **HTTPS loopback with a cert** to talk to the local
  Device Agent — no cloud-to-device inbound connection is required for this leg.
- **There is no fleet management fused into the catalog.** Individual devices
  are **not** persistently known to the catalog — the catalog only knows OXMs,
  ISV/SI/Intel user accounts, and org-level system configurations.
  **[CORRECTED]** — the prior draft's persistent `devices` table with
  enrollment/heartbeat contradicts this; see §5 for the revised data model.
- The catalog **"challenges" (probes) the Device Agent live** each time to learn
  the system profile and show relevant install options — not a stored device
  inventory.

## 4. Core Services (Tier 2)

### 4.1 Identity & Access Service
- OIDC integration with Intel SSO (authorization code flow), or Cognito
  federated with Intel IdP (AWS implementation, §9).
- Invitation/allowlist-based authorization: only pre-invited emails complete
  sign-in; unauthorized users are turned away at sign-in.
- RBAC: role = {OXM, ISV, SI, ADMIN}, many-to-many per user/org.

### 4.2 Catalog Service
- Browse/search/filter Listed apps by category, ISV, geography, tags.
- Serves app detail pages: description, hardware validation, license, versions.
- Exposes both **REST API and MCP** for programmatic/agent consumption
  *(new — [CORRECTED])*.

### 4.3 Onboarding / Submission Service (ISV-facing)
- Wizard: create draft app → app_version → upload deployment file.
- MVP primarily targets a **single Docker Compose file**; bare-metal executable
  packaging is a stated target category but out of scope for TP1
  *(new nuance — [CORRECTED])*.
- **Compose parser** extracts referenced images, volumes/config/data files, and
  env vars ("settings"); ISV sets defaults or marks some `fill_at_install=true`.
- **Image sourcing flexibility**: ISV may either push images to the catalog's
  hosted registry, **or provide a reference URL** to an externally hosted image
  *(new — [CORRECTED]; previous draft assumed push-to-registry only)*.
- Hardware requirements (CPU/GPU/NPU, memory) + tested-on proof upload; ISV must
  validate the app on target hardware prior to uploading (future: automated via
  an OE compatibility lab).
- On submit: immutable `app_version` snapshot, status → `pending_review`.

### 4.4 Review / Workflow Service (Intel Admin-facing)
- State machine (§6) driving `app_version.status`/`app.status`.
- Filterable dashboard (by ISV, status, vertical).
- Approve → Listed; Send back (comments) → ISV; Reject → not listed.
- Suspend/Resume/Remove available any time on Listed apps (reasons out of scope
  of this document, owned by catalog governance).

### 4.5 Install Orchestration (v1: browser-triggered, single-device, no fleet) *(rewritten — [CONFIRMED])*
No persistent device registry. The Storefront browser, running on the same
edge device the SI is installing onto, only *triggers* the install — it never
carries the actual install payload (compose file, image refs, settings). The
Device Agent fetches that itself directly from Catalog Service, over its own
normal **outbound** HTTPS connection (ordinary public-CA trust, no custom
PKI/signing needed) — see §3.1 for the full sequence:
1. Storefront queries the local **Device Agent via loopback** for a fresh
   **SystemProfile** (hardware, OS, Edge Pack version).
2. Storefront calls Catalog Service: `POST /install {app_version_id, system_profile}`.
3. Catalog Service does the license/entitlement/compatibility checks and
   returns a **short-lived, single-use opaque install token** (not the
   install payload) **in the same HTTPS response** to the Storefront.
4. Storefront hands the token to the Device Agent over the loopback
   connection (`POST /local/install {install_token}`).
5. Device Agent redeems the token itself — `GET /install/redeem/{install_token}`
   over its own outbound HTTPS call to Catalog Service. Catalog Service
   validates the token (unexpired, unused), marks it consumed, and returns
   the real install plan (compose file URL, image refs, settings, license
   terms, compatibility rules) directly to the Device Agent. Device Agent
   checks the SystemProfile against the plan's compatibility rules
   **locally** before proceeding.
6. Device Agent provisions prerequisites (drivers, container runtime, udev
   rules) if needed, then hands the install plan to the **OEP Installer**.
7. OEP Installer pulls images from the registry (or the ISV-provided URL),
   renders/injects settings, and runs `docker compose up` with declared device
   passthrough.
8. Status flows back: OEP Installer → Device Agent → Storefront (loopback) →
   user ("App available"); Storefront optionally posts an aggregate
   install-telemetry event to Catalog Service.
- **Upgrade/Uninstall**: same browser-relayed flow; Device Agent instructs OEP
  Installer to stop/remove; no central "installations" row to clean up.
- **View installed apps / health**: served **locally** by the Device Agent
  (via loopback) to whichever browser/CLI is currently open on that device —
  not a central cross-device fleet dashboard.
- Aggregate counters shown on ISV/Admin dashboards ("downloads", "installs")
  are recorded as **anonymous/aggregate telemetry events** keyed by
  `app_version_id` + requesting org only — not tied to a persistent device
  identity, preserving the v1 "no fleet management" decision.
- **CLI (`eaictl`) note**: the CLI plays the same relay role as the browser
  when used instead of/alongside the Storefront — it also runs on the device
  and talks to the local Device Agent over loopback.

### 4.6 Notification Service
- Email/webhook on: submission received, sent-back, approved, rejected,
  suspended, install/upgrade/uninstall success or failure.

### 4.7 Audit / Compliance Service
- Immutable log of every admin action, license acceptance, and role change.

### 4.8 Federation Service *(new, future/out-of-scope for TP — [CORRECTED])*
- Exchanges **signed indexes** with Partner Catalog Services (other fully
  hosted Intel-partner app stores). Explicitly marked "out of scope for Tech
  Preview" in source material; included here as a placeholder so Tier 2's API
  surface doesn't need breaking changes later.

## 5. Data Model (simplified ER) *(revised — [CORRECTED]: no device registry)*

```
organizations(id, name, org_type[OXM|ISV|SI|INTEL])
users(id, sso_subject_id, email, name, created_at)
user_roles(user_id, role[OXM|ISV|SI|ADMIN], org_id)
invitations(id, email, role, org_id, invited_by, status, expires_at)

apps(id, isv_org_id, name, category, description, tags[], icon_url,
     license_id, status[draft|pending_review|listed|sent_back|rejected|suspended|removed],
     created_at, updated_at)

app_versions(id, app_id, version, deployment_file_url, deployment_kind[compose|baremetal],
             status, hardware_requirements(jsonb), test_evidence_url,
             submitted_at, reviewed_at, reviewer_id, review_comments)

app_version_images(id, app_version_id, service_name, image_ref,
                    source[hosted_registry|external_url], registry_or_url,
                    requires_pull_secret)

app_version_settings(id, app_version_id, env_key, default_value, is_secret,
                      fill_at_install boolean, description)

licenses(id, title, text_url, version)

license_acceptances(id, user_id, org_id, app_version_id, license_id,
                     accepted_at, ip_address)   -- gates artifact download, see §9.2

review_events(id, app_version_id, actor_id, action[approve|send_back|reject|suspend|resume|remove],
              comments, created_at)

-- NOTE: no persistent `devices` or `installations` fleet tables, per the
-- explicit "no fleet management" design decision. Install/upgrade/uninstall
-- state lives on the edge device (Device Agent local state), not centrally.

install_telemetry_events(id, app_version_id, org_id, action[install|upgrade|uninstall],
                          result[success|failure], occurred_at)
  -- anonymous/aggregate only; powers "downloads/installs" counters, not fleet tracking

audit_logs(id, actor_id, action, entity_type, entity_id, metadata(jsonb), created_at)
```

## 6. App Lifecycle State Machine

```
draft --submit--> pending_review
pending_review --approve--> listed
pending_review --send_back(comments)--> sent_back --resubmit--> pending_review
pending_review --reject--> rejected
listed --suspend--> suspended --resume--> listed
listed --remove--> removed
suspended --remove--> removed
```
Only `listed` apps are installable by SIs. An ISV update always creates a new
`app_version` in `pending_review`; the previously listed version stays
installable until the new one is approved.

## 7. Key API Surface (`/api/v1`, REST + MCP)

**Auth**
- `GET /auth/login` → redirect to Intel SSO / Cognito
- `GET /auth/callback`
- `GET /me` → profile, roles, orgs

**ISV**
- `POST /apps` / `PUT /apps/{id}`
- `POST /apps/{id}/versions` (upload compose/baremetal deployment file)
- `POST /apps/{id}/versions/{v}/parse-deployment` → extracted images/settings/volumes
- `PUT /apps/{id}/versions/{v}/settings`
- `POST /apps/{id}/versions/{v}/evidence`
- `POST /apps/{id}/versions/{v}/submit`
- `GET /isv/dashboard`
- `DELETE /apps/{id}` (delist)

**Admin**
- `GET /admin/reviews?status=pending_review&isv=`
- `POST /admin/reviews/{version_id}/approve|send-back|reject`
- `POST /admin/apps/{id}/suspend|resume`
- `DELETE /admin/apps/{id}`
- `POST /admin/invitations`
- `PUT /admin/users/{id}/roles`

**SI (v1: browser triggers, Device Agent fetches directly, no device registry)**
- `GET /catalog?category=&search=&isv=&geo=`
- `GET /catalog/apps/{id}`
- `POST /install {app_version_id, system_profile}` → returns an opaque,
  short-lived, single-use `install_token` synchronously in the response
  (browser relays only this token to the local Device Agent)
- `GET /install/redeem/{install_token}` → called by the **Device Agent itself**
  (normal outbound HTTPS, not by the browser) to fetch the real install plan;
  server validates the token is unexpired/unused and marks it consumed
- `POST /install/{token_id}/telemetry` → optional aggregate success/failure
  ping (no device identity retained)

**Storefront/CLI ↔ Device Agent** (local loopback only, HTTPS + cert — the only
device-facing channel needed in v1)
- `GET /local/system-profile`
- `POST /local/install {install_token}` (Device Agent redeems the token itself,
  then installs via OEP Installer)
- `POST /local/upgrade {install_token}` / `POST /local/uninstall {app_version_id}`
- `GET /local/installed-apps` (local status/health, for "view installed apps")

## 8. Cross-Cutting Concerns
- **Secrets**: settings marked `is_secret` never stored/logged in plaintext;
  decrypted only in-memory on the Device Agent at install time.
- **Multi-tenancy**: ISV/SI data scoped by `org_id`; RBAC enforced at API layer.
- **Image sourcing**: catalog-hosted registry (preferred, enables click-to-accept
  gating) or ISV-provided external URL (weaker gating guarantee — flagged to
  Intel admin at review time).
- **Compatibility check**: performed **locally by the Device Agent** against
  the install plan it fetched directly from Catalog Service (not by trusting
  the browser's relayed data), and also pre-checked server-side before the
  install token is issued — avoids trusting an install grant the device
  itself hasn't independently verified.
- **Observability**: audit_logs for every admin/lifecycle action;
  install_telemetry_events for aggregate adoption metrics.

## 9. AWS Architecture (Tier 2 implementation choice)

### 9.1 Service Mapping

| Concern | AWS Service | Notes |
|---|---|---|
| SSO / Login | **Amazon Cognito** federated with Intel IdP via SAML/OIDC | Invite-only user pools match allowlist requirement |
| API layer | **API Gateway** + **ECS Fargate** (or Lambda for lighter endpoints) | v1: plain request/response only — `POST /install` returns an opaque install token synchronously to the browser; the Device Agent separately calls `GET /install/redeem/{token}` outbound to fetch the real plan; no WebSocket/long-poll needed since there's no direct cloud→device leg |
| App/version/user metadata | **Amazon RDS (Postgres)** | Relational integrity for lifecycle states |
| Search/browse index | **OpenSearch Service** (optional) or Postgres full-text | Start with Postgres |
| Compose/baremetal files, config/data files, evidence, icons | **Amazon S3** (private, per-org prefix) | Access via short-lived pre-signed URLs only |
| Container images (hosted-registry path) | **Amazon ECR** (private, per-ISV-org namespace) | External-URL path bypasses ECR — see §8 |
| Secrets | **AWS Secrets Manager** / KMS-encrypted RDS column | Never plaintext |
| Async jobs (deployment-file parsing, image scanning, notifications) | **SQS** + **Lambda/Fargate workers** | |
| Install token store | **DynamoDB** (or Redis/ElastiCache) with TTL | Single-use, short-lived (minutes) opaque tokens; no asymmetric signing/PKI required — ordinary HTTPS (public CA) secures the Device Agent's redeem call |
| Audit logs | **CloudTrail** + application `audit_logs` table | |
| CDN for public listing assets | **CloudFront** over a public S3 prefix | Never for gated artifacts |

### 9.2 Click-to-Accept Gated Download — Flow
Browsing/discovery is open; **download/pull of artifacts is gated** by a
recorded license acceptance.

```
1. SI browses catalog, opens app detail page (freely visible, no gate).
2. SI clicks "Install" → backend checks: has this user_id accepted
   license_id for this app_version before?
      NO  → show license/EULA text → SI clicks "Accept" → backend writes
             `license_acceptances(user_id, app_version_id, license_id,
              accepted_at, ip_address)` — immutable, append-only.
      YES → proceed.
3. Only after this check passes does Catalog Service issue the **opaque
   install token** (§4.5) — the token itself grants nothing until redeemed.
4. Device Agent redeems the token (`GET /install/redeem/{token}`, its own
   outbound HTTPS call). Catalog Service, at redeem time, includes a
   short-lived pre-signed S3 URL (compose/config files) and a temporary ECR
   pull token scoped only to that app_version's images (hosted-registry
   path), or the external URL as-is (external path).
5. Device Agent hands the plan to the OEP Installer, which fetches artifacts
   and runs `docker compose up`.
6. Re-acceptance is only required again if the license version changes for a
   new app_version.
```
Enforcement is server-side: **token issuance is the gate** (step 3) and the
token is only redeemable once (step 4) — nothing is downloadable without
passing the acceptance check first.

### 9.3 Image & Artifact Hosting Flow (ISV → ECR/S3, hosted-registry path)
```
1. ISV uploads a deployment file (compose, MVP-primary) via the onboarding wizard.
2. Onboarding Service parses it, extracts referenced image refs.
3. ISV chooses: (a) push each image to a catalog-provisioned private ECR repo
   (`<catalog-registry>/<isv-org-slug>/<app-id>/<service-name>:<tag>`), or
   (b) supply an external image URL instead (recorded with a lower-trust flag).
4. On ECR push, an EventBridge-triggered job runs vulnerability scanning
   (ECR native scan or Trivy) before the app_version can leave `draft`.
5. Deployment file + config/data files stored in S3 under
   `s3://<bucket>/<org_id>/<app_id>/<version>/`.
6. At review time, Intel admin sees scan results (hosted path) or a "external,
   unscanned" flag (URL path) alongside hardware test evidence.
```

## 10. Phased Rollout (Tech Preview 1 → 3) *(new — [CORRECTED])*

| Phase | Device-side distribution | Notes |
|---|---|---|
| TP1 | SI manually installs Ubuntu, network/proxy config, Edge Pack (own installer), then installs **Device Agent + OEP Installer from Intel-signed `.deb` packages via RDC** | OXM step is optional/skipped for TP1; SI does device prep |
| TP2/TP3 | **Edge Pack declares Device Agent + OEP Installer as hard dependencies**, installed automatically from an **Intel APT repo** | Requires Intel to publish official Device Agent/Installer packages in that repo; OXM can now image devices "catalog-ready" out of the box |

Open per source deck: signing/security model for Edge Pack images, and whether
Device Agent + OEP Installer as hard Edge Pack dependencies (vs. other
distribution options) is the right long-term call.

## 11. Corrections From Prior Draft & Remaining Open Questions

### 11.1 Summary of corrections in this revision
1. Added the 4th persona (OXM/OEM) and its device-imaging journey.
2. Replaced the single generic "device agent" with the real Tier-3 split:
   **Device Agent** (profile, redeem install token, orchestrate) + **OEP
   Installer** (existing module/profile bootstrap engine — actual install
   execution).
3. Removed the persistent `devices`/`installations` fleet tables — replaced
   with session-scoped install-token handoff and anonymous aggregate
   telemetry, per the explicit "no fleet management" design decision.
4. Added the **HTTPS-loopback-with-cert** channel between Storefront/CLI and
   the local Device Agent (previously only had client→cloud→agent).
5. Replaced the SQS device job-queue model with an **opaque single-use
   install token** relayed by the browser and **redeemed directly by the
   Device Agent** over its own outbound HTTPS call — no asymmetric
   signing/PKI needed for this leg (simpler than an earlier signed-manifest
   design that required KMS + public-key provisioning to every device).
6. Added Federation (Partner Catalogs, signed indexes) as a Tier-2 concern,
   explicitly future/out-of-scope for TP.
7. Added MCP as a peer interface to REST on the Catalog Service.
8. Broadened app format awareness (compose is MVP-primary; bare-metal
   executables are a stated target category, not yet designed for).
9. Added ISV image-sourcing flexibility (hosted registry **or** external URL).
10. Added the phased TP1→TP3 device-side distribution model (§10).
11. Named `eaictl` as the first-class CLI client alongside the web Storefront.

### 11.2 Important carry-over risk (unchanged from earlier review)
Tier 3 still depends on the **existing OEP Installer**, which today defines
install logic as **per-app hardcoded shell functions** with manually pinned git
tags/commits per component (see the separate OEP Installer review in this
workstream). Unless the OEP Installer evolves to consume the Catalog Service's
install plan **data-drivenly** (rather than needing a bespoke shell function
per app baked into the installer itself), this new catalog will inherit that
duplication-of-install-logic problem at the Tier-3 boundary — worth flagging to
the OEP Installer owner as this design solidifies.

### 11.3 Open questions
1. ~~Device Agent transport~~ — **resolved for v1**: browser triggers the
   install (relays only an opaque, short-lived token), Device Agent redeems
   the token and fetches the install plan **directly** from Catalog Service
   over its own outbound HTTPS call (§3.1, §4.5); no direct cloud→agent leg
   or persistent connection needed since the user browses the catalog from
   the device they're installing onto. Revisit only if a future phase needs
   remote/fleet-initiated installs.
2. Does "Send back" preserve the same `app_version` row or create a revision history?
3. Multi-version support: can an SI stay on an older Listed version after a new one is approved?
4. Geography filter — self-declared by ISV, or derived from org profile?
5. Image vulnerability scan failure handling: hard block, or admin-overridable warning?
6. Multi-region: single AWS region sufficient for MVP, or cross-region S3/ECR replication needed?
7. Bare-metal executable app format: what does the "install plan" + "compatibility
   check" even mean for non-containerized apps — separate design track needed
   before TP claims to support it.
8. Edge Pack signing/security model, and whether Device Agent + OEP Installer as
   hard Edge Pack dependencies is the right long-term distribution mechanism
   (both flagged as open issues in the source architecture deck).
9. **Loopback cert provisioning strategy (new)**: wildcard-DNS-to-loopback with
   a real public CA cert (Plex-style) vs. a pre-installed private root CA
   (Docker Desktop-style)? This decision must be made before Device Agent
   implementation starts, and needs sign-off from Intel's PKI/security team
   given it involves either public DNS delegation or installing a trusted root
   CA on customer devices. Also needs confirmation that Chrome/Edge's Private
   Network Access preflight behavior (§3.1.1c) works as expected across the
   versions Intel intends to support.
