# SPDX-FileCopyrightText: (C) 2026 Intel Corporation
# SPDX-License-Identifier: Apache-2.0
"""
SQLAlchemy models mirroring edge-ai-catalog-design.md §5 data model.

Deliberately mocked/simplified pieces for the local reference implementation
(clearly not production infra):
  - install_tokens: in production this is a short-TTL row in DynamoDB/Redis
    (design doc §9.1); here it's a plain table with an `expires_at`/
    `consumed_at` column, same semantics (single-use, short-lived).
  - No `devices`/`installations` fleet tables — matches the explicit
    "no fleet management" design decision (§5 note).
"""
import uuid
from datetime import datetime, timedelta, timezone

from sqlalchemy import (
    JSON,
    Boolean,
    DateTime,
    ForeignKey,
    Integer,
    String,
    Text,
)
from sqlalchemy.orm import Mapped, mapped_column, relationship

from .db import Base


def _uuid() -> str:
    return str(uuid.uuid4())


def _now() -> datetime:
    return datetime.now(timezone.utc)


class Organization(Base):
    __tablename__ = "organizations"
    id: Mapped[str] = mapped_column(String, primary_key=True, default=_uuid)
    name: Mapped[str] = mapped_column(String, nullable=False)
    org_type: Mapped[str] = mapped_column(String, nullable=False)  # OXM|ISV|SI|INTEL


class User(Base):
    __tablename__ = "users"
    id: Mapped[str] = mapped_column(String, primary_key=True, default=_uuid)
    sso_subject_id: Mapped[str] = mapped_column(String, nullable=True)
    email: Mapped[str] = mapped_column(String, nullable=False, unique=True)
    name: Mapped[str] = mapped_column(String, nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=_now)


class UserRole(Base):
    __tablename__ = "user_roles"
    id: Mapped[str] = mapped_column(String, primary_key=True, default=_uuid)
    user_id: Mapped[str] = mapped_column(String, ForeignKey("users.id"), nullable=False)
    role: Mapped[str] = mapped_column(String, nullable=False)  # OXM|ISV|SI|ADMIN
    org_id: Mapped[str] = mapped_column(String, ForeignKey("organizations.id"), nullable=False)


class Invitation(Base):
    __tablename__ = "invitations"
    id: Mapped[str] = mapped_column(String, primary_key=True, default=_uuid)
    email: Mapped[str] = mapped_column(String, nullable=False)
    role: Mapped[str] = mapped_column(String, nullable=False)
    org_id: Mapped[str] = mapped_column(String, ForeignKey("organizations.id"), nullable=False)
    invited_by: Mapped[str] = mapped_column(String, nullable=True)
    status: Mapped[str] = mapped_column(String, default="pending")  # pending|accepted|expired
    expires_at: Mapped[datetime] = mapped_column(
        DateTime, default=lambda: _now() + timedelta(days=7)
    )


class License(Base):
    __tablename__ = "licenses"
    id: Mapped[str] = mapped_column(String, primary_key=True, default=_uuid)
    title: Mapped[str] = mapped_column(String, nullable=False)
    text_url: Mapped[str] = mapped_column(String, nullable=False)
    version: Mapped[str] = mapped_column(String, nullable=False)


class App(Base):
    __tablename__ = "apps"
    id: Mapped[str] = mapped_column(String, primary_key=True, default=_uuid)
    isv_org_id: Mapped[str] = mapped_column(String, ForeignKey("organizations.id"), nullable=False)
    name: Mapped[str] = mapped_column(String, nullable=False)
    category: Mapped[str] = mapped_column(String, nullable=False)
    description: Mapped[str] = mapped_column(Text, default="")
    tags: Mapped[list] = mapped_column(JSON, default=list)
    icon_url: Mapped[str] = mapped_column(String, nullable=True)
    license_id: Mapped[str] = mapped_column(String, ForeignKey("licenses.id"), nullable=True)
    status: Mapped[str] = mapped_column(String, default="draft")
    created_at: Mapped[datetime] = mapped_column(DateTime, default=_now)
    updated_at: Mapped[datetime] = mapped_column(DateTime, default=_now, onupdate=_now)

    versions = relationship("AppVersion", back_populates="app", cascade="all, delete-orphan")


class AppVersion(Base):
    __tablename__ = "app_versions"
    id: Mapped[str] = mapped_column(String, primary_key=True, default=_uuid)
    app_id: Mapped[str] = mapped_column(String, ForeignKey("apps.id"), nullable=False)
    version: Mapped[str] = mapped_column(String, default="0.1.0")
    deployment_file_url: Mapped[str] = mapped_column(String, nullable=True)
    deployment_kind: Mapped[str] = mapped_column(String, default="compose")
    status: Mapped[str] = mapped_column(String, default="draft")
    hardware_requirements: Mapped[dict] = mapped_column(JSON, default=dict)
    test_evidence_url: Mapped[str] = mapped_column(String, nullable=True)
    submitted_at: Mapped[datetime] = mapped_column(DateTime, nullable=True)
    reviewed_at: Mapped[datetime] = mapped_column(DateTime, nullable=True)
    reviewer_id: Mapped[str] = mapped_column(String, nullable=True)
    review_comments: Mapped[str] = mapped_column(Text, nullable=True)

    app = relationship("App", back_populates="versions")
    images = relationship(
        "AppVersionImage", back_populates="app_version", cascade="all, delete-orphan"
    )
    settings = relationship(
        "AppVersionSetting", back_populates="app_version", cascade="all, delete-orphan"
    )


