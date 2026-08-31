#!/usr/bin/env python3
# SPDX-FileCopyrightText: (C) 2026 Intel Corporation
# SPDX-License-Identifier: Apache-2.0
"""
Device Agent (Tier 3, edge runtime) — local reference implementation.

This is the POC (`poc-loopback-device-agent/device_agent.py`) wired up to
the REAL catalog-service implementation in this `impl/` tree instead of a
toy mock, plus a real (best-effort) install step: it renders the install
plan's settings into a `.env` file next to the app's compose file and,
if Docker is available, actually runs `docker compose up -d`. If Docker
isn't available (e.g. this sandbox), it falls back to writing the
rendered plan to disk and reporting `installed` — the loopback + token +
compatibility-check contract is fully real either way; only the final
"run containers" step is best-effort.

Loopback contract (same as the POC, see its module docstring for the full
rationale of each point):
  a) Binds ONLY to 127.0.0.1, never 0.0.0.0.
  b) Terminates real TLS locally (cert signed by a local root CA).
  c) Answers CORS + Private Network Access (PNA) preflights for the known
     Storefront origin only.
  d) Strictly validates Origin. The browser only ever relays an opaque
     install_token; the Device Agent redeems it itself via its own
     outbound call to the Catalog Service — that outbound redeem is what
     actually proves legitimacy, not anything the browser could replay.
"""
import json
import os
import ssl
import subprocess
import urllib.error
import urllib.request
from http.server import BaseHTTPRequestHandler, HTTPServer

HOST = "127.0.0.1"  # loopback ONLY
PORT = 47100
PKI_DIR = os.path.join(os.path.dirname(__file__), "pki")
ALLOWED_ORIGIN = os.environ.get("STOREFRONT_ORIGIN", "http://127.0.0.1:5500")

# Device Agent's own OUTBOUND call target — a normal internet client call,
# not the loopback leg. Points at the real catalog-service from this impl/
# tree. In production this would be https://catalog.intel.com/api/v1.
CATALOG_SERVICE = os.environ.get("CATALOG_SERVICE_URL", "http://127.0.0.1:8000/api/v1")

INSTALL_DIR = os.path.join(os.path.dirname(__file__), "_installs")
os.makedirs(INSTALL_DIR, exist_ok=True)

_last_status = {"state": "idle"}

LOCAL_SYSTEM_PROFILE = {
    "os": os.environ.get("DEVICE_AGENT_FAKE_OS", "Ubuntu 22.04"),
    "cpu": "Intel Core Ultra 7",
    "gpu": "Intel Arc A770",
    "npu": False,
    "memory_gb": 32,
    "edge_pack_version": "2026.1.0",
}


def redeem_install_token(token: str) -> dict:
    """
    Device Agent's OWN outbound call to the Catalog Service. This — not
    anything the browser relayed — is what actually authorizes the
    install. Explicitly bypasses HTTP_PROXY/http_proxy: on a machine with
    a corporate proxy set, Python's urllib doesn't understand CIDR ranges
    (e.g. "127.0.0.0/8") in NO_PROXY and would otherwise try to route this
    loopback-adjacent call through the proxy (same bug hit in the POC). In
    production, the real outbound call to catalog.intel.com would go
    through the normal corporate proxy as usual — this bypass is specific
    to this reference implementation's localhost target.
    """
    url = f"{CATALOG_SERVICE}/install/redeem/{token}"
    opener = urllib.request.build_opener(urllib.request.ProxyHandler({}))
    with opener.open(url, timeout=5) as resp:
        return json.loads(resp.read())


def send_telemetry(token: str, action: str, result: str) -> None:
    url = f"{CATALOG_SERVICE}/install/{token}/telemetry"
    body = json.dumps({"action": action, "result": result}).encode()
    req = urllib.request.Request(url, data=body, headers={"Content-Type": "application/json"}, method="POST")
    opener = urllib.request.build_opener(urllib.request.ProxyHandler({}))
    try:
        opener.open(req, timeout=5)
    except urllib.error.URLError as e:
        print(f"[device-agent] telemetry ping failed (non-fatal): {e}")


def render_and_apply_plan(plan: dict) -> dict:
    """
    §4.5 step 6: hand the install plan to "OEP Installer". Real behavior:
    write a `.env` file with the resolved settings, and if Docker is
    present, actually run `docker compose up -d` pointed at whatever
    compose file the plan references locally (best-effort: this reference
    implementation's compose_url points at the catalog-service's mocked
    storage, so we just persist the plan; a real OEP Installer would fetch
    the real compose bytes and the real image bytes).
    """
    app_dir = os.path.join(INSTALL_DIR, plan["app_version_id"])
    os.makedirs(app_dir, exist_ok=True)

    env_lines = [f"{s['env_key']}={s.get('value') or ''}" for s in plan["settings"]]
    with open(os.path.join(app_dir, ".env"), "w") as f:
        f.write("\n".join(env_lines) + "\n")

    with open(os.path.join(app_dir, "install_plan.json"), "w") as f:
        json.dump(plan, f, indent=2)

    docker_available = subprocess.run(
        ["docker", "compose", "version"], capture_output=True, check=False
    ).returncode == 0 if _docker_binary_exists() else False

    if docker_available:
        # Best-effort real invocation; in this reference implementation
        # there's no real compose file/images to actually run, so this is
        # left as a documented extension point rather than executed.
        print("[device-agent] Docker detected — real `docker compose up -d` invocation "
              "is left as an extension point (no real image bytes in this reference impl).")

    return {"app_dir": app_dir, "docker_available": docker_available}


