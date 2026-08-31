// SPDX-FileCopyrightText: (C) 2026 Intel Corporation
// SPDX-License-Identifier: Apache-2.0
//
// Shared app shell: tab switching + the mocked-auth role switcher. See
// catalog-service/app/auth.py's module docstring — this is standing in
// for real SSO session cookies; it just sets X-Debug-* headers on every
// request.
const SEED_USERS = [
  { email: "isv1@example-vendor.com", role: "ISV", label: "Isabel Vendor (ISV)" },
  { email: "admin1@intel.com", role: "ADMIN", label: "Ada Min (Intel Admin)" },
  { email: "si1@example-integrator.com", role: "SI", label: "Sam Integrator (SI)" },
];

function currentUser() {
  const idx = document.getElementById("user-select").value;
  return SEED_USERS[idx];
}

async function apiFetch(path, opts = {}) {
  const user = currentUser();
  const headers = {
    "Content-Type": "application/json",
    "X-Debug-User-Email": user.email,
    "X-Debug-Role": user.role,
    ...(opts.headers || {}),
  };
  const res = await fetch(`${CATALOG_API}${path}`, { ...opts, headers });
  if (!res.ok) {
    const text = await res.text();
    throw new Error(`${opts.method || "GET"} ${path} -> ${res.status}: ${text}`);
  }
  const contentType = res.headers.get("content-type") || "";
  return contentType.includes("application/json") ? res.json() : null;
}

document.addEventListener("DOMContentLoaded", () => {
  const select = document.getElementById("user-select");
  SEED_USERS.forEach((u, i) => {
    const opt = document.createElement("option");
    opt.value = i;
    opt.textContent = u.label;
    select.appendChild(opt);
  });

  document.querySelectorAll(".tab-btn").forEach((btn) => {
    btn.addEventListener("click", () => {
      document.querySelectorAll(".tab-btn").forEach((b) => b.classList.remove("active"));
      document.querySelectorAll(".tab-panel").forEach((p) => p.classList.remove("active"));
      btn.classList.add("active");
      document.getElementById(`tab-${btn.dataset.tab}`).classList.add("active");
    });
  });

  document.getElementById("seed-btn").addEventListener("click", async () => {
    const res = await fetch(`${CATALOG_ROOT}/dev/seed`, { method: "POST" });
    const body = await res.json();
    alert(`Seeded ${body.users.length} demo users. Reload catalog/admin tabs.`);
    if (window.loadCatalog) window.loadCatalog();
    if (window.loadAdminReviews) window.loadAdminReviews();
  });
});
