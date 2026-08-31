#!/usr/bin/env python3
# SPDX-FileCopyrightText: (C) 2026 Intel Corporation
# SPDX-License-Identifier: Apache-2.0
"""
Simulates the Storefront browser — the sole relay between Catalog Service
(cloud) and Device Agent (local loopback), per §3.1 / §3.1.1 / §4.5,
token-based install model.

Flow exercised:
  1. GET  Device Agent /local/system-profile          (loopback HTTPS)
  2. POST Catalog Service /install                     (normal internet HTTPS)
                                                         -> {install_token, expires_in}
  3. POST {install_token} -> Device Agent /local/install (loopback HTTPS)
     (Device Agent redeems the token itself against Catalog Service, over
      its own OUTBOUND connection — the browser never sees the real plan)
  4. GET  Device Agent /local/status

Plus two negative cases proving the "defense-in-depth" claims in §3.1.1(d):
  - a request with a forged Origin header is rejected (403)
  - replaying the SAME install_token a second time is rejected, because the
    Device Agent's own redeem call fails server-side (single-use token
    already consumed) — this replaces the old "tampered manifest" test,
    since there's no signed payload left for the browser to tamper with.

Trust model note: we trust our own CA (pki/ca.crt) the way a browser would
trust a pre-installed root CA (§3.1.1 option b) — NOT Python's default CA
bundle, and NOT verify=False.
"""
import json

import requests

DEVICE_AGENT = "https://127.0.0.1:47100"
CATALOG_SERVICE = "http://127.0.0.1:8443"
ALLOWED_ORIGIN = "https://catalog.intel.com"
PKI_DIR = "pki"

session = requests.Session()
session.verify = f"{PKI_DIR}/ca.crt"  # trust only the "pre-installed" local root CA


def step(title):
    print(f"\n=== {title} ===")


def main():
    step("1. Browser -> Device Agent (loopback): GET /local/system-profile")
    r = session.get(
        f"{DEVICE_AGENT}/local/system-profile",
        headers={"Origin": ALLOWED_ORIGIN},
    )
    r.raise_for_status()
    system_profile = r.json()
    print("SystemProfile:", system_profile)

    step("2. Browser -> Catalog Service (internet): POST /install")
    r = requests.post(
        f"{CATALOG_SERVICE}/install",
        json={"app_version_id": "demo-app@1.2.3", "system_profile": system_profile},
    )
    r.raise_for_status()
    token_response = r.json()
    install_token = token_response["install_token"]
    print("Install token issued (opaque, single-use):", json.dumps(token_response, indent=2))

    step("3. Browser -> Device Agent (loopback): POST /local/install {install_token}")
    print("(Device Agent will redeem this token itself, outbound, against Catalog Service)")
    r = session.post(
        f"{DEVICE_AGENT}/local/install",
        headers={"Origin": ALLOWED_ORIGIN},
        json={"install_token": install_token, "system_profile": system_profile},
    )
    print("Status:", r.status_code, r.json())
    assert r.status_code == 200

    step("4. Browser -> Device Agent (loopback): GET /local/status")
    r = session.get(f"{DEVICE_AGENT}/local/status", headers={"Origin": ALLOWED_ORIGIN})
    print("Status:", r.status_code, r.json())

    step("5. Negative test: forged Origin header is rejected")
    r = session.get(
        f"{DEVICE_AGENT}/local/system-profile",
        headers={"Origin": "https://evil.example.com"},
    )
    print("Status:", r.status_code, r.json())
    assert r.status_code == 403

    step("6. Negative test: replaying the same (already-consumed) install_token is rejected")
    r = session.post(
        f"{DEVICE_AGENT}/local/install",
        headers={"Origin": ALLOWED_ORIGIN},
        json={"install_token": install_token, "system_profile": system_profile},
    )
    print("Status:", r.status_code, r.json())
    assert r.status_code == 401

    print("\nAll POC steps completed successfully.")


if __name__ == "__main__":
    main()
