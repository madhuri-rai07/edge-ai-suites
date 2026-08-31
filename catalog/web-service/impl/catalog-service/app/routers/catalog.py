# SPDX-FileCopyrightText: (C) 2026 Intel Corporation
# SPDX-License-Identifier: Apache-2.0
"""
Catalog discovery + install endpoints — flow D1/D2/D3/D4.

This is the router implementing the token-based install model (design doc
§4.5): POST /install issues an opaque, single-use, short-lived token;
GET /install/redeem/{token} is called by the Device Agent itself over its
own outbound connection (never the browser) and returns the real install
plan.
"""
import secrets
from datetime import datetime, timedelta, timezone

from fastapi import APIRouter, Depends, HTTPException, Request
from sqlalchemy.orm import Session

from .. import models, registry, schemas
from ..auth import CurrentUser, get_current_user
from ..db import get_db

router = APIRouter(tags=["catalog"])

INSTALL_TOKEN_TTL_SECONDS = 120


@router.get("/catalog")
def browse_catalog(
    category: str | None = None,
    search: str | None = None,
    isv: str | None = None,
    geo: str | None = None,
    page: int = 1,
    db: Session = Depends(get_db),
):
    q = db.query(models.App).filter(models.App.status == "listed")
    if category:
        q = q.filter(models.App.category == category)
    if search:
        q = q.filter(models.App.name.ilike(f"%{search}%"))
    if isv:
        q = q.filter(models.App.isv_org_id == isv)
    apps = q.all()
    items = []
    for a in apps:
        org = db.query(models.Organization).filter_by(id=a.isv_org_id).first()
        items.append(
            schemas.AppSummary(
                id=a.id,
                name=a.name,
                category=a.category,
                icon_url=a.icon_url,
                isv_org_name=org.name if org else "",
                short_description=(a.description or "")[:140],
            )
        )
    return {"items": items, "total": len(items), "page": page}


@router.get("/catalog/apps/{app_id}", response_model=schemas.AppDetail)
def app_detail(app_id: str, db: Session = Depends(get_db)):
    app = db.query(models.App).filter_by(id=app_id, status="listed").first()
    if not app:
        raise HTTPException(status_code=404, detail={"code": "not_found", "message": "App not found"})
    org = db.query(models.Organization).filter_by(id=app.isv_org_id).first()
    return schemas.AppDetail(
        **schemas.AppOut.model_validate(app).model_dump(),
        versions=[schemas.AppVersionOut.model_validate(v) for v in app.versions if v.status == "listed"],
        isv_org_name=org.name if org else "",
    )


@router.post("/apps/{app_id}/versions/{version_id}/accept-license", response_model=schemas.LicenseAcceptanceOut, status_code=201)
def accept_license(
    app_id: str,
    version_id: str,
    request: Request,
    db: Session = Depends(get_db),
    user: CurrentUser = Depends(get_current_user),
):
    version = db.query(models.AppVersion).filter_by(id=version_id, app_id=app_id).first()
    if not version:
        raise HTTPException(status_code=404, detail={"code": "not_found", "message": "Version not found"})
    app = db.query(models.App).filter_by(id=app_id).first()
    acceptance = models.LicenseAcceptance(
        user_id=user.user_id,
        org_id=user.org_id,
        app_version_id=version_id,
        license_id=app.license_id,
        ip_address=request.client.host if request.client else None,
    )
    db.add(acceptance)
    db.commit()
    db.refresh(acceptance)
    return acceptance


def _license_accepted(db: Session, user: CurrentUser, version_id: str) -> bool:
    return (
        db.query(models.LicenseAcceptance)
        .filter_by(app_version_id=version_id, org_id=user.org_id)
        .first()
        is not None
    )


@router.post("/install", response_model=schemas.InstallTokenResponse)
def request_install(
    body: schemas.InstallRequest,
    db: Session = Depends(get_db),
    user: CurrentUser = Depends(get_current_user),
):
    version = db.query(models.AppVersion).filter_by(id=body.app_version_id).first()
    if not version or version.status != "listed":
        raise HTTPException(
            status_code=409, detail={"code": "not_installable", "message": "App version is not listed"}
        )
    app = db.query(models.App).filter_by(id=version.app_id).first()
    if not _license_accepted(db, user, version.id):
        raise HTTPException(
            status_code=428,
            detail=schemas.LicenseAcceptanceRequired(
                license_id=app.license_id, license_text_url=None
            ).model_dump(),
        )

    token = secrets.token_urlsafe(32)
    expires_at = datetime.now(timezone.utc) + timedelta(seconds=INSTALL_TOKEN_TTL_SECONDS)
    db.add(
        models.InstallToken(
            token=token,
            app_version_id=version.id,
            org_id=user.org_id,
            user_id=user.user_id,
            system_profile=body.system_profile.model_dump(),
            settings_overrides=[s.model_dump() for s in body.settings_overrides],
            expires_at=expires_at,
        )
    )
    db.commit()
    return schemas.InstallTokenResponse(install_token=token, expires_in=INSTALL_TOKEN_TTL_SECONDS)


@router.get("/install/redeem/{install_token}", response_model=schemas.InstallPlan)
def redeem_install_token(install_token: str, db: Session = Depends(get_db)):
    """
    Called by the Device Agent itself, over its own outbound HTTPS
    connection — no browser involvement, no session cookie (security: []
    per the OpenAPI spec — the token itself is the credential).
    """
    row = db.query(models.InstallToken).filter_by(token=install_token).first()
    if not row:
        raise HTTPException(status_code=404, detail={"code": "not_found", "message": "Unknown token"})
    now = datetime.now(timezone.utc)
    expires_at = row.expires_at if row.expires_at.tzinfo else row.expires_at.replace(tzinfo=timezone.utc)
    if row.consumed_at is not None or now > expires_at:
        raise HTTPException(
            status_code=410, detail={"code": "token_expired_or_consumed", "message": "Token expired or already used"}
        )

    row.consumed_at = now
    version = db.query(models.AppVersion).filter_by(id=row.app_version_id).first()
    app = db.query(models.App).filter_by(id=version.app_id).first()

    overrides = {o["env_key"]: o["value"] for o in (row.settings_overrides or [])}
    settings_out = []
    for s in version.settings:
        value = overrides.get(s.env_key, s.default_value)
        settings_out.append(schemas.InstallPlanSetting(env_key=s.env_key, value=value))

    images_out = []
    for img in version.images:
        pull_token = None
        if img.source == "hosted_registry":
            creds = registry.issue_push_credentials("runtime-pull", app.id, img.service_name)
            pull_token = creds["auth_token"]
        images_out.append(
            schemas.InstallPlanImage(service_name=img.service_name, image_ref=img.image_ref, pull_token=pull_token)
        )

    db.commit()
    return schemas.InstallPlan(
        app_version_id=version.id,
        compose_url=version.deployment_file_url,
        images=images_out,
        settings=settings_out,
        license_terms_url=None,
        compatibility_rules=version.hardware_requirements or {},
        issued_at=now,
    )


@router.post("/install/{install_token_id}/telemetry", status_code=202)
def telemetry(
    install_token_id: str,
    body: schemas.TelemetryRequest,
    db: Session = Depends(get_db),
):
    row = db.query(models.InstallToken).filter_by(token=install_token_id).first()
    db.add(
        models.InstallTelemetryEvent(
            app_version_id=row.app_version_id if row else "unknown",
            org_id=row.org_id if row else None,
            action=body.action,
            result=body.result,
        )
    )
    db.commit()
    return {"accepted": True}
