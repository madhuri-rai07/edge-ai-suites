#!/usr/bin/env python3
# SPDX-FileCopyrightText: (C) 2026 Intel Corporation
# SPDX-License-Identifier: Apache-2.0
"""
Mock Catalog Service (Tier 2, cloud) — token-based install model, §4.5
step 3-6 of edge-ai-catalog-design.md:

  "3. Catalog Service does the license/entitlement/compatibility checks and
      returns a short-lived, single-use opaque install token to the browser
      (same HTTPS response) — not the install payload itself.
   ...
   5. Device Agent redeems the token itself, over its own outbound HTTPS
      connection to Catalog Service. Catalog Service validates the token
      (unexpired, unused), marks it consumed, and returns the real install
      plan directly to the Device Agent."

Runs plain HTTP on a normal "internet" port (8443 here) — this is NOT the
loopback leg, it stands in for the real catalog.intel.com HTTPS endpoint.
Two endpoints:
  POST /install                    -> browser calls this; returns
                                       {install_token, expires_in}
  GET  /install/redeem/{token}     -> Device Agent calls this itself
                                       (own outbound call, browser never
                                       sees this); returns the install plan
                                       and marks the token consumed
"""
import datetime
import json
import secrets
from http.server import BaseHTTPRequestHandler, HTTPServer
from urllib.parse import urlparse

PORT = 8443
TOKEN_TTL_SECONDS = 120

# In-memory token store: token -> {app_version_id, system_profile, expires_at, consumed}
# Stands in for the design doc's DynamoDB/Redis-with-TTL token store (§9.1).
_tokens = {}


def _now():
    return datetime.datetime.now(datetime.timezone.utc)


class CatalogHandler(BaseHTTPRequestHandler):
    def log_message(self, fmt, *args):
        print(f"[catalog-service] {self.address_string()} - {fmt % args}")

    def _send_json(self, code, obj):
        body = json.dumps(obj).encode()
        self.send_response(code)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def do_POST(self):
        if self.path != "/install":
            self._send_json(404, {"error": "not found"})
            return

        length = int(self.headers.get("Content-Length", 0))
        body = json.loads(self.rfile.read(length) or b"{}")
        app_version_id = body.get("app_version_id")
        system_profile = body.get("system_profile", {})

        print(f"[catalog-service] POST /install: app_version_id={app_version_id!r} "
              f"system_profile={system_profile}")

        # Server-side compatibility pre-check (advisory only — the
        # authoritative check happens locally on the Device Agent against
        # the redeemed plan, per design doc §8 "Compatibility check").
        compatible = system_profile.get("os", "").startswith("Ubuntu")
        if not compatible:
            print("[catalog-service] system profile marked incompatible (demo rule); "
                  "still issuing a token so the Device Agent can demonstrate its own check.")

        install_token = secrets.token_urlsafe(32)
        _tokens[install_token] = {
            "app_version_id": app_version_id,
            "consumed": False,
            "expires_at": _now() + datetime.timedelta(seconds=TOKEN_TTL_SECONDS),
        }
        print(f"[catalog-service] issued install_token={install_token!r} "
              f"(expires in {TOKEN_TTL_SECONDS}s, single-use)")

        self._send_json(200, {"install_token": install_token, "expires_in": TOKEN_TTL_SECONDS})

    def do_GET(self):
        parsed = urlparse(self.path)
        parts = parsed.path.strip("/").split("/")
        if len(parts) == 3 and parts[0] == "install" and parts[1] == "redeem":
            self._handle_redeem(parts[2])
            return
        self._send_json(404, {"error": "not found"})

    def _handle_redeem(self, token):
        print(f"[catalog-service] GET /install/redeem/{token!r} "
              f"(called by Device Agent's own outbound connection)")
        entry = _tokens.get(token)
        if entry is None:
            self._send_json(404, {"error": "unknown install_token"})
            return
        if entry["consumed"]:
            self._send_json(410, {"error": "install_token already consumed (single-use)"})
            return
        if _now() > entry["expires_at"]:
            self._send_json(410, {"error": "install_token expired"})
            return

        # Mark consumed BEFORE returning — single-use, prevents replay even
        # if the response is somehow duplicated in flight.
        entry["consumed"] = True

        plan = {
            "app_version_id": entry["app_version_id"],
            "compose_ref": "registry.edge-ai-catalog.example/apps/demo-app:1.2.3",
            "image_refs": ["registry.edge-ai-catalog.example/apps/demo-app@sha256:deadbeef"],
            "settings": {"LOG_LEVEL": "info"},
            "license_terms_id": "lic-demo-app-1.2.3",
            "compatibility_rules": {"os": "Ubuntu", "min_ram_gb": 4},
        }
        print(f"[catalog-service] token redeemed OK, returning install plan for "
              f"app_version_id={entry['app_version_id']!r}; token now consumed")
        self._send_json(200, plan)


def main():
    server = HTTPServer(("127.0.0.1", PORT), CatalogHandler)
    print(f"[catalog-service] listening on http://127.0.0.1:{PORT} (stand-in for catalog.intel.com)")
    server.serve_forever()


if __name__ == "__main__":
    main()
