// SPDX-FileCopyrightText: (C) 2026 Intel Corporation
// SPDX-License-Identifier: Apache-2.0
//
// Points at the local reference-implementation Catalog Service and the
// local Device Agent. In production these would be catalog.intel.com and
// https://127.0.0.1:<device-agent-port>.
const CATALOG_API = "http://10.223.22.94:8000/api/v1";
const CATALOG_ROOT = "http://10.223.22.94:8000";
// TEST-ONLY: pointed at the host's LAN IP so a remote browser (e.g. a
// Windows laptop) can reach the Device Agent. Production/normal use must
// keep this as https://127.0.0.1:<port> — see device_agent.py's HOST var.
const DEVICE_AGENT = "https://10.223.22.94:47100";
