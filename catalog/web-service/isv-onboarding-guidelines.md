<!--
SPDX-FileCopyrightText: (C) 2026 Intel Corporation
SPDX-License-Identifier: Apache-2.0
-->

# ISV Onboarding Guidelines — Intel OEP Catalog

> Companion to [`edge-ai-catalog-design.md`](edge-ai-catalog-design.md)
> (§4.3 Onboarding/Submission, §6 App Lifecycle, §9.2–9.3). This doc tells an
> ISV what to prepare and what to expect — it is not a design spec.

## 1. Who this is for
Independent Software Vendors (ISVs) who want to publish an edge AI app to the
catalog so System Integrators (SIs) can discover and one-click install it.

## 2. Before you start — have these ready
- **A single Docker Compose file** describing your app (MVP supports Compose
  only; bare-metal packaging is a future category).
- **Container images**, either:
  - pushed to the catalog's hosted registry (recommended — required for
    click-to-accept license gating), **or**
  - hosted at your own reachable URL (accepted, but gating on your registry
    is weaker — see design doc §8).
- **Hardware requirements**: CPU/GPU/NPU, memory, and any device-specific
  needs.
- **Tested-on evidence**: proof you validated the app on the target
  hardware before upload (screenshots, logs, or a short report).
- **License / EULA text** for the app, and its version.
- An account invited/approved for the **ISV** role (invite-only sign-in via
  Intel SSO).

## 3. Submission flow (2 screens)
1. **Screen 1 — Listing + Compose upload**: app name, description, category,
   tags, and your Compose file, submitted together.
2. **Screen 2 — Review & fill-in**: the catalog auto-extracts images,
   volumes/config files, and environment variables ("settings") from your
   Compose file and pre-fills them. You only need to:
   - Confirm or correct extracted values.
   - Mark any setting that must be supplied by the SI at install time as
     `fill_at_install=true` (e.g. API keys, per-site config).
   - Confirm hardware requirements and attach tested-on evidence.
   - Attach/confirm license terms.
3. Click **Submit**. This creates an immutable `app_version` snapshot and
   moves it to `pending_review`. You can keep editing a new draft while the
   submitted version awaits review.

## 4. What happens after you submit
Your `app_version` moves through this lifecycle:

```
draft --submit--> pending_review --approve--> listed
pending_review --send_back(comments)--> sent_back --resubmit--> pending_review
pending_review --reject--> rejected
listed --suspend--> suspended --resume--> listed
listed --remove--> removed
```

- **Approved → Listed**: installable by SIs immediately.
- **Sent back**: an Intel reviewer left comments; fix and resubmit — this
  goes back into `pending_review`.
- **Rejected**: not listed; you may submit a new version after addressing
  feedback.
- Updating a listed app always creates a **new app_version** in
  `pending_review`; the previously listed version stays installable until
  the new one is approved.

## 5. Prerequisites & setup steps — must be containerized
Some apps need work done before the main service starts — generating a
TLS cert, waiting on another service, seeding a config file, etc. **All such
steps must run as containers declared in your Compose file (e.g. an init
container using `depends_on`/healthchecks), not as host-level scripts.**

- ❌ **Not supported**: shell scripts, `install.sh`, or any setup step the
  catalog/Device Agent would need to execute directly on the SI's device
  outside a container. The Device Agent's only job is to verify your signed
  manifest and hand it to the OEP Installer to run `docker compose up` — it
  does not execute ISV-provided host code, and TP1 has no mechanism for
  reviewing or sandboxing such scripts.
- ✅ **Supported pattern**: package the setup logic as its own container
  (e.g. an `init` service that runs `openssl req -x509 ...` into a shared
  named volume, then exits) and order it with `depends_on` +
  `condition: service_completed_successfully` or a healthcheck, so your main
  service only starts once the prerequisite container has finished.
- If your app depends on **another catalog app** being installed first
  (rather than just an init step), don't fold that dependency's source into
  your own repo/Compose file — flag it in your submission notes so it can be
  tracked as an explicit app-to-app dependency; this is handled outside the
  Compose parser and may not be supported until a later Tech Preview.

## 6. What SIs see and do with your app
- Your app appears in catalog browse/search once **Listed**.
- An SI must accept your license terms once per `app_version` (a
  click-to-accept event is recorded) before any image pull is authorized.
- Re-acceptance is only required again if the license version changes.
- Install/upgrade/uninstall happen on the SI's own device via the local
  Device Agent — the catalog does not track individual devices.

## 7. What you can see (ISV dashboard)
- Status of each `app_version` (`draft`, `pending_review`, `listed`,
  `sent_back`, `rejected`, `suspended`, `removed`).
- Reviewer comments on `sent_back`/`rejected` versions.
- Aggregate, anonymous install/upgrade/uninstall counters per
  `app_version` (no per-device or per-SI-identity data).

## 8. Quick do's and don'ts
- ✅ Do keep one Compose file as the single source of truth for images,
  volumes, and settings.
- ✅ Do mark secrets/site-specific values as `fill_at_install=true` rather
  than hardcoding them.
- ✅ Do validate on real target hardware before uploading evidence.
- ✅ Do containerize any pre-install step (cert generation, config seeding,
  wait-for-dependency) as an init container in your Compose file.
- ❌ Don't expect the catalog to build your image from source — you build
  and push (or host) it; the catalog never builds from source (§4.3).
- ❌ Don't ship a host-level setup/install script that needs to run outside
  a container — it will not be executed by the Device Agent and your
  submission will be sent back.
- ❌ Don't assume external-URL-hosted images get the same license-gating
  guarantees as catalog-hosted-registry images.

## 9. Need help?
Contact your Intel catalog onboarding point of contact, or check the
Review/Workflow comments on a `sent_back` submission for specific fixes
requested by the reviewer.
