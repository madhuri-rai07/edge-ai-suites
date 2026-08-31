# Edge AI Catalog — Detailed Technical Flows

> Companion to `edge-ai-catalog-design.md`. That doc defines the architecture,
> data model (§5), state machine (§6), and API surface (§7). This doc expands
> each persona capability from the MVP Persona doc into a concrete,
> step-by-step technical sequence — actor action → API call → backend
> processing → DB/state change → response — so a build vendor can implement
> against it without re-deriving behavior from prose.
>
> **Status note on Install/Upgrade/Uninstall/View-installed (flows I1–I4):**
> these are written against the v1-confirmed design (browser ↔ local Device
> Agent over HTTPS loopback with a cert — see design doc §3.1.1). The
> loopback/cert provisioning strategy is an **explicitly open, pending
> decision** (design doc §11.3 #9) parked for later resolution. A vendor can
> build everything else in this document now; flows I1–I4 should be
> implemented behind a feature flag / TP2 milestone, with **TP1 fallback**
> notes included per flow so the vendor isn't blocked.

---

## Flow Index

| # | Flow | Persona | Primary APIs | Depends on Device Agent? |
|---|---|---|---|---|
| A1 | Sign in / access control | All | Auth service | No |
| B1 | Onboard a new application | ISV | Onboarding Service | No |
| B2 | Update an application | ISV | Onboarding Service | No |
| B3 | Track & manage apps (dashboard, delist) | ISV | Onboarding Service | No |
| C1 | Review an application | Intel Admin | Review Service | No |
| C2 | Manage listed applications (suspend/resume/remove) | Intel Admin | Review Service | No |
| C3 | User management (invite, roles, revoke) | Intel Admin | Identity & Access | No |
| D1 | Discover applications | SI | Catalog Service | No |
| D2 | Install an application | SI | Catalog Service + Device Agent | **Yes (TP2+)** |
| D3 | Upgrade an application | SI | Catalog Service + Device Agent | **Yes (TP2+)** |
| D4 | Uninstall an application | SI | Device Agent (local only) | **Yes (TP2+)** |
| D5 | View installed apps / health | SI | Device Agent (local only) | **Yes (TP2+)** |

---

## A1 — Sign in / access control (all personas)

**Preconditions:** user's email has been added to an `invitations` row by an
Intel Admin (C3), with a role assigned.

1. User opens Storefront at `catalog.intel.com`. No session cookie → redirect
   to `GET /auth/login`.
2. Catalog Service redirects to Intel SSO (OIDC authorization-code flow) —
   or Cognito federated with Intel IdP (AWS impl., design doc §9.1).
3. User authenticates with Intel SSO. IdP redirects back to
   `GET /auth/callback?code=...`.
4. Catalog Service exchanges `code` for tokens, extracts `sso_subject_id` and
   `email` from the ID token.
5. **Allowlist check**: query `invitations` for a row matching `email` with
   `status = 'pending'` or an existing `users` row with that
   `sso_subject_id`.
   - **Not found** → reject: render "Access not authorized — contact your
     Intel Admin" page. No session created. *(Do not leak whether the email
     exists in the system at all — same generic message either way.)*
   - **Found (first login)** → create `users` row (`sso_subject_id`, `email`,
     `name` from ID token claims), create `user_roles` row(s) from the
     matched `invitations.role`/`org_id`, mark `invitations.status = 'accepted'`.
   - **Found (returning user)** → load existing `users` + `user_roles`.
6. Catalog Service issues its own session (JWT or server session, per §9.1
   Cognito user pool tokens), sets secure/httpOnly cookie, redirects to `/`.
7. Storefront calls `GET /me` → returns `{ user_id, email, roles: [...],
   orgs: [...] }`. Storefront renders nav/capabilities based on roles
   (ISV dashboard link only if role includes ISV, etc. — a user may have
   multiple roles, so multiple nav sections may show).
8. Every subsequent API call carries the session; API layer enforces RBAC
   per-endpoint (e.g. `/admin/*` requires role=ADMIN) — **never** trust a
   client-supplied role claim, always re-check `user_roles` server-side.