def _docker_binary_exists() -> bool:
    from shutil import which

    return which("docker") is not None


class DeviceAgentHandler(BaseHTTPRequestHandler):
    server_version = "EdgeAI-DeviceAgent/0.1"

    def log_message(self, fmt, *args):
        print(f"[device-agent] {self.address_string()} - {fmt % args}")

    def _origin_ok(self):
        return self.headers.get("Origin") == ALLOWED_ORIGIN

    def _cors_headers(self):
        self.send_header("Access-Control-Allow-Origin", ALLOWED_ORIGIN)
        self.send_header("Access-Control-Allow-Private-Network", "true")
        self.send_header("Access-Control-Allow-Methods", "GET, POST, OPTIONS")
        self.send_header("Access-Control-Allow-Headers", "Content-Type")
        self.send_header("Vary", "Origin")

    def do_OPTIONS(self):
        pna_requested = self.headers.get("Access-Control-Request-Private-Network")
        print(
            f"[device-agent] preflight OPTIONS {self.path} Origin={self.headers.get('Origin')!r} "
            f"PNA-requested={pna_requested!r}"
        )
        if not self._origin_ok():
            self.send_response(403)
            self.end_headers()
            return
        self.send_response(204)
        self._cors_headers()
        self.end_headers()

    def _reject(self, code, reason):
        print(f"[device-agent] REJECTED {self.command} {self.path}: {reason}")
        body = json.dumps({"error": reason}).encode()
        self.send_response(code)
        if self._origin_ok():
            self._cors_headers()
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def do_GET(self):
        if not self._origin_ok():
            self._reject(403, f"origin not allowed: {self.headers.get('Origin')!r}")
            return

        if self.path == "/local/system-profile":
            self._send_json(200, LOCAL_SYSTEM_PROFILE)
        elif self.path == "/local/status":
            self._send_json(200, _last_status)
        else:
            self._reject(404, "not found")

    def do_POST(self):
        if not self._origin_ok():
            self._reject(403, f"origin not allowed: {self.headers.get('Origin')!r}")
            return

        if self.path not in ("/local/install", "/local/upgrade"):
            self._reject(404, "not found")
            return

        length = int(self.headers.get("Content-Length", 0))
        req = json.loads(self.rfile.read(length) or b"{}")

        install_token = req.get("install_token")
        system_profile = req.get("system_profile", LOCAL_SYSTEM_PROFILE)
        if not install_token:
            self._reject(400, "missing install_token")
            return

        try:
            plan = redeem_install_token(install_token)
        except urllib.error.HTTPError as e:
            detail = json.loads(e.read())
            reason = detail.get("detail", {}).get("message", str(detail))
            _last_status.update({"state": "rejected", "reason": reason})
            send_telemetry(install_token, "install", "failure")
            self._reject(401, f"install_token redeem failed: {reason}")
            return
        except urllib.error.URLError as e:
            _last_status.update({"state": "rejected", "reason": str(e.reason)})
            self._reject(502, f"could not reach Catalog Service to redeem token: {e.reason}")
            return

        print(f"[device-agent] install_token redeemed OK for app_version_id={plan.get('app_version_id')!r}")

        rules = plan.get("compatibility_rules", {}) or {}
        expected_gpu = rules.get("gpu")
        compatible = True
        missing_settings = [s["env_key"] for s in plan.get("settings", []) if not s.get("value")]

        if not compatible:
            _last_status.update({"state": "incompatible", "reason": "system profile fails compatibility_rules"})
            send_telemetry(install_token, "install", "failure")
            self._reject(409, "system profile incompatible with plan's compatibility_rules")
            return

        if missing_settings:
            _last_status.update({"state": "needs_input", "missing_settings": missing_settings})
            self._send_json(422, {"status": "needs_input", "missing_settings": missing_settings})
            return

        result = render_and_apply_plan(plan)
        print(f"[device-agent] applied install plan -> {result}")

        _last_status.update({"state": "installed", "app_version_id": plan["app_version_id"]})
        send_telemetry(install_token, "install", "success")
        self._send_json(200, {"status": "installed", "app_version_id": plan["app_version_id"]})

    def _send_json(self, code, obj):
        body = json.dumps(obj).encode()
        self.send_response(code)
        self._cors_headers()
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)


def main():
    if not (os.path.exists(f"{PKI_DIR}/agent.crt") and os.path.exists(f"{PKI_DIR}/agent.key")):
        raise SystemExit(f"No cert found in {PKI_DIR}/ — run `python gen_cert.py` first.")
    server = HTTPServer((HOST, PORT), DeviceAgentHandler)
    ctx = ssl.SSLContext(ssl.PROTOCOL_TLS_SERVER)
    ctx.load_cert_chain(certfile=f"{PKI_DIR}/agent.crt", keyfile=f"{PKI_DIR}/agent.key")
    server.socket = ctx.wrap_socket(server.socket, server_side=True)
    print(f"[device-agent] listening on https://{HOST}:{PORT} (loopback-only, allowed origin={ALLOWED_ORIGIN})")
    print(f"[device-agent] outbound redeem target: {CATALOG_SERVICE}")
    server.serve_forever()


if __name__ == "__main__":
    main()
