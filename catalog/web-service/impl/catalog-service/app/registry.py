# SPDX-FileCopyrightText: (C) 2026 Intel Corporation
# SPDX-License-Identifier: Apache-2.0
"""
MOCKED ECR registry + vulnerability scanner for the local reference
implementation.

Production (§4.3, §9.1, §9.3, flow B1 step 5): a real per-image ECR repo is
provisioned once, short-lived push credentials are issued via
`sts.get_authorization_token` / `ecr.get_authorization_token`, the ISV does
a real `docker push`, an ECR EventBridge rule fires on push completion and
invokes a webhook, which queues an async Trivy/ECR-native vulnerability
scan (SQS -> Fargate worker).

None of that infra exists here. Instead:
  - `issue_push_credentials` returns a fake `registry_uri`/`repository`/
    `auth_token` (clearly fake, not usable against real ECR).
  - `simulate_push_webhook` stands in for the EventBridge->webhook call —
    a real system would receive this asynchronously from AWS; the
    `/dev/simulate-ecr-push` endpoint below lets a caller (or a test) fire
    it manually to model "the ISV finished a real docker push".
  - `simulate_scan` stands in for the async Trivy/Fargate worker — runs
    synchronously and deterministically (marks external_url images
    not_applicable, hosted_registry images as passed) rather than actually
    scanning bytes, since no real image bytes exist in this reference
    implementation.
"""
import base64
import uuid
from datetime import datetime, timedelta, timezone


def issue_push_credentials(isv_org_slug: str, app_id: str, service_name: str) -> dict:
    repository = f"{isv_org_slug}/{app_id}/{service_name}"
    fake_token = base64.b64encode(f"AWS:fake-ecr-token-{uuid.uuid4()}".encode()).decode()
    return {
        "registry_uri": "mock-catalog-registry.local",
        "repository": repository,
        "auth_token": fake_token,
        "expires_at": datetime.now(timezone.utc) + timedelta(hours=12),
    }


def simulate_scan(source: str) -> str:
    """Returns the scan_status that would eventually land after an async scan."""
    if source == "external_url":
        return "not_applicable"
    return "passed"
