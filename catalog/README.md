<!--- SPDX-FileCopyrightText: (C) 2026 Intel Corporation -->
<!--- SPDX-License-Identifier: Apache-2.0 -->

# OEP App Catalog

A lightweight, GitOps-driven marketplace for Open Edge Platform (OEP) sample applications.

```
catalog/
├── index.yaml                              # Master catalog index (all apps)
└── apps/
    └── smart-traffic-intersection-agent/
        └── manifest.yaml                   # Full app metadata
```

---

## For SIs — Installing Apps

### Prerequisites
- `bash`, `curl`, [`yq`](https://github.com/mikefarah/yq), `docker` + `docker compose`
- For Helm installs: `helm >= 3.12`

### Install the CLI

```bash
curl -fsSL https://raw.githubusercontent.com/intel/edge-ai-suites/main/scripts/oep \
  -o /usr/local/bin/oep && chmod +x /usr/local/bin/oep
```

### Typical Workflow

```bash
# Browse the catalog
oep list

# Search by keyword
oep search traffic

# Inspect an app
oep info smart-traffic-intersection-agent

# Install via Docker Compose (default)
oep install smart-traffic-intersection-agent

# Install with GPU inference
oep install smart-traffic-intersection-agent --set VLM_TARGET_DEVICE=GPU

# Install via Helm (Kubernetes)
oep install smart-traffic-intersection-agent --method helm
```

### Offline / air-gapped use

```bash
git clone https://github.com/intel/edge-ai-suites.git
export OEP_CATALOG_LOCAL=/path/to/edge-ai-suites/catalog
oep list
```

---

## For ODMs — Publishing Apps

### 1. Create a manifest

Copy `catalog/apps/smart-traffic-intersection-agent/manifest.yaml` as a template and fill in your app's details.

### 2. Validate

```bash
scripts/oep-publish validate catalog/apps/my-app/manifest.yaml
```

### 3. Register in the catalog index

```bash
scripts/oep-publish register catalog/apps/my-app/manifest.yaml
# → updates catalog/index.yaml automatically
```

### 4. (Optional) Bundle & push Helm chart to OCI registry

```bash
OEP_OCI_PUSH=1 scripts/oep-publish bundle catalog/apps/my-app/manifest.yaml
```

### 5. Submit PR

```bash
git add catalog/
git commit -m "catalog: publish my-app 2026.1.0"
# Open PR → CI validates → merge → immediately available via `oep install`
```

---

## Catalog Schema

### `index.yaml` entry

| Field | Description |
|---|---|
| `id` | Unique app identifier (kebab-case) |
| `name` | Human-readable name |
| `version` | SemVer or `YYYY.M.P` |
| `suite` | Parent suite (metro-ai-suite, etc.) |
| `publisher` | Publishing org |
| `description` | One-line description |
| `tags` | Searchable keywords |
| `manifest` | Relative path to full manifest |

### `manifest.yaml` key sections

| Section | Purpose |
|---|---|
| `requirements` | Hardware, OS, software prerequisites |
| `artifacts` | Helm chart, Compose file, container images |
| `parameters` | Configurable env vars with defaults |
| `install` | Quick-start snippets shown by `oep info` |
| `source` | Repo, directory, license |
| `changelog` | Version history |

---

## Architecture Overview

```
ODM (Publisher)                  Catalog (Git + OCI)          SI (Consumer)
────────────────                 ───────────────────          ─────────────
oep-publish validate  ─────────► catalog/index.yaml    ◄───── oep list / search
oep-publish register             apps/*/manifest.yaml  ◄───── oep info
oep-publish bundle  ──────────►  OCI registry          ◄───── oep install
                (PR + CI)                                      docker compose up
                                                               helm install
```

CI (GitHub Actions) validates every manifest on PR, ensuring the catalog stays
consistent before merge.
