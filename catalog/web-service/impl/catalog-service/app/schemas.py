# SPDX-FileCopyrightText: (C) 2026 Intel Corporation
# SPDX-License-Identifier: Apache-2.0
"""Pydantic request/response schemas — mirrors openapi/catalog-service.openapi.yaml."""
from datetime import datetime

from pydantic import BaseModel, ConfigDict, Field


# ---------------------------------------------------------------- auth --
class UserProfile(BaseModel):
    user_id: str
    email: str
    name: str | None = None
    roles: list[str]
    org_id: str
    org_type: str


# ----------------------------------------------------------------- isv --
class AppCreateRequest(BaseModel):
    name: str
    category: str
    description: str = ""
    tags: list[str] = Field(default_factory=list)


class AppUpdateRequest(BaseModel):
    name: str | None = None
    category: str | None = None
    description: str | None = None
    tags: list[str] | None = None
    icon_url: str | None = None
    license_id: str | None = None


class AppOut(BaseModel):
    id: str
    isv_org_id: str
    name: str
    category: str
    description: str
    tags: list[str]
    icon_url: str | None
    license_id: str | None
    status: str
    created_at: datetime
    updated_at: datetime

    model_config = ConfigDict(from_attributes=True)


class AppVersionCreateRequest(BaseModel):
    deployment_file_url: str | None = None
    deployment_kind: str = "compose"
    version: str = "0.1.0"
    base_version_id: str | None = None


class AppVersionOut(BaseModel):
    id: str
    app_id: str
    version: str
    deployment_file_url: str | None
    deployment_kind: str
    status: str
    hardware_requirements: dict
    test_evidence_url: str | None
    submitted_at: datetime | None
    reviewed_at: datetime | None
    reviewer_id: str | None
    review_comments: str | None

    model_config = ConfigDict(from_attributes=True)


class AppVersionImageOut(BaseModel):
    id: str
    app_version_id: str
    service_name: str
    image_ref: str
    source: str
    registry_or_url: str | None
    requires_pull_secret: bool
    scan_status: str

    model_config = ConfigDict(from_attributes=True)


class AppVersionImageUpdateRequest(BaseModel):
    source: str
    registry_or_url: str | None = None


class EcrPushCredentials(BaseModel):
    registry_uri: str
    repository: str
    auth_token: str
    expires_at: datetime


class AppVersionSettingUpsert(BaseModel):
    env_key: str
    default_value: str | None = None
    is_secret: bool = False
    fill_at_install: bool = False
    description: str | None = None


class AppVersionSettingOut(AppVersionSettingUpsert):
    id: str
    app_version_id: str

    model_config = ConfigDict(from_attributes=True)


class EvidenceRequest(BaseModel):
    test_evidence_url: str


class HardwareRequirementsRequest(BaseModel):
    hardware_requirements: dict


class LicenseCreateRequest(BaseModel):
    title: str
    text_url: str
    version: str


class LicenseOut(LicenseCreateRequest):
    id: str

    model_config = ConfigDict(from_attributes=True)


class LicenseAcceptanceOut(BaseModel):
    id: str
    user_id: str | None
    org_id: str | None
    app_version_id: str
    license_id: str | None
    accepted_at: datetime
    ip_address: str | None

    model_config = ConfigDict(from_attributes=True)


class ParsedDeployment(BaseModel):
    images: list[AppVersionImageOut]
    settings: list[AppVersionSettingOut]
    referenced_files: list[dict] = Field(default_factory=list)


class SubmitError(BaseModel):
    code: str
    message: str
    fields: list[dict] = Field(default_factory=list)


# --------------------------------------------------------------- admin --
class ReviewActionRequest(BaseModel):
    comments: str | None = None


class InvitationCreateRequest(BaseModel):
    email: str
    role: str
    org_id: str


class InvitationOut(BaseModel):
    id: str
    email: str
    role: str
    org_id: str
    status: str
    expires_at: datetime

    model_config = ConfigDict(from_attributes=True)


# ------------------------------------------------------------- catalog --
class AppSummary(BaseModel):
    id: str
    name: str
    category: str
    icon_url: str | None
    isv_org_name: str
    short_description: str


class AppDetail(AppOut):
    versions: list[AppVersionOut]
    isv_org_name: str


class SystemProfile(BaseModel):
    os: str
    edge_pack_version: str | None = None
    cpu: str | None = None
    gpu: str | None = None
    npu: bool = False
    memory_gb: int | None = None


class SettingOverride(BaseModel):
    env_key: str
    value: str


class InstallRequest(BaseModel):
    app_version_id: str
    system_profile: SystemProfile
    settings_overrides: list[SettingOverride] = Field(default_factory=list)


class InstallTokenResponse(BaseModel):
    install_token: str
    expires_in: int


class LicenseAcceptanceRequired(BaseModel):
    requires_acceptance: bool = True
    license_id: str | None
    license_text_url: str | None


class InstallPlanImage(BaseModel):
    service_name: str
    image_ref: str
    pull_token: str | None = None


class InstallPlanSetting(BaseModel):
    env_key: str
    value: str | None = None


class InstallPlan(BaseModel):
    app_version_id: str
    compose_url: str | None
    images: list[InstallPlanImage]
    settings: list[InstallPlanSetting]
    license_terms_url: str | None
    compatibility_rules: dict
    issued_at: datetime


class TelemetryRequest(BaseModel):
    action: str
    result: str