**Error cases:** expired invitation (`invitations.expires_at` passed) →
same generic rejection message, logged to `audit_logs` with reason
`invitation_expired` (admin-visible, not user-visible).

---

## B1 — ISV: Onboard a new application

**Preconditions:** user authenticated with role ISV, belongs to an
`organizations` row of `org_type = ISV`.

1. ISV clicks "New App" in ISV dashboard → Storefront opens onboarding
   wizard, step 1: **listing details**.
2. Step 1 — Listing details: ISV enters name, category (enum: Retail,
   Industrial, Robotics, Cities & Infrastructure, Education, Other),
   description, tags, icon upload, license selection/upload.
   - `POST /apps` `{ name, category, description, tags[], org_id }` →
     creates `apps` row, `status = draft`. Returns `{ app_id }`.
   - Icon upload: client requests a pre-signed S3 PUT URL
     (`POST /apps/{id}/assets/icon-upload-url`), uploads directly to S3,
     then `PUT /apps/{id}` `{ icon_url }` to record the final URL.
   - License: either select an existing `licenses` row, or
     `POST /licenses` `{ title, text_url, version }` for a new one; store
     `apps.license_id`.
3. Step 2 — Deployment file: ISV uploads a single Docker Compose file.
   - Client gets a pre-signed S3 PUT URL, uploads the file, then
     `POST /apps/{id}/versions` `{ deployment_file_url, deployment_kind:
     "compose" }` → creates `app_versions` row, `status = draft`, auto
     `version` suggestion (e.g. `0.1.0`, ISV can override before submit).
4. Step 3 — Parse & fill in references:
   - `POST /apps/{id}/versions/{v}/parse-deployment` → server downloads the
     compose file from S3, parses it (`docker-compose` schema), extracts:
     - referenced **images** per service → creates draft
       `app_version_images` rows (`service_name`, `image_ref`,
       `source = external_url` by default).
     - referenced **volumes/config/data files** → wizard prompts ISV to
       upload each one (pre-signed S3 URL per file, same pattern as step 2).
     - referenced **environment variables** ("settings") → creates draft
       `app_version_settings` rows (`env_key`) with empty `default_value`.
   - Response returns the full extracted list so the Storefront can render
     an editable form (this is a **synchronous** call for MVP-sized compose
     files; for very large files, an async job + `SQS` + polling is the
     fallback per §9.1 — flag as an implementation choice for the vendor).
5. Step 3a — ISV fills in image sourcing per service:
   - Choice A: "push to catalog registry" — wizard shows
     `docker push <catalog-registry>/<isv-org-slug>/<app-id>/<service>:<tag>`
     instructions + a short-lived ECR push credential
     (`POST /apps/{id}/versions/{v}/images/{image_id}/push-credentials`).
     ISV pushes from their own CI/CLI. On push completion (ECR
     EventBridge → catalog webhook), `app_version_images.source =
     hosted_registry`, `registry_or_url` updated, and an async **vulnerability
     scan job** is queued (SQS → Fargate worker running Trivy/ECR native
     scan); result stored against the image row.
     - Choice B: "external URL" — ISV pastes a reachable image URL directly;
       `PUT /apps/{id}/versions/{v}/images/{image_id}` `{ source:
       external_url, registry_or_url }`. No scan is performed; this is
       recorded as a **lower-trust flag** surfaced to the Admin at review
       time (§8 of design doc).
6. Step 3b — ISV fills in settings:
   - For each `app_version_settings` row: ISV sets `default_value`, marks
     `is_secret = true/false`, and may set `fill_at_install = true` (leaves
     value blank for the SI/installer to fill in — e.g. an access token).
   - `PUT /apps/{id}/versions/{v}/settings` `[{ env_key, default_value,
     is_secret, fill_at_install, description }, ...]` (bulk upsert).
