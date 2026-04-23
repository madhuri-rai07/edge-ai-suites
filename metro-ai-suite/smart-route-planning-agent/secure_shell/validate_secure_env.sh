#!/usr/bin/env bash

set -u
set -o pipefail

NS="${NS:-dev-madhuri}"
REL="${REL:-srpa}"
TEST_POD="kata-net-test"
ESCAPE_POD="escape-attempt"
TIMEOUT="${TIMEOUT:-120s}"
EXPECTED_RUNTIME_CLASS="${EXPECTED_RUNTIME_CLASS:-}"

PASS_COUNT=0
FAIL_COUNT=0
WARN_COUNT=0

pass() {
  PASS_COUNT=$((PASS_COUNT + 1))
  echo "[PASS] $1"
}

fail() {
  FAIL_COUNT=$((FAIL_COUNT + 1))
  echo "[FAIL] $1"
}

warn() {
  WARN_COUNT=$((WARN_COUNT + 1))
  echo "[WARN] $1"
}

info() {
  echo "[INFO] $1"
}

cleanup() {
  kubectl delete pod -n "$NS" "$TEST_POD" --ignore-not-found >/dev/null 2>&1 || true
  kubectl delete pod -n "$NS" "$ESCAPE_POD" --ignore-not-found >/dev/null 2>&1 || true
}

trap cleanup EXIT

if ! command -v kubectl >/dev/null 2>&1; then
  echo "kubectl not found in PATH"
  exit 2
fi

info "Namespace: $NS"
info "Release label: $REL"

POD="$(kubectl get pod -n "$NS" -l "app.kubernetes.io/instance=$REL" -o jsonpath='{.items[0].metadata.name}' 2>/dev/null || true)"
if [[ -z "$POD" ]]; then
  fail "No pod found for release label app.kubernetes.io/instance=$REL in namespace $NS"
  echo
  echo "Summary: PASS=$PASS_COUNT FAIL=$FAIL_COUNT WARN=$WARN_COUNT"
  exit 1
fi

info "Target pod: $POD"

RUNTIME_CLASS="$(kubectl get pod -n "$NS" "$POD" -o jsonpath='{.spec.runtimeClassName}' 2>/dev/null || true)"
if [[ -n "$EXPECTED_RUNTIME_CLASS" ]]; then
  if [[ "$RUNTIME_CLASS" == "$EXPECTED_RUNTIME_CLASS" ]]; then
    pass "Pod runtimeClassName is $EXPECTED_RUNTIME_CLASS"
  else
    fail "Pod runtimeClassName is '$RUNTIME_CLASS' (expected $EXPECTED_RUNTIME_CLASS)"
  fi
else
  if [[ "$RUNTIME_CLASS" == kata* ]]; then
    EXPECTED_RUNTIME_CLASS="$RUNTIME_CLASS"
    pass "Pod runtimeClassName is $RUNTIME_CLASS"
  else
    fail "Pod runtimeClassName is '$RUNTIME_CLASS' (expected a kata* RuntimeClass)"
  fi
fi

if [[ -z "$EXPECTED_RUNTIME_CLASS" ]]; then
  EXPECTED_RUNTIME_CLASS="kata"
fi

if kubectl get runtimeclass "$EXPECTED_RUNTIME_CLASS" >/dev/null 2>&1; then
  pass "RuntimeClass $EXPECTED_RUNTIME_CLASS exists"
else
  fail "RuntimeClass $EXPECTED_RUNTIME_CLASS not found"
fi

RUN_AS_NON_ROOT="$(kubectl get pod -n "$NS" "$POD" -o jsonpath='{.spec.securityContext.runAsNonRoot}' 2>/dev/null || true)"
ALLOW_PE="$(kubectl get pod -n "$NS" "$POD" -o jsonpath='{.spec.containers[0].securityContext.allowPrivilegeEscalation}' 2>/dev/null || true)"
SECCOMP="$(kubectl get pod -n "$NS" "$POD" -o jsonpath='{.spec.containers[0].securityContext.seccompProfile.type}' 2>/dev/null || true)"
CAP_DROP="$(kubectl get pod -n "$NS" "$POD" -o jsonpath='{.spec.containers[0].securityContext.capabilities.drop[*]}' 2>/dev/null || true)"

[[ "$RUN_AS_NON_ROOT" == "true" ]] && pass "runAsNonRoot is true" || fail "runAsNonRoot is '$RUN_AS_NON_ROOT'"
[[ "$ALLOW_PE" == "false" ]] && pass "allowPrivilegeEscalation is false" || fail "allowPrivilegeEscalation is '$ALLOW_PE'"
[[ "$SECCOMP" == "RuntimeDefault" ]] && pass "seccompProfile is RuntimeDefault" || fail "seccompProfile is '$SECCOMP'"
if [[ "$CAP_DROP" == *"ALL"* ]]; then
  pass "Container drops ALL capabilities"
else
  fail "Container capabilities.drop does not include ALL"
fi

info "Attempting privileged breakout pod creation (should be denied in secure posture)"
ESCAPE_APPLY_OUT="$(cat <<'EOF' | kubectl apply -n "$NS" -f - 2>&1
apiVersion: v1
kind: Pod
metadata:
  name: escape-attempt
