// SPDX-FileCopyrightText: (C) 2026 Intel Corporation
// SPDX-License-Identifier: Apache-2.0
//
// Flow C1 — Intel Admin review.
async function loadAdminReviews() {
  const list = document.getElementById("admin-list");
  list.innerHTML = "Loading...";
  try {
    const reviews = await apiFetch("/admin/reviews");
    if (reviews.length === 0) {
      list.innerHTML = "<p>No versions pending review.</p>";
      return;
    }
    list.innerHTML = "";
    for (const v of reviews) {
      const card = document.createElement("div");
      card.className = "app-card";
      card.innerHTML = `
        <h3>Version ${v.version} <small>(app ${v.app_id})</small></h3>
        <p>Status: ${v.status}</p>
        <button data-action="approve">Approve</button>
        <button data-action="send-back">Send back</button>
        <button data-action="reject">Reject</button>
      `;
      card.querySelectorAll("button").forEach((btn) => {
        btn.addEventListener("click", async () => {
          const action = btn.dataset.action;
          const body =
            action === "approve" ? undefined : JSON.stringify({ comments: prompt("Comments?") || "" });
          await apiFetch(`/admin/reviews/${v.id}/${action}`, { method: "POST", body });
          loadAdminReviews();
        });
      });
      list.appendChild(card);
    }
  } catch (e) {
    list.innerHTML = `<p class="status-box bad">Failed to load reviews: ${e.message}</p>`;
  }
}

document.addEventListener("DOMContentLoaded", () => {
  window.loadAdminReviews = loadAdminReviews;
  document.querySelector('[data-tab="admin"]').addEventListener("click", loadAdminReviews);
});