7. Step 4 — Hardware requirements + tested-on proof:
   - `PUT /apps/{id}/versions/{v}` `{ hardware_requirements: { cpu, gpu,
     npu, memory_gb, ... } }` (jsonb, free-form per design doc §5).
   - Evidence upload (screenshot/log/report of a test run) via pre-signed S3
     URL, then `POST /apps/{id}/versions/{v}/evidence` `{ test_evidence_url
     }`.
8. Step 5 — Review & submit:
   - Storefront renders a read-only summary of everything above.
   - `POST /apps/{id}/versions/{v}/submit`:
     - Server-side validation: all required fields present, at least one
       image reference resolved, license selected, evidence uploaded, **all
       hosted-registry images have a completed (not pending) vulnerability
       scan** (design doc §9.3 step 4 — hard gate per open question §11.3 #5,
       unless the SOW says otherwise).
     - On success: `app_versions.status = pending_review`,
       `submitted_at = now()`, snapshot becomes **immutable** (no further
       edits to this version row — corrections require step B2's new-version
       flow). If this is the app's first version, `apps.status =
       pending_review` too.
     - Triggers Notification Service → email to Intel Admin distribution
       list ("New app pending review: {app_name} v{version}").
   - Response: `{ status: "pending_review" }`. Storefront redirects to ISV
     dashboard, new app card shows "Pending review" badge.

**Error cases:** parse failure (invalid compose syntax) → `422` with parser
error detail, wizard stays on step 3 with inline error. Submit validation
failure → `400` with a list of missing/invalid fields, wizard jumps to the
first incomplete step.

---

## B2 — ISV: Update an application

**Preconditions:** ISV owns an `apps` row with at least one prior
`app_versions` row (any status).

1. ISV opens the app from the dashboard → clicks "New Version" (if they only
   want metadata changes, e.g. fixing the description, that's a `PUT
   /apps/{id}` on the parent `apps` row instead and does **not** require
   re-review — clarify this distinction in the SOW; the MVP doc implies
   version-level changes always go back through review, metadata-only edits
   are a product decision worth confirming, design doc open question #2).
2. `POST /apps/{id}/versions` `{ deployment_file_url?, base_version_id }` —
   if ISV chooses "start from previous version," server copies forward the
   prior version's images/settings/hardware requirements as an editable
   draft (`app_version_images`, `app_version_settings` rows duplicated with
   new `app_version_id`) rather than starting blank.
3. ISV edits whatever changed (new image tag, new setting, updated hardware
   claim, new evidence) — same sub-flows as B1 steps 3–4, scoped to the new
   `app_versions.id`.
4. `POST /apps/{id}/versions/{v}/submit` — same validation as B1 step 8.
   - `app_versions.status = pending_review` for the **new** version only.
   - **The previously `listed` version's status is untouched** and remains
     installable by SIs until this new version is separately approved
     (design doc §6: "the previously listed version stays installable until
     the new one is approved").
   - `apps.status` does not change if the app already has a currently listed
     version (an app can have one `listed` version and simultaneously one
     `pending_review` version — the `apps.status` field in the simplified ER
     is a simplification; the vendor's actual implementation should track
     "does this app have ≥1 listed version" as a derived value for catalog
     visibility, separate from "does it have a version awaiting review" for
     the ISV/Admin dashboards).
5. On Admin decision (flow C1), only the new `app_versions` row transitions;
   if approved, it becomes the new `listed` version and (per product
   decision, open question #3) either replaces the old one in the catalog
   listing or is offered as a selectable version alongside it.

---

## B3 — ISV: Track & manage apps (dashboard)

1. `GET /isv/dashboard` (scoped to caller's `org_id`) returns:
   - List of `apps` with their current status, and per-app the list of
     `app_versions` with individual statuses (an app can simultaneously show
     one `listed` version and one `pending_review`/`sent_back` version).
   - Aggregate counts: `SELECT count(*) FROM apps WHERE status='listed'`,
     `= 'pending_review'`, and `SELECT sum(...) FROM
     install_telemetry_events WHERE app_version_id IN (...) AND
     action='install'/'upgrade'` grouped for "downloads"/"installs" cards.
2. ISV clicks into an app with `status = sent_back` → sees
   `review_events.comments` from the reviewer, "Edit & Resubmit" button
   routes into B2 flow 2 (pre-filled with the sent-back version's data).
3. **Delist**: ISV clicks "Delist" on a `listed` app →
   `DELETE /apps/{id}` (ISV-scoped, only allowed on apps the ISV owns,
   only from `listed` state) → `apps.status = removed` (or a distinct
   `delisted` status if the SOW wants ISV-initiated removal tracked
   separately from Admin-initiated `removed` — worth clarifying since the
   MVP doc uses "Delist" for ISV and "Remove/Revoke" for Admin as
   conceptually different triggers of the same end-state).
   Writes `audit_logs` entry `{ actor_id: isv_user, action: "delist",
   entity_type: "app", entity_id }`.

---

## C1 — Intel Admin: Review an application

1. Admin opens `GET /admin/reviews?status=pending_review&isv=` — filterable
   list of `app_versions` in `pending_review`, joined with `apps`/
   `organizations` for ISV name.
2. Admin opens one — Storefront renders the full submission read-only:
   listing details, parsed images (flagging any `source = external_url` as
   lower-trust, per §9.3), settings (secrets masked), hardware requirements,
   tested-on evidence link, and (hosted-registry images only) vulnerability
   scan results.
3. Admin takes one action:
   - **Approve**: `POST /admin/reviews/{version_id}/approve` →
     `app_versions.status = listed`, `reviewed_at = now()`,
     `reviewer_id = admin_user_id`. Writes `review_events` row
     (`action=approve`). If this app had a prior `listed` version and the
     product decision (open question #3) is "replace," that prior version's
     status flips to a terminal `superseded` state (not in the current
     simplified state machine — vendor should confirm this addition with
     product owner before implementing). Triggers Notification Service →
     ISV email "Your app is now listed."
   - **Send back**: `POST /admin/reviews/{version_id}/send-back`
     `{ comments }` → `app_versions.status = sent_back`. Writes
     `review_events` (`action=send_back`, `comments`). Notification → ISV
     email with comments, link back into B2 flow 2.
   - **Reject**: `POST /admin/reviews/{version_id}/reject` `{ comments }`
     → `app_versions.status = rejected` (terminal — per state machine §6,
     no further transitions from `rejected`; ISV must submit a brand-new
     `app_versions` row to try again, not resubmit this one). Writes
     `review_events` (`action=reject`). Notification → ISV email.
4. All three actions are also written to `audit_logs` (immutable,
   Admin-action audit trail per design doc §4.7), separate from the
   `review_events` table which is app-version-scoped and ISV-visible.

---

## C2 — Intel Admin: Manage listed applications

1. Admin opens a `listed` app → sees Suspend / Remove actions (Resume
   appears if currently `suspended`).
2. **Suspend**: `POST /admin/apps/{id}/suspend` `{ reason? }` →
   `apps.status = suspended` (hides from SI catalog browse/search
   immediately — `GET /catalog` filters `WHERE status='listed'` only).
   Existing SI installs are **unaffected** (no fleet tracking to reach into
   per the no-fleet-management decision — suspension only stops *new*
   installs, design doc §4.5 is explicit that this catalog has no way to
   remotely act on already-installed apps in v1). Writes `review_events`
   (`action=suspend`) + `audit_logs`.
3. **Resume**: `POST /admin/apps/{id}/resume` → `apps.status = listed`
   again. Same audit trail pattern.
4. **Remove**: `DELETE /admin/apps/{id}` → `apps.status = removed`
   (terminal — per state machine, no path back from `removed`; ISV would
   need a net-new `apps` row to re-list). Writes `review_events`
   (`action=remove`) + `audit_logs`. Underlying S3 artifacts/ECR images are
   **not** deleted immediately (retain for audit/compliance window per
   Intel data-retention policy — confirm retention period with legal/compliance,
   not specified in source docs).

---

## C3 — Intel Admin: User management

1. **Invite**: Admin enters email + role(s) + org →
   `POST /admin/invitations` `{ email, role, org_id }` → creates
   `invitations` row (`status = pending`, `expires_at = now() + N days`).
   Triggers Notification Service → invite email with a magic-link or plain
   "go to catalog.intel.com and sign in with this email" instruction
   (exact UX depends on whether Intel SSO auto-matches by email or needs an
   explicit invite-token link — clarify with Intel IAM team, affects flow A1
   step 5).
2. **Assign/change roles**: `PUT /admin/users/{id}/roles` `{ roles: [...] }`
   — replaces the user's `user_roles` rows. A user may hold multiple roles
   simultaneously (ISV + SI, per design doc §2). Writes `audit_logs`
   (`action = role_change`, `metadata: { before, after }`).
3. **Revoke access**: not explicitly named in the MVP doc but implied by
   "authorize partner users" — recommend adding
   `DELETE /admin/users/{id}` (soft-delete: mark all `user_roles` inactive,
   invalidate any active sessions) as a vendor deliverable even though it's
   not spelled out in source docs; flag as a gap to confirm with product
   owner (not in design doc's open questions list — add it).
4. **Unauthorized sign-in attempts**: already covered by flow A1 step 5 —
   confirm the Admin dashboard surfaces a log of rejected sign-in attempts
   (from `audit_logs` reason=`not_invited`/`invitation_expired`) for
   visibility, even though this isn't explicitly called out in source docs.

---

## D1 — SI: Discover applications

1. SI lands on catalog home: `GET /catalog?category=&search=&isv=&geo=`
   with no filters → returns paginated `listed`-only apps (server enforces
   `status='listed'` regardless of client-supplied filters — never trust
   client to only ask for listed apps), plus separately curated "trending
   use cases" (a product-curated list, mechanism TBD — likely a simple
   admin-managed featured-apps flag, not specified in source docs, flag as
   a gap).
2. SI applies filters (category/vertical dropdown, ISV name search,
   geography) → same endpoint, different query params. Geography filtering
   depends on resolving design doc open question #4 (self-declared by ISV
   on the app record vs. derived from the ISV org's registered address) —
   vendor needs this resolved before implementing the geo filter, not just
   the UI control.
3. SI clicks into an app: `GET /catalog/apps/{id}` → full detail: versions
   list (only `listed` ones visible to SI, though the ISV/Admin can see
   `sent_back`/`pending_review` ones via their own endpoints), description,
   hardware validation summary, license title (full text available on
   click, not yet the acceptance flow — that's gated later at install time,
   D2).
4. No authentication-gated content in this flow beyond being a signed-in,
   invited user at all (A1) — browsing is open to any authorized user
   regardless of role, per MVP doc ("Discover applications" has no
   role-specific gate beyond being logged in).

---

## D2 — SI: Install an application on a device

> **v1 target design (pending loopback/cert resolution — see status note at
> top of this document).**

**Preconditions:** SI is physically using a browser (or `eaictl` CLI)
running on the edge device itself. Device already has Ubuntu + Edge Pack +
Device Agent + OEP Installer present (TP1: SI manually installed these per
design doc §10; TP2+: OXM-imaged or Edge Pack auto-installs them).

1. SI clicks "Install on this device" on the app detail page (D1 step 3).
2. Storefront calls the **local Device Agent** over loopback:
   `GET https://127.0.0.1:<port>/local/system-profile` (see design doc
   §3.1.1 for the cert/CORS/PNA mechanics — not repeated here).
   - **First-time-only setup**: if this call fails (Device Agent not
     running/not yet provisioned), Storefront shows the "run this one-line
     setup command on your device" instructions from the MVP doc, then
     retries once the SI confirms setup is done.
