#!/usr/bin/env bash
# SPDX-FileCopyrightText: (C) 2026 Intel Corporation
# SPDX-License-Identifier: Apache-2.0
#
# Convenience script: starts catalog-service (8000), device-agent (47100,
# loopback TLS), and the storefront static server (5500) together. Ctrl-C
# stops all three.
set -euo pipefail
cd "$(dirname "$0")"

if [ ! -d .venv ]; then
  echo "Creating venv + installing deps (first run only)..."
  python3 -m venv .venv
  # shellcheck disable=SC1091
  source .venv/bin/activate
  pip install --quiet --upgrade pip
  pip install --quiet fastapi "uvicorn[standard]" sqlalchemy pydantic pyyaml \
    python-multipart httpx pytest cryptography email-validator requests
else
  # shellcheck disable=SC1091
  source .venv/bin/activate
fi

if [ ! -f device-agent/pki/agent.crt ]; then
  echo "Generating Device Agent loopback TLS cert..."
  (cd device-agent && python gen_cert.py)
fi

# Unset any inherited proxy env vars for these loopback/localhost-only
# processes — see device_agent.py's redeem_install_token() docstring for
# why a corporate proxy breaks loopback-adjacent outbound calls.
export http_proxy= https_proxy= HTTP_PROXY= HTTPS_PROXY=
export STOREFRONT_ORIGIN="http://127.0.0.1:5500"
export CATALOG_SERVICE_URL="http://127.0.0.1:8000/api/v1"

echo "Starting catalog-service on :8000 ..."
(cd catalog-service && uvicorn app.main:app --port 8000 --host 127.0.0.1) &
CATALOG_PID=$!

echo "Starting device-agent on :47100 (loopback, TLS) ..."
(cd device-agent && python device_agent.py) &
AGENT_PID=$!

echo "Starting storefront static server on :5500 ..."
(cd storefront && python3 -m http.server 5500 --bind 127.0.0.1) &
STOREFRONT_PID=$!

sleep 2
echo ""
echo "Seeding demo users (isv1@example-vendor.com, admin1@intel.com, si1@example-integrator.com)..."
curl -s -X POST http://127.0.0.1:8000/dev/seed >/dev/null && echo "Seeded."
echo ""
echo "Open http://127.0.0.1:5500 in a browser."
echo "NOTE: the Device Agent uses a self-signed local cert (device-agent/pki/ca.crt)."
echo "On first use, open https://127.0.0.1:47100/local/status directly and accept the"
echo "browser's security exception once (see README.md 'Known limitation' section)."
echo ""
echo "Press Ctrl-C to stop all three services."

trap 'kill $CATALOG_PID $AGENT_PID $STOREFRONT_PID 2>/dev/null' EXIT
wait
