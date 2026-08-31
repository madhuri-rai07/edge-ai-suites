#!/usr/bin/env python3
# SPDX-FileCopyrightText: (C) 2026 Intel Corporation
# SPDX-License-Identifier: Apache-2.0
"""
Mock Device Agent (Tier 3, edge runtime) — implements the loopback contract
described in §3.1.1 and §4.5 of edge-ai-catalog-design.md, token-based model:

  a) Binds ONLY to 127.0.0.1 (loopback), never 0.0.0.0.
  b) Terminates real TLS locally (cert signed by the "pre-installed" local
     root CA from gen_cert.py — Docker Desktop-style trust).
  c) Answers CORS + Private Network Access (PNA) preflights, and only for
     the known Storefront origin.
  d) Defense in depth: strictly validates the Origin header. The browser
     only ever relays an opaque install_token — it is meaningless on its
     own. The Device Agent redeems it itself, over its OWN outbound HTTPS
     call to the Catalog Service (ordinary connection, no custom PKI) —
     this is what actually proves the request is legitimate, not a
     signature the browser could have replayed.

Endpoints:
  OPTIONS *                      -> CORS/PNA preflight response
  GET  /local/system-profile     -> returns a SystemProfile JSON
  POST /local/install            -> body = {install_token, system_profile};
                                     Device Agent redeems the token itself
                                     against the Catalog Service (outbound),
                                     checks compatibility locally, then
                                     "hands the plan to OEP Installer"
                                     (simulated) and records status
  GET  /local/status              -> last known install status
"""
import json
import ssl
import urllib.error
import urllib.request
from http.server import BaseHTTPRequestHandler, HTTPServer

HOST = "127.0.0.1"  # loopback ONLY — never 0.0.0.0, per §3.1.1(a)
PORT = 47100
PKI_DIR = "pki"
ALLOWED_ORIGIN = "https://catalog.intel.com"

# Normal outbound HTTPS/HTTP call target for redeeming install tokens — this
# is the Device Agent acting as a regular internet client, NOT the loopback
# leg. In the POC the mock Catalog Service runs plain HTTP; in production
# this would be ordinary public-CA-trusted HTTPS to catalog.intel.com.
CATALOG_SERVICE = "http://127.0.0.1:8443"

_last_status = {"state": "idle"}


def redeem_install_token(token: str) -> dict:
    """
    Device Agent's OWN outbound call — this is what actually authorizes the
    install, not anything the browser relayed. Raises urllib.error.HTTPError
    on 404/410 (unknown/expired/already-consumed token).

    NOTE: explicitly bypasses any HTTP_PROXY/http_proxy env vars. In this
    POC the "outbound" target is 127.0.0.1 (mock Catalog Service); Python's
    urllib does not understand CIDR ranges (e.g. "127.0.0.0/8") in NO_PROXY,
    so on a machine with a corporate proxy set it would otherwise try to
    route this loopback-adjacent call through the proxy and fail. In
    production, the real Device Agent's outbound call to catalog.intel.com
    would go through the normal corporate proxy as usual.
    """
    url = f"{CATALOG_SERVICE}/install/redeem/{token}"
    opener = urllib.request.build_opener(urllib.request.ProxyHandler({}))
    with opener.open(url, timeout=5) as resp:
        return json.loads(resp.read())


class DeviceAgentHandler(BaseHTTPRequestHandler):
    server_version = "EdgeAI-DeviceAgent-POC/0.2"

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
        # §3.1.1(c): PNA preflight — must answer
        # Access-Control-Allow-Private-Network: true plus CORS headers naming
        # the exact calling origin.
        pna_requested = self.headers.get("Access-Control-Request-Private-Network")
        print(f"[device-agent] preflight OPTIONS {self.path} Origin={self.headers.get('Origin')!r} "
              f"PNA-requested={pna_requested!r}")
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
        # §3.1.1(d): strictly validate Origin even for reads.
        if not self._origin_ok():
            self._reject(403, f"origin not allowed: {self.headers.get('Origin')!r}")
            return

        if self.path == "/local/system-profile":
            profile = {
                "os": "Ubuntu 22.04",
                "cpu": "Intel Core Ultra 7",
                "gpu": "Intel Arc A770",
                "ram_gb": 32,
                "edge_pack_version": "2026.1.0",
            }
            self._send_json(200, profile)
        elif self.path == "/local/status":
            self._send_json(200, _last_status)
        else:
            self._reject(404, "not found")

    def do_POST(self):
        if not self._origin_ok():
            self._reject(403, f"origin not allowed: {self.headers.get('Origin')!r}")
            return

        if self.path != "/local/install":
            self._reject(404, "not found")
            return

        length = int(self.headers.get("Content-Length", 0))
        req = json.loads(self.rfile.read(length) or b"{}")

        install_token = req.get("install_token")
        system_profile = req.get("system_profile", {})
        if not install_token:
            self._reject(400, "missing install_token")
            return

        # The browser only relayed an opaque token — it never saw the real
        # payload. The Device Agent redeems the token ITSELF, over its own
        # outbound connection, which is what actually proves legitimacy.
        try:
            plan = redeem_install_token(install_token)
        except urllib.error.HTTPError as e:
            reason = json.loads(e.read()).get("error", "redeem failed")
            _last_status.update({"state": "rejected", "reason": reason})
            self._reject(401, f"install_token redeem failed: {reason}")
            return
        except urllib.error.URLError as e:
            _last_status.update({"state": "rejected", "reason": str(e.reason)})
            self._reject(502, f"could not reach Catalog Service to redeem token: {e.reason}")
            return

        print(f"[device-agent] install_token redeemed OK for "
              f"app_version_id={plan.get('app_version_id')!r}")

        # §4.5 step 5: check SystemProfile against plan's compatibility_rules
        # locally — does NOT simply trust the server's advisory pre-check.
        rules = plan.get("compatibility_rules", {})
        compatible = system_profile.get("os", "").startswith(rules.get("os", ""))

        if not compatible:
            _last_status.update({"state": "incompatible", "reason": "system profile fails compatibility_rules"})
            self._reject(409, "system profile incompatible with plan's compatibility_rules")
            return

        # §4.5 step 6: "hands the install plan to the OEP Installer" — simulated here.
        install_plan = {
            "app_version_id": plan["app_version_id"],
            "compose_ref": plan["compose_ref"],
            "image_refs": plan["image_refs"],
            "settings": plan["settings"],
        }
        print(f"[device-agent] handing install plan to OEP Installer (simulated): {install_plan}")
        print("[device-agent] (simulated) OEP Installer: pulling images, running `docker compose up` ...")

        _last_status.update({"state": "installed", "app_version_id": plan["app_version_id"]})
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
    server = HTTPServer((HOST, PORT), DeviceAgentHandler)
    ctx = ssl.SSLContext(ssl.PROTOCOL_TLS_SERVER)
    ctx.load_cert_chain(certfile=f"{PKI_DIR}/agent.crt", keyfile=f"{PKI_DIR}/agent.key")
    server.socket = ctx.wrap_socket(server.socket, server_side=True)
    print(f"[device-agent] listening on https://{HOST}:{PORT} (loopback-only, allowed origin={ALLOWED_ORIGIN})")
    server.serve_forever()


if __name__ == "__main__":
    main()