3. Storefront calls Catalog Service:
   `POST /install {app_version_id, system_profile}`.
4. Catalog Service:
   a. **Compatibility pre-check** (server-side, advisory only — the
      authoritative check happens locally in step 6): compares
      `system_profile` against `app_versions.hardware_requirements`.
   b. **License gate** (design doc §9.2): checks `license_acceptances` for
      `(user_id, app_version_id)`.
      - Not yet accepted → returns `{ requires_acceptance: true,
        license_id, license_text_url }` instead of a manifest. Storefront
        shows the EULA, SI clicks "Accept" → `POST /apps/{id}/versions/{v}
        /accept-license` → writes `license_acceptances` row
        (`user_id, org_id, app_version_id, license_id, accepted_at,
        ip_address`) → Storefront re-calls `POST /install` (now passes the
        gate).
   c. Builds a **signed manifest**: compose file reference + resolved image
      refs (pre-signed S3 URL / ECR temp pull token for hosted-registry
      images, or the raw external URL) + `app_version_settings` (secrets
      still encrypted, decrypted only by the Device Agent) + license terms
      + compatibility rules, signs it with the KMS asymmetric key (design
      doc §9.1).
   d. Returns the signed manifest in the same HTTP response (no async
      job/polling — synchronous per design doc §3.1 step 4).