spec:
  hostPID: true
  hostNetwork: true
  containers:
  - name: attacker
    image: busybox:1.36
    command: ["sh","-c","sleep 600"]
    securityContext:
      privileged: true
    volumeMounts:
    - name: host-root
      mountPath: /host
  volumes:
  - name: host-root
    hostPath:
      path: /
      type: Directory
EOF
)"
ESCAPE_RC=$?

if [[ $ESCAPE_RC -ne 0 ]]; then
  pass "Privileged breakout pod was denied by policy/admission"
else
  ESC_PHASE="$(kubectl get pod -n "$NS" "$ESCAPE_POD" -o jsonpath='{.status.phase}' 2>/dev/null || true)"
  warn "Privileged breakout pod apply succeeded (phase: ${ESC_PHASE:-unknown}); verify Pod Security/OPA/Kyverno policies"
fi

NP_COUNT="$(kubectl get networkpolicy -n "$NS" --no-headers 2>/dev/null | wc -l | tr -d ' ')"
if [[ "$NP_COUNT" -ge 1 ]]; then
  pass "NetworkPolicy objects present in namespace ($NP_COUNT found)"
else
  fail "No NetworkPolicy objects found in namespace"
fi

info "Creating kata egress test pod"
TEST_RUNTIME_CLASS="$EXPECTED_RUNTIME_CLASS"
cat <<EOF | kubectl apply -n "$NS" -f - >/dev/null 2>&1
apiVersion: v1
kind: Pod
metadata:
  name: kata-net-test
spec:
  runtimeClassName: ${TEST_RUNTIME_CLASS}
  restartPolicy: Never
  containers:
  - name: curl
    image: curlimages/curl:8.8.0
    command: ["sh","-c","sleep 1200"]
    securityContext:
      allowPrivilegeEscalation: false
      capabilities:
        drop: ["ALL"]
EOF

if kubectl wait -n "$NS" --for=condition=Ready "pod/$TEST_POD" --timeout="$TIMEOUT" >/dev/null 2>&1; then
  pass "Kata test pod became Ready"
else
  warn "Kata test pod did not become Ready within $TIMEOUT (check image pull/policy/runtime issues)"
fi

test_egress_blocked() {
  local name="$1"
  local url="$2"
  if kubectl exec -n "$NS" "$TEST_POD" -- curl -m 5 -sS "$url" >/dev/null 2>&1; then
    fail "Egress test '$name' succeeded to $url (expected blocked by deny-by-default)"
  else
    pass "Egress test '$name' blocked as expected"
  fi
}

if kubectl get pod -n "$NS" "$TEST_POD" >/dev/null 2>&1; then
  test_egress_blocked "public-ip" "http://1.1.1.1"
  test_egress_blocked "metadata-ip" "http://169.254.169.254"
  test_egress_blocked "kubernetes-svc" "https://kubernetes.default.svc"
else
  warn "Skipping egress tests because test pod is missing"
fi

SA="$(kubectl get pod -n "$NS" "$POD" -o jsonpath='{.spec.serviceAccountName}' 2>/dev/null || true)"
if [[ -z "$SA" ]]; then
  fail "Could not determine service account for target pod"
else
  info "ServiceAccount: $SA"
  CAN_LIST_SECRETS="$(kubectl auth can-i --as="system:serviceaccount:${NS}:${SA}" list secrets -n "$NS" 2>/dev/null || true)"
  CAN_CREATE_PODS="$(kubectl auth can-i --as="system:serviceaccount:${NS}:${SA}" create pods -n "$NS" 2>/dev/null || true)"
  CAN_GET_NODES="$(kubectl auth can-i --as="system:serviceaccount:${NS}:${SA}" get nodes 2>/dev/null || true)"

  [[ "$CAN_LIST_SECRETS" == "no" ]] && pass "SA cannot list secrets" || warn "SA can list secrets"
  [[ "$CAN_CREATE_PODS" == "no" ]] && pass "SA cannot create pods" || warn "SA can create pods"
  [[ "$CAN_GET_NODES" == "no" ]] && pass "SA cannot get nodes" || warn "SA can get nodes"
fi

PSA_ENFORCE="$(kubectl get ns "$NS" -o jsonpath='{.metadata.labels.pod-security\.kubernetes\.io/enforce}' 2>/dev/null || true)"
if [[ -n "$PSA_ENFORCE" ]]; then
  info "Namespace pod-security enforce label: $PSA_ENFORCE"
  if [[ "$PSA_ENFORCE" == "restricted" || "$PSA_ENFORCE" == "baseline" ]]; then
    pass "Namespace has Pod Security enforce label"
  else
    warn "Namespace Pod Security enforce label is '$PSA_ENFORCE'"
  fi
else
  warn "Namespace missing pod-security.kubernetes.io/enforce label"
fi

NODE_OS_LINES="$(kubectl get nodes -o jsonpath='{range .items[*]}{.metadata.name}{"\t"}{.status.nodeInfo.osImage}{"\n"}{end}' 2>/dev/null || true)"
if [[ -n "$NODE_OS_LINES" ]]; then
  info "Node OS inventory:"
  echo "$NODE_OS_LINES"
else
  warn "Could not collect node OS inventory"
fi

echo
echo "Summary: PASS=$PASS_COUNT FAIL=$FAIL_COUNT WARN=$WARN_COUNT"

if [[ $FAIL_COUNT -gt 0 ]]; then
  exit 1
fi

exit 0