class AppVersionImage(Base):
    __tablename__ = "app_version_images"
    id: Mapped[str] = mapped_column(String, primary_key=True, default=_uuid)
    app_version_id: Mapped[str] = mapped_column(
        String, ForeignKey("app_versions.id"), nullable=False
    )
    service_name: Mapped[str] = mapped_column(String, nullable=False)
    image_ref: Mapped[str] = mapped_column(String, nullable=False)
    source: Mapped[str] = mapped_column(String, default="external_url")
    registry_or_url: Mapped[str] = mapped_column(String, nullable=True)
    requires_pull_secret: Mapped[bool] = mapped_column(Boolean, default=False)
    scan_status: Mapped[str] = mapped_column(String, default="not_applicable")

    app_version = relationship("AppVersion", back_populates="images")


class AppVersionSetting(Base):
    __tablename__ = "app_version_settings"
    id: Mapped[str] = mapped_column(String, primary_key=True, default=_uuid)
    app_version_id: Mapped[str] = mapped_column(
        String, ForeignKey("app_versions.id"), nullable=False
    )
    env_key: Mapped[str] = mapped_column(String, nullable=False)
    default_value: Mapped[str] = mapped_column(String, nullable=True)
    is_secret: Mapped[bool] = mapped_column(Boolean, default=False)
    fill_at_install: Mapped[bool] = mapped_column(Boolean, default=False)
    description: Mapped[str] = mapped_column(String, nullable=True)

    app_version = relationship("AppVersion", back_populates="settings")


class LicenseAcceptance(Base):
    __tablename__ = "license_acceptances"
    id: Mapped[str] = mapped_column(String, primary_key=True, default=_uuid)
    user_id: Mapped[str] = mapped_column(String, nullable=True)
    org_id: Mapped[str] = mapped_column(String, nullable=True)
    app_version_id: Mapped[str] = mapped_column(
        String, ForeignKey("app_versions.id"), nullable=False
    )
    license_id: Mapped[str] = mapped_column(String, nullable=True)
    accepted_at: Mapped[datetime] = mapped_column(DateTime, default=_now)
    ip_address: Mapped[str] = mapped_column(String, nullable=True)


class ReviewEvent(Base):
    __tablename__ = "review_events"
    id: Mapped[str] = mapped_column(String, primary_key=True, default=_uuid)
    app_version_id: Mapped[str] = mapped_column(
        String, ForeignKey("app_versions.id"), nullable=False
    )
    actor_id: Mapped[str] = mapped_column(String, nullable=True)
    action: Mapped[str] = mapped_column(String, nullable=False)
    comments: Mapped[str] = mapped_column(Text, nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=_now)


class InstallTelemetryEvent(Base):
    __tablename__ = "install_telemetry_events"
    id: Mapped[str] = mapped_column(String, primary_key=True, default=_uuid)
    app_version_id: Mapped[str] = mapped_column(String, nullable=False)
    org_id: Mapped[str] = mapped_column(String, nullable=True)
    action: Mapped[str] = mapped_column(String, nullable=False)  # install|upgrade|uninstall
    result: Mapped[str] = mapped_column(String, nullable=False)  # success|failure
    occurred_at: Mapped[datetime] = mapped_column(DateTime, default=_now)


class AuditLog(Base):
    __tablename__ = "audit_logs"
    id: Mapped[str] = mapped_column(String, primary_key=True, default=_uuid)
    actor_id: Mapped[str] = mapped_column(String, nullable=True)
    action: Mapped[str] = mapped_column(String, nullable=False)
    entity_type: Mapped[str] = mapped_column(String, nullable=False)
    entity_id: Mapped[str] = mapped_column(String, nullable=False)
    event_metadata: Mapped[dict] = mapped_column(JSON, default=dict)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=_now)


class InstallToken(Base):
    """
    Mocked stand-in for the DynamoDB/Redis TTL token store described in
    edge-ai-catalog-design.md §4.5 / §9.1. Same semantics: opaque token,
    short expiry, single-use (consumed_at set on redeem).
    """

    __tablename__ = "install_tokens"
    token: Mapped[str] = mapped_column(String, primary_key=True)
    app_version_id: Mapped[str] = mapped_column(
        String, ForeignKey("app_versions.id"), nullable=False
    )
    org_id: Mapped[str] = mapped_column(String, nullable=True)
    user_id: Mapped[str] = mapped_column(String, nullable=True)
    system_profile: Mapped[dict] = mapped_column(JSON, default=dict)
    settings_overrides: Mapped[list] = mapped_column(JSON, default=list)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=_now)
    expires_at: Mapped[datetime] = mapped_column(DateTime, nullable=False)
    consumed_at: Mapped[datetime] = mapped_column(DateTime, nullable=True)