5. Storefront hands the manifest to the Device Agent:
   `POST https://127.0.0.1:<port>/local/install {manifest}`.
6. Device Agent: verifies the manifest's signature against the catalog's
   published public key; independently re-checks `system_profile`
   compatibility locally (does **not** simply trust the server's pre-check
   — design doc §8 "Compatibility check" principle); if any
   `fill_at_install=true` settings remain unfilled, returns a
   `needs_input: [...]` response to the Storefront, which prompts the SI
   for those values (e.g. an access token) and re-calls `/local/install`
   with them merged in.
7. Device Agent hands the fully-resolved **signed plan** to the **OEP
   Installer** (existing tool, unmodified per current design — carries
   forward the known per-app-hardcoded-logic risk, design doc §11.2).
   OEP Installer pulls images (from ECR using the temp token, or the
   external URL), writes config/data files, renders env vars into the
   compose file, and runs `docker compose up -d` with any declared device
   passthrough (`/dev/dri`, `/dev/accel`, etc. per repo conventions).
8. Status flows back: OEP Installer exit code → Device Agent → Storefront
   (polls or long-polls `GET /local/install/{job_id}/status` over the same
   loopback connection) → UI shows "Installing... / App available" with a
   launch link (from the app's declared entrypoint URL/port, a field not
   yet in the data model — vendor should add
   `app_version_settings`-adjacent `launch_url_template` or similar, flag
   as a gap).
