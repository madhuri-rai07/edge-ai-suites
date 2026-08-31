# SPDX-FileCopyrightText: (C) 2026 Intel Corporation
# SPDX-License-Identifier: Apache-2.0
"""
End-to-end pytest covering flows B1 (onboarding), C1 (review), D1
(discover), D2 (token-based install) against the in-process FastAPI app —
mirrors the manual script used to validate the implementation live.
"""
ISV_H = {"X-Debug-User-Email": "isv1@example-vendor.com", "X-Debug-Role": "ISV"}
ADMIN_H = {"X-Debug-User-Email": "admin1@intel.com", "X-Debug-Role": "ADMIN"}
SI_H = {"X-Debug-User-Email": "si1@example-integrator.com", "X-Debug-Role": "SI"}

COMPOSE_YAML = b"""
services:
  ovms-service:
    image: openvino/model_server:2026.1
  traffic-agent:
    image: traffic-agent:1.0.0
    environment:
      HF_TOKEN: ""
      LOG_LEVEL: info
    volumes:
      - ./configs/agent.yaml:/app/config.yaml
"""


def _seed(client):
    r = client.post("/dev/seed")
    assert r.status_code == 200, r.text


def test_full_b1_c1_d1_d2_flow(client):
    _seed(client)

    lic = client.post(
        "/api/v1/licenses",
        json={"title": "Standard EULA", "text_url": "https://example.com/eula", "version": "1.0"},
        headers=ISV_H,
    )
    assert lic.status_code == 201
    license_id = lic.json()["id"]

    app_resp = client.post(
        "/api/v1/apps",
        json={"name": "Traffic Agent", "category": "Cities & Infrastructure", "description": "d", "tags": []},
        headers=ISV_H,
    )
    assert app_resp.status_code == 201
    app_id = app_resp.json()["id"]
    assert client.put(f"/api/v1/apps/{app_id}", json={"license_id": license_id}, headers=ISV_H).status_code == 200

    upload = client.post(f"/api/v1/apps/{app_id}/assets/icon-upload-url", headers=ISV_H).json()
    put_resp = client.put(upload["upload_url"], content=COMPOSE_YAML)
    assert put_resp.status_code == 200

    version_resp = client.post(
        f"/api/v1/apps/{app_id}/versions",
        json={"deployment_kind": "compose", "version": "1.0.0", "deployment_file_url": upload["upload_url"]},
        headers=ISV_H,
    )
    assert version_resp.status_code == 201
    version_id = version_resp.json()["id"]

    parsed = client.post(f"/api/v1/apps/{app_id}/versions/{version_id}/parse-deployment", headers=ISV_H)
    assert parsed.status_code == 200
    images = parsed.json()["images"]
    traffic_img = next(i for i in images if i["service_name"] == "traffic-agent")
    ovms_img = next(i for i in images if i["service_name"] == "ovms-service")

    creds = client.post(
        f"/api/v1/apps/{app_id}/versions/{version_id}/images/{traffic_img['id']}/push-credentials",
        headers=ISV_H,
    )
    assert creds.status_code == 200

    assert (
        client.put(
            f"/api/v1/apps/{app_id}/versions/{version_id}/images/{ovms_img['id']}",
            json={"source": "external_url", "registry_or_url": "openvino/model_server:2026.1"},
            headers=ISV_H,
        ).status_code
        == 200
    )

    assert (
        client.put(
            f"/api/v1/apps/{app_id}/versions/{version_id}/settings",
            json=[
                {"env_key": "HF_TOKEN", "is_secret": True, "fill_at_install": True},
                {"env_key": "LOG_LEVEL", "default_value": "info"},
            ],
            headers=ISV_H,
        ).status_code
        == 200
    )
    assert (
        client.put(
            f"/api/v1/apps/{app_id}/versions/{version_id}",
            json={"hardware_requirements": {"cpu": "x86_64", "gpu": "Intel Arc A770 or better"}},
            headers=ISV_H,
        ).status_code
        == 200
    )
    assert (
        client.post(
            f"/api/v1/apps/{app_id}/versions/{version_id}/evidence",
            json={"test_evidence_url": "https://example.com/evidence.pdf"},
            headers=ISV_H,
        ).status_code
        == 200
    )

    # Submit blocked on pending vuln scan for hosted_registry image.
    blocked = client.post(f"/api/v1/apps/{app_id}/versions/{version_id}/submit", headers=ISV_H)
    assert blocked.status_code == 409

    # Simulate ECR EventBridge webhook -> scan completed.
    assert client.post(f"/dev/simulate-ecr-push/{traffic_img['id']}").status_code == 200

    submitted = client.post(f"/api/v1/apps/{app_id}/versions/{version_id}/submit", headers=ISV_H)
    assert submitted.status_code == 200
    assert submitted.json()["status"] == "pending_review"

    # C1: admin review
    pending = client.get("/api/v1/admin/reviews", headers=ADMIN_H).json()
    assert any(v["id"] == version_id for v in pending)
    approved = client.post(f"/api/v1/admin/reviews/{version_id}/approve", headers=ADMIN_H)
    assert approved.status_code == 200
    assert approved.json()["status"] == "listed"

    # D1: discover
    catalog = client.get("/api/v1/catalog", headers=SI_H).json()
    assert catalog["total"] == 1
    assert catalog["items"][0]["name"] == "Traffic Agent"

    # D2: install gated on license acceptance
    profile = {"os": "Ubuntu 22.04", "cpu": "x86_64", "gpu": "Intel Arc A770", "npu": False, "memory_gb": 32}
    gated = client.post(
        "/api/v1/install", json={"app_version_id": version_id, "system_profile": profile}, headers=SI_H
    )
    assert gated.status_code == 428

    accepted = client.post(f"/api/v1/apps/{app_id}/versions/{version_id}/accept-license", headers=SI_H)
    assert accepted.status_code == 201

    install_resp = client.post(
        "/api/v1/install",
        json={
            "app_version_id": version_id,
            "system_profile": profile,
            "settings_overrides": [{"env_key": "HF_TOKEN", "value": "hf_fake_token_123"}],
        },
        headers=SI_H,
    )
    assert install_resp.status_code == 200
    token = install_resp.json()["install_token"]
    assert install_resp.json()["expires_in"] == 120

    # Device Agent's own outbound redeem call — no auth headers at all.
    plan_resp = client.get(f"/api/v1/install/redeem/{token}")
    assert plan_resp.status_code == 200
    plan = plan_resp.json()
    assert plan["app_version_id"] == version_id
    setting_values = {s["env_key"]: s["value"] for s in plan["settings"]}
    assert setting_values["HF_TOKEN"] == "hf_fake_token_123"
    assert setting_values["LOG_LEVEL"] == "info"
    image_pull_tokens = {i["service_name"]: i["pull_token"] for i in plan["images"]}
    assert image_pull_tokens["ovms-service"] is None
    assert image_pull_tokens["traffic-agent"] is not None

    # Replay is rejected (single-use).
    replay = client.get(f"/api/v1/install/redeem/{token}")
    assert replay.status_code == 410

    telemetry = client.post(f"/api/v1/install/{token}/telemetry", json={"action": "install", "result": "success"})
    assert telemetry.status_code == 202


def test_unknown_token_returns_404(client):
    _seed(client)
    r = client.get("/api/v1/install/redeem/does-not-exist")
    assert r.status_code == 404


def test_submit_requires_license_and_evidence(client):
    _seed(client)
    app_resp = client.post(
        "/api/v1/apps", json={"name": "No License App", "category": "Retail"}, headers=ISV_H
    )
    app_id = app_resp.json()["id"]
    version_resp = client.post(f"/api/v1/apps/{app_id}/versions", json={"version": "0.1.0"}, headers=ISV_H)
    version_id = version_resp.json()["id"]
    r = client.post(f"/api/v1/apps/{app_id}/versions/{version_id}/submit", headers=ISV_H)
    assert r.status_code == 400
    fields = {f["field"] for f in r.json()["detail"]["fields"]}
    assert "license_id" in fields
    assert "images" in fields
    assert "test_evidence_url" in fields
