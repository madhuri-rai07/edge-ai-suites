// SPDX-FileCopyrightText: (C) 2026 Intel Corporation
// SPDX-License-Identifier: Apache-2.0
//
// Flow B1 (onboarding) — the 2-screen UX described in
// technical-flows.md §B1 and edge-ai-catalog-design.md §4.3.
let obState = {};

function obLog(msg) {
  const el = document.getElementById("onboarding-log");
  el.textContent += msg + "\n";
}

async function uploadFile(uploadUrl, file) {
  await fetch(uploadUrl, { method: "PUT", body: file });
}

document.getElementById("screen1-form").addEventListener("submit", async (e) => {
  e.preventDefault();
  const el = document.getElementById("onboarding-log");
  el.textContent = "";
  const form = new FormData(e.target);

  try {
    const license = await apiFetch("/licenses", {
      method: "POST",
      body: JSON.stringify({
        title: form.get("license_title"),
        text_url: form.get("license_url"),
        version: "1.0",
      }),
    });
    obLog(`Created license ${license.id}`);

    const app = await apiFetch("/apps", {
      method: "POST",
      body: JSON.stringify({
        name: form.get("name"),
        category: form.get("category"),
        description: form.get("description"),
        tags: [],
      }),
    });
    obState.appId = app.id;
    await apiFetch(`/apps/${app.id}`, { method: "PUT", body: JSON.stringify({ license_id: license.id }) });
    obLog(`Created draft app ${app.id} (${app.name})`);

    const upload = await apiFetch(`/apps/${app.id}/assets/icon-upload-url`, { method: "POST" });
    const file = form.get("compose_file");
    await uploadFile(upload.upload_url, file);
    obLog(`Uploaded compose file to ${upload.upload_url}`);

    const version = await apiFetch(`/apps/${app.id}/versions`, {
      method: "POST",
      body: JSON.stringify({
        deployment_kind: "compose",
        version: "1.0.0",
        deployment_file_url: upload.upload_url,
      }),
    });
    obState.versionId = version.id;
    obLog(`Created draft version ${version.id}`);

    const parsed = await apiFetch(`/apps/${app.id}/versions/${version.id}/parse-deployment`, { method: "POST" });
    obLog(`Parsed compose: ${parsed.images.length} image(s), ${parsed.settings.length} setting(s)`);
    obState.images = parsed.images;
    obState.settings = parsed.settings;

    renderScreen2();
    document.getElementById("screen2").style.display = "flex";
  } catch (err) {
    obLog(`ERROR: ${err.message}`);
  }
});

function renderScreen2() {
  const imagesDiv = document.getElementById("images-editor");
  imagesDiv.innerHTML = "<h4>Images (per-service source)</h4>";
  for (const img of obState.images) {
    const row = document.createElement("div");
    row.className = "image-row";
    row.innerHTML = `
      <span>${img.service_name} (${img.image_ref})</span>
      <select data-image-id="${img.id}">
        <option value="hosted_registry" selected>hosted_registry (push creds)</option>
        <option value="external_url">external_url</option>
      </select>
    `;
    imagesDiv.appendChild(row);
  }

  const settingsDiv = document.getElementById("settings-editor");
  settingsDiv.innerHTML = "<h4>Settings (env vars)</h4>";
  for (const s of obState.settings) {
    const row = document.createElement("div");
    row.className = "setting-row";
    row.innerHTML = `
      <span>${s.env_key}</span>
      <input placeholder="default value" data-env-key="${s.env_key}" value="${s.default_value || ""}" />
      <label><input type="checkbox" data-secret-key="${s.env_key}" ${s.is_secret ? "checked" : ""}/> secret</label>
      <label><input type="checkbox" data-fill-key="${s.env_key}" ${s.fill_at_install ? "checked" : ""}/> fill_at_install</label>
    `;
    settingsDiv.appendChild(row);
  }
}

document.getElementById("submit-btn").addEventListener("click", async () => {
  const { appId, versionId } = obState;
  try {
    for (const select of document.querySelectorAll("#images-editor select")) {
      const imageId = select.dataset.imageId;
      const source = select.value;
      if (source === "hosted_registry") {
        const creds = await apiFetch(
          `/apps/${appId}/versions/${versionId}/images/${imageId}/push-credentials`,
          { method: "POST" }
        );
        obLog(`Issued push credentials for image ${imageId}: docker push ${creds.registry_uri}/${creds.repository}`);
        // Simulate the ISV's real `docker push` + async ECR EventBridge webhook.
        const simRes = await fetch(`${CATALOG_ROOT}/dev/simulate-ecr-push/${imageId}`, { method: "POST" });
        const sim = await simRes.json();
        obLog(`(simulated) push completed -> scan_status=${sim.scan_status}`);
      } else {
        await apiFetch(`/apps/${appId}/versions/${versionId}/images/${imageId}`, {
          method: "PUT",
          body: JSON.stringify({ source: "external_url", registry_or_url: "" }),
        });
      }
    }

    const settingsPayload = obState.settings.map((s) => ({
      env_key: s.env_key,
      default_value: document.querySelector(`[data-env-key="${s.env_key}"]`).value || null,
      is_secret: document.querySelector(`[data-secret-key="${s.env_key}"]`).checked,
      fill_at_install: document.querySelector(`[data-fill-key="${s.env_key}"]`).checked,
    }));
    await apiFetch(`/apps/${appId}/versions/${versionId}/settings`, {
      method: "PUT",
      body: JSON.stringify(settingsPayload),
    });
    obLog("Saved settings.");

    const hw = JSON.parse(document.getElementById("hw-reqs").value);
    await apiFetch(`/apps/${appId}/versions/${versionId}`, {
      method: "PUT",
      body: JSON.stringify({ hardware_requirements: hw }),
    });
    await apiFetch(`/apps/${appId}/versions/${versionId}/evidence`, {
      method: "POST",
      body: JSON.stringify({ test_evidence_url: document.getElementById("evidence-url").value }),
    });
    obLog("Saved hardware requirements + evidence.");

    const submitted = await apiFetch(`/apps/${appId}/versions/${versionId}/submit`, { method: "POST" });
    obLog(`Submitted! status=${submitted.status}. Switch to the Admin Review tab to approve it.`);
  } catch (err) {
    obLog(`ERROR: ${err.message}`);
  }
});