9. Storefront optionally posts `POST /install/{manifest_id}/telemetry
   {action: "install", result: "success"|"failure"}` → writes
   `install_telemetry_events` (aggregate only, no device identity —
   design doc §4.5/§5).

**TP1 fallback (no Device Agent/loopback yet):** SI clicks "Install" →
Catalog Service performs the license gate (step 4b) then returns a
pre-signed download link + a plain-text install command
(`oep-cli install --manifest <signed-manifest-url>`) instead of relaying
through a local HTTPS service. SI runs this manually via a terminal on the
device (same pattern ESH uses today — download, then user-driven install).
This still satisfies "download gated by click-to-accept," just without the
in-browser one-click UX; recommend this as the actual TP1 deliverable given
the loopback/cert decision is still open.

**Error cases:** signature verification failure → Device Agent refuses,
logs locally, Storefront shows generic "Install failed — please retry"
(never surface signature details to the end user, but do log
device-side for support/debug). Incompatible hardware (local check fails
even though server pre-check passed, e.g. stale system_profile) → Device
Agent returns `{ error: "incompatible", details }`, Storefront shows
specific mismatch (e.g. "requires NPU, none detected").

---

## D3 — SI: Upgrade an application

1. SI opens an installed app (from D5's local list) → "Upgrade" button
   shown only if a newer `listed` `app_versions` row exists for the same
   `app_id` than the one currently installed (Storefront determines
   "currently installed version" from the Device Agent's local state,
   `GET /local/installed-apps`, then cross-checks against
   `GET /catalog/apps/{id}` for newer listed versions).
2. Same manifest-issuance flow as D2 steps 3–4 (license re-acceptance only
   triggered if `license_id` changed for the new version, per design doc
   §9.2 "re-acceptance only required if license version changes").
3. Storefront → Device Agent: `POST /local/upgrade {manifest}` instead of
   `/local/install`. Device Agent verifies + hands to OEP Installer, which
   this time runs the equivalent of `docker compose down` (old version) +
   `docker compose up -d` (new version) — exact OEP Installer command
   depends on its existing upgrade support (flag: confirm the OEP Installer
   actually has an idempotent upgrade path today, or if this needs new
   Installer work — separate from the Catalog project but a dependency of
   it).
4. Status/telemetry same pattern as D2 steps 8–9, `action: "upgrade"`.

**TP1 fallback:** same manual CLI pattern as D2, `oep-cli upgrade`.

---

## D4 — SI: Uninstall an application

1. SI opens an installed app (D5) → "Uninstall" → confirmation dialog.
2. Storefront → Device Agent: `POST /local/uninstall {app_version_id}` —
   **note this call does not need to reach Catalog Service at all**; it's
   a purely local action (no manifest needed to remove something already
   present, design doc §7 lists this as local-only).
3. Device Agent hands to OEP Installer to stop + remove containers/volumes
   per that app's `_remove` module function (existing OEP Installer
   convention).
