Kubernetes + Kata POC
With and Without EMT‑S (Helm‑based Agent)

1. Purpose of the POC (common to both)
The POC demonstrates Intel approach – Option B (conceptually) by validating:

Stronger isolation than plain containers using Kata micro‑VMs
Kubernetes‑controlled agent privileges
Network deny‑by‑default
Compatibility with an existing Helm‑deployed agent
Clear security/UX midpoint between OpenShell and TDX

What changes between the two setups is the host platform, not the agent or Helm charts.

2. Architecture Overview
Common layers (both setups)
Agent (Helm)
└── Kubernetes Pod
    └── Kata Containers runtime
        └── Micro‑VM
            └── Kata guest OS

Difference is below Kubernetes
WITHOUT EMT‑S:
Hardware
└── Ubuntu (or standard Linux)
    └── containerd + K8s
        └── Kata + Agent

WITH EMT‑S:
Hardware
└── EMT‑S (immutable host OS)
    └── containerd + K8s
        └── Kata + Agent
# Secure Agent POC Scope

## Scope Statement
This proof of concept validates Intel OpenShell Option B (EMT-S model) using the same Helm-deployed route-agent architecture in two variants:

1. Kubernetes + Kata on a standard Ubuntu host (without EMT-S)
2. Kubernetes + Kata on an EMT-S immutable host (with EMT-S)

The POC intentionally focuses on platform layering and security posture, not agent redesign.

## In Scope
- Validate Kubernetes policy-driven control with deny-by-default networking.
- Validate Kata Containers runtime isolation for agent pods.
- Reuse the existing Helm deployment model for the route-agent.
- Compare security posture between mutable host (Ubuntu) and immutable host (EMT-S).

## Out of Scope
- No architecture redesign.
- No application refactor.
- No Helm chart changes beyond setting `runtimeClassName: kata`.
- No confidential computing goals (this is not Option D).

## Core Architectural Clarification
- EMT-S is the host operating system layer for the Kubernetes node.
- Kata guest OS is the per-pod micro-VM operating system layer.
- EMT-S is not the Kata runtime OS.

## Variant 1: Kubernetes + Kata Without EMT-S

### Layering
hardware -> Ubuntu host OS -> Kubernetes/containerd -> Kata runtime -> Kata guest OS (micro-VM) -> route-agent pod (Helm)

### Security Guarantees
- Stronger isolation than standard containers via micro-VM boundaries.
- Kubernetes can enforce network and workload policies.
- Demonstrates Option B mechanics for runtime isolation and control.

### Explicit Trust Boundaries
- Host OS remains trusted and mutable.
- Host compromise risk is not removed.
- Not confidential compute.

### Helm Integration
- Existing Helm charts remain valid.
- Expected delta is pod runtime class selection: `runtimeClassName: kata`.
- Agent image, values, and release workflow stay unchanged.

### Why This Variant Is Valid
This is an intentional first step that verifies the technical core of Option B (Kubernetes + Kata behavior, policy enforcement, and operational flow) before introducing immutable host controls.

## Variant 2: Kubernetes + Kata With EMT-S

### Layering
hardware -> EMT-S immutable host OS -> Kubernetes/containerd -> Kata runtime -> Kata guest OS (micro-VM) -> route-agent pod (Helm)

### Security Guarantees
- Keeps all runtime isolation and policy benefits from Variant 1.
- Adds immutable host platform controls and reduced host drift.
- Improves production readiness for governance and operations.

### Explicit Trust Boundaries
- Host remains part of the trusted base.
- Still not confidential compute.
- Does not claim Option D properties.

### Helm Integration
- Same Helm artifacts and release process.
- Same expected runtime setting: `runtimeClassName: kata`.
- No workload logic change required.

### Productionization Path
EMT-S productionizes the same architecture by hardening the host platform layer while preserving the agent deployment model and runtime behavior.

## Option B Mapping
This POC maps directly to Option B from the deck:
- Secure host platform objective is realized fully in the EMT-S variant.
- Kubernetes provides policy and control plane enforcement.
- Kata provides stronger isolation for agent workloads.
- Tradeoff remains usability plus practical security, not maximum isolation at all costs.

## Quick Comparison

| Area | Without EMT-S | With EMT-S |
|---|---|---|
| Host OS | Standard Ubuntu (mutable) | EMT-S (immutable) |
| Kubernetes + Kata model | Same | Same |
| Helm integration | Same chart, set `runtimeClassName: kata` | Same chart, set `runtimeClassName: kata` |
| Agent changes | None expected | None expected |
| Host hardening level | Baseline | Higher |
| Option B maturity | Technical baseline | Production-aligned Option B |

## Distinction from Other Deck Options
- Option A (OpenShell-only sandboxing): narrower app/sandbox-level controls; does not represent this full K8s + Kata platform layering.
- Option D (TDX/confidential compute): different trust model that reduces trust in host infrastructure; not the objective of this POC.

## Executive Summary
This POC validates Option B by proving the route-agent can run under Kubernetes with Kata isolation using existing Helm delivery and only a runtime class selection change. The non-EMT-S deployment is a deliberate baseline to verify runtime and policy mechanics quickly. The EMT-S deployment then productionizes the same architecture by hardening the host OS while keeping Kubernetes, Kata, and the agent unchanged. This preserves user experience and operational practicality while meaningfully improving security posture within Option B's trusted-host model.
EMT‑S + Kata = host‑trusted
TDX = host‑untrusted

Your work here:
✅ Does not get thrown away
✅ Becomes the delivery and policy layer even if TDX is added later

Final takeaway (one line)
Without EMT‑S, your POC validates the technical heart of Option B; with EMT‑S, the same architecture becomes a managed, immutable, enterprise‑ready platform—without changing your Helm‑deployed agent.