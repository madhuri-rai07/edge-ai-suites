# OpenShell Security Feature Mapping to Kubernetes + Kata Validation

This document maps OpenShell-style security features to what we validated in the Kubernetes + Kata POC for Smart Route Planning Agent.

Namespace used: `dev-madhuri`  
Release label used: `srpa`

## Quick Summary

- Total checks: `PASS=12`, `FAIL=2`, `WARN=2`
- Strong controls validated: workload isolation runtime in use, non-root, no privilege escalation, seccomp default, dropped capabilities, egress restrictions, least-privilege service account.
- Gaps to close: RuntimeClass lookup visibility/config check, namespace NetworkPolicy baseline, namespace Pod Security enforce label, admission guardrail for privileged breakout attempt.

## Mapping Table

| OpenShell-style security feature | How we validated in K8s+Kata | Step/command used | Observed output | Simple explanation | Status |
|---|---|---|---|---|---|
| Workload isolation with hardened runtime | Verified route-agent pod runs on Kata runtime class | `kubectl get pod -n dev-madhuri -l app.kubernetes.io/instance=srpa -o jsonpath='{.items[0].spec.runtimeClassName}'` | `[PASS] Pod runtimeClassName is kata-qemu` | Agent is running in Kata micro-VM isolation, not plain container runtime. | PASS |
| RuntimeClass object integrity | Checked RuntimeClass object exists in cluster API | `kubectl get runtimeclass kata-qemu` (inside script) | `[FAIL] RuntimeClass kata-qemu not found` | Pod still ran with `kata-qemu`, so this likely indicates RBAC visibility issue or naming mismatch in check path. Needs admin confirmation. | FAIL |
| Non-root execution | Checked pod-level security context | `kubectl get pod ... -o jsonpath='{.spec.securityContext.runAsNonRoot}'` | `[PASS] runAsNonRoot is true` | Container is not allowed to run as root user. | PASS |
| Privilege escalation blocked | Checked container security context | `kubectl get pod ... -o jsonpath='{.spec.containers[0].securityContext.allowPrivilegeEscalation}'` | `[PASS] allowPrivilegeEscalation is false` | Process inside container cannot raise privileges. | PASS |
| Kernel syscall hardening (seccomp) | Checked seccomp profile | `kubectl get pod ... -o jsonpath='{.spec.containers[0].securityContext.seccompProfile.type}'` | `[PASS] seccompProfile is RuntimeDefault` | Restricted syscall profile is active. | PASS |
| Linux capability minimization | Checked dropped capabilities list | `kubectl get pod ... -o jsonpath='{.spec.containers[0].securityContext.capabilities.drop[*]}'` | `[PASS] Container drops ALL capabilities` | Container has no extra Linux capabilities by default. | PASS |
| Escape attempt resistance (admission/policy) | Tried launching privileged pod with host access | Script applied `escape-attempt` pod (`privileged`, `hostPID`, `hostNetwork`, `hostPath:/`) | `[WARN] Privileged breakout pod apply succeeded (phase: Pending)` | Guardrail did not hard-reject request at admission time. Add/strengthen Pod Security or policy engine rules. | WARN |
| Deny-by-default network baseline present | Checked if any NetworkPolicy exists in namespace | `kubectl get networkpolicy -n dev-madhuri` | `[FAIL] No NetworkPolicy objects found in namespace` | Namespace baseline policy is missing and should be added explicitly. | FAIL |
| Outbound network containment effective | Created kata test pod and attempted external/service access | Test pod `kata-net-test` + curl checks to `1.1.1.1`, `169.254.169.254`, `kubernetes.default.svc` | `[PASS] ... blocked as expected` for all three | Egress from test workload was blocked for these destinations. | PASS |
| Test workload runtime operability | Confirmed Kata validation pod reaches Ready | `kubectl wait --for=condition=Ready pod/kata-net-test ...` | `[PASS] Kata test pod became Ready` | Kata runtime path is operational for test workload. | PASS |
| Service account least privilege | Checked default SA permissions for sensitive actions | `kubectl auth can-i --as=system:serviceaccount:dev-madhuri:default ...` | `[PASS] SA cannot list secrets/create pods/get nodes` | App identity has limited API permissions. | PASS |
| Namespace Pod Security enforcement | Checked namespace label for Pod Security admission | `kubectl get ns dev-madhuri -o jsonpath='{.metadata.labels.pod-security\.kubernetes\.io/enforce}'` | `[WARN] Namespace missing pod-security.kubernetes.io/enforce label` | Namespace-level Pod Security mode is not explicitly enforced yet. | WARN |
| Platform inventory evidence | Collected node OS inventory | `kubectl get nodes -o jsonpath='{range .items[*]}{.metadata.name}{"\t"}{.status.nodeInfo.osImage}{"\n"}{end}'` | Listed master/worker Ubuntu versions | Good evidence for current host baseline; useful for audit trail. | INFO |

## Exact Result Snapshot Used

```text
[INFO] Namespace: dev-madhuri
[INFO] Release label: srpa
[INFO] Target pod: srpa-smart-route-planning-agent-5cb7c6d577-jtsl2
[PASS] Pod runtimeClassName is kata-qemu
[FAIL] RuntimeClass kata-qemu not found
[PASS] runAsNonRoot is true
[PASS] allowPrivilegeEscalation is false
[PASS] seccompProfile is RuntimeDefault
[PASS] Container drops ALL capabilities
[INFO] Attempting privileged breakout pod creation (should be denied in secure posture)
[WARN] Privileged breakout pod apply succeeded (phase: Pending); verify Pod Security/OPA/Kyverno policies
[FAIL] No NetworkPolicy objects found in namespace
[INFO] Creating kata egress test pod
[PASS] Kata test pod became Ready
[PASS] Egress test 'public-ip' blocked as expected
[PASS] Egress test 'metadata-ip' blocked as expected
[PASS] Egress test 'kubernetes-svc' blocked as expected
[INFO] ServiceAccount: default
[PASS] SA cannot list secrets
[PASS] SA cannot create pods
[PASS] SA cannot get nodes
[WARN] Namespace missing pod-security.kubernetes.io/enforce label
[INFO] Node OS inventory:
master1 Ubuntu 24.04.3 LTS
worker1 Ubuntu 24.04.1 LTS
worker2 Ubuntu 24.04.1 LTS
worker3 Ubuntu 24.04.1 LTS
worker4 Ubuntu 24.04.3 LTS
worker5 Ubuntu 24.04.3 LTS
worker6 Ubuntu 24.04.1 LTS

Summary: PASS=12 FAIL=2 WARN=2
```

## Minimal Follow-up Actions

1. Confirm RuntimeClass visibility/name with admin:
   - `kubectl get runtimeclass`
   - `kubectl get runtimeclass kata-qemu -o yaml`
2. Add namespace baseline NetworkPolicy (deny-by-default + required allow rules).
3. Add Pod Security labels on namespace (`enforce`, `warn`, `audit`).
4. Enforce hard reject for privileged/host-level pods via Pod Security restricted mode or policy engine (Kyverno/OPA).