4. Device Agent updates its local installed-apps state, returns success/
   failure to Storefront.
5. Storefront optionally posts aggregate telemetry (`action: "uninstall"`)
   to Catalog Service, same as D2 step 9.

**TP1 fallback:** SI runs `oep-cli uninstall <app>` manually.

---

## D5 — SI: View installed apps / health

1. Storefront (or CLI) calls `GET /local/installed-apps` on the Device
   Agent (loopback) — returns the list of currently installed apps on
   *this device only*, with basic health (container running/stopped,
   last-started time) — sourced from the Device Agent's local state, which
   in turn reflects `docker ps`/OEP Installer's own tracking, not a
   database Catalog Service owns.
2. Storefront renders this list with "Launch" (opens the app's URL) /
   "Upgrade" (feeds into D3) / "Uninstall" (feeds into D4) actions per row.
3. **No cross-device view exists in v1** — this is intentionally
   single-device, matching the "no fleet management" decision. If the SI
   opens the Storefront on a different device, they'll see that *other*
   device's local Device Agent state, not a unified list — call this out
   explicitly to the vendor and to any UX mockups so nobody accidentally
   designs a fleet-style multi-device table for v1.

**TP1 fallback:** `oep-cli list` prints installed apps/status locally; no
Storefront-rendered view for TP1 if Device Agent doesn't exist yet — pure
CLI experience for this capability until TP2.

---

## Open items a vendor should get resolved before/while building (cross-reference to design doc §11.3)

These are called out again here, flow-by-flow, so nothing gets silently
assumed during implementation:

- B2/C1: does an approved new version **replace** the previously listed one
  in the catalog, or do both appear as selectable versions? (affects C1 step
  3 "Approve" logic and the data model's lack of a `superseded` status)
- B3/C2: is ISV-initiated "Delist" the same end-state as Admin-initiated
  "Remove," or should they be distinguishable in `apps.status`?
- D1: geography filter semantics (open question #4) and the "trending use
  cases" curation mechanism (not in source docs at all — net-new gap)
- D2: `launch_url_template`-equivalent field doesn't exist yet in the data
  model but is needed for "SI gets a link to open/launch it" (MVP doc,
  Persona 2, Install capability, step 5)
- D2/D3: confirm the existing OEP Installer supports idempotent
  upgrade/uninstall today, independent of anything the Catalog project
  builds
- C3: explicit revoke-access endpoint (not named in source docs, recommend
  adding)
- All ISV artifact endpoints: confirm image vulnerability scan failure
  policy (hard block vs. admin-overridable) before B1 step 8's submit
  validation is finalized (open question #5)
