# SPDX-FileCopyrightText: (C) 2026 Intel Corporation
# SPDX-License-Identifier: Apache-2.0
"""ISV onboarding endpoints — flow B1/B2/B3. See technical-flows.md."""
from datetime import datetime, timezone

from fastapi import APIRouter, Depends, HTTPException, Request
from sqlalchemy.orm import Session

from .. import compose_parser, models, registry, schemas, storage
from ..auth import CurrentUser, require_role
from ..db import get_db

router = APIRouter(tags=["isv"])


def _base_url(request: Request) -> str:
    return str(request.base_url).rstrip("/")


def _get_app_owned(db: Session, app_id: str, user: CurrentUser) -> models.App:
    app = db.query(models.App).filter_by(id=app_id).first()
    if not app:
        raise HTTPException(status_code=404, detail={"code": "not_found", "message": "App not found"})
    if app.isv_org_id != user.org_id:
        raise HTTPException(status_code=403, detail={"code": "forbidden", "message": "Not your app"})
    return app


def _get_version_owned(db: Session, app_id: str, version_id: str, user: CurrentUser) -> models.AppVersion:
    _get_app_owned(db, app_id, user)
    version = db.query(models.AppVersion).filter_by(id=version_id, app_id=app_id).first()
    if not version:
        raise HTTPException(status_code=404, detail={"code": "not_found", "message": "Version not found"})
    return version


# ------------------------------------------------------------- Screen 1 --
@router.post("/apps", response_model=schemas.AppOut, status_code=201)
def create_app(
    body: schemas.AppCreateRequest,
    db: Session = Depends(get_db),
    user: CurrentUser = Depends(require_role("ISV")),
):
    app = models.App(
        isv_org_id=user.org_id,
        name=body.name,
        category=body.category,
        description=body.description,
        tags=body.tags,
        status="draft",
    )
    db.add(app)
    db.commit()
    db.refresh(app)
    return app


@router.put("/apps/{app_id}", response_model=schemas.AppOut)
def update_app(
    app_id: str,
    body: schemas.AppUpdateRequest,
    db: Session = Depends(get_db),
    user: CurrentUser = Depends(require_role("ISV")),
):
    app = _get_app_owned(db, app_id, user)
    for field, value in body.model_dump(exclude_unset=True).items():
        setattr(app, field, value)
    app.updated_at = datetime.now(timezone.utc)
    db.commit()
    db.refresh(app)
    return app


@router.delete("/apps/{app_id}", status_code=204)
def delist_app(
    app_id: str,
    db: Session = Depends(get_db),
    user: CurrentUser = Depends(require_role("ISV")),
):
    app = _get_app_owned(db, app_id, user)
    if app.status != "listed":
        raise HTTPException(
            status_code=409,
            detail={"code": "not_delistable", "message": "App must be 'listed' to delist"},
        )
    app.status = "removed"
    db.commit()


@router.post("/apps/{app_id}/assets/icon-upload-url")
def icon_upload_url(
    app_id: str,
    request: Request,
    db: Session = Depends(get_db),
    user: CurrentUser = Depends(require_role("ISV")),
):
    _get_app_owned(db, app_id, user)
    return storage.presign_upload(f"icons/{app_id}", _base_url(request))


@router.post("/licenses", response_model=schemas.LicenseOut, status_code=201)
def create_license(
    body: schemas.LicenseCreateRequest,
    db: Session = Depends(get_db),
    user: CurrentUser = Depends(require_role("ISV")),
):
    lic = models.License(**body.model_dump())
    db.add(lic)
    db.commit()
    db.refresh(lic)
    return lic


@router.post("/apps/{app_id}/versions", response_model=schemas.AppVersionOut, status_code=201)
def create_version(
    app_id: str,
    body: schemas.AppVersionCreateRequest,
    db: Session = Depends(get_db),
    user: CurrentUser = Depends(require_role("ISV")),
):
    _get_app_owned(db, app_id, user)
    version = models.AppVersion(
        app_id=app_id,
        deployment_file_url=body.deployment_file_url,
        deployment_kind=body.deployment_kind,
        version=body.version,
        status="draft",
    )
    db.add(version)

    if body.base_version_id:
        base = db.query(models.AppVersion).filter_by(id=body.base_version_id, app_id=app_id).first()
        if base:
            version.hardware_requirements = dict(base.hardware_requirements or {})
            for img in base.images:
                db.add(
                    models.AppVersionImage(
                        app_version_id=version.id,
                        service_name=img.service_name,
                        image_ref=img.image_ref,
                        source=img.source,
                        registry_or_url=img.registry_or_url,
                        requires_pull_secret=img.requires_pull_secret,
                        scan_status=img.scan_status,
                    )
                )
            for st in base.settings:
                db.add(
                    models.AppVersionSetting(
                        app_version_id=version.id,
                        env_key=st.env_key,
                        default_value=st.default_value,
                        is_secret=st.is_secret,
                        fill_at_install=st.fill_at_install,
                        description=st.description,
                    )
                )
    db.commit()
    db.refresh(version)
    return version


# ------------------------------------------------------------- Screen 2 --
@router.post(
    "/apps/{app_id}/versions/{version_id}/parse-deployment",
    response_model=schemas.ParsedDeployment,
)
def parse_deployment(
    app_id: str,
    version_id: str,
    request: Request,
    db: Session = Depends(get_db),
    user: CurrentUser = Depends(require_role("ISV")),
):
    version = _get_version_owned(db, app_id, version_id, user)
    if not version.deployment_file_url:
        raise HTTPException(
            status_code=422,
            detail={"code": "no_deployment_file", "message": "Upload a deployment file first"},
        )
    key = storage.key_from_url(version.deployment_file_url)
    if not key or not storage.exists(key):
        raise HTTPException(
            status_code=422,
            detail={"code": "file_not_uploaded", "message": "Deployment file has not been uploaded yet"},
        )
    try:
        parsed = compose_parser.parse_compose(storage.read_bytes(key))
    except ValueError as exc:
        raise HTTPException(status_code=422, detail={"code": "parse_failed", "message": str(exc)}) from exc

    for img in parsed["images"]:
        db.add(
            models.AppVersionImage(
                app_version_id=version.id,
                service_name=img["service_name"],
                image_ref=img["image_ref"],
                source="external_url",
                registry_or_url=img["image_ref"],
                scan_status="not_applicable",
            )
        )
    for env_key, is_secret_guess in parsed["settings"].items():
        db.add(
            models.AppVersionSetting(
                app_version_id=version.id,
                env_key=env_key,
                is_secret=is_secret_guess,
                fill_at_install=is_secret_guess,
            )
        )
    db.commit()
    db.refresh(version)

    referenced_files = [
        {
            "path_in_compose": p,
            "upload_url": storage.presign_upload(f"files/{version.id}", _base_url(request))["upload_url"],
        }
        for p in parsed["referenced_files"]
    ]
    return schemas.ParsedDeployment(
        images=version.images, settings=version.settings, referenced_files=referenced_files
    )


@router.put("/apps/{app_id}/versions/{version_id}/images/{image_id}", response_model=schemas.AppVersionImageOut)
def set_image_source(
    app_id: str,
    version_id: str,
    image_id: str,
    body: schemas.AppVersionImageUpdateRequest,
    db: Session = Depends(get_db),
    user: CurrentUser = Depends(require_role("ISV")),
):
    _get_version_owned(db, app_id, version_id, user)
    image = db.query(models.AppVersionImage).filter_by(id=image_id, app_version_id=version_id).first()
    if not image:
        raise HTTPException(status_code=404, detail={"code": "not_found", "message": "Image not found"})
    image.source = body.source
    image.registry_or_url = body.registry_or_url
    image.scan_status = "pending" if body.source == "hosted_registry" else "not_applicable"
    db.commit()
    db.refresh(image)
    return image


@router.post(
    "/apps/{app_id}/versions/{version_id}/images/{image_id}/push-credentials",
    response_model=schemas.EcrPushCredentials,
)
def push_credentials(
    app_id: str,
    version_id: str,
    image_id: str,
    db: Session = Depends(get_db),
    user: CurrentUser = Depends(require_role("ISV")),
):
    app = _get_app_owned(db, app_id, user)
    image = db.query(models.AppVersionImage).filter_by(id=image_id, app_version_id=version_id).first()
    if not image:
        raise HTTPException(status_code=404, detail={"code": "not_found", "message": "Image not found"})
    org = db.query(models.Organization).filter_by(id=app.isv_org_id).first()
    slug = org.name.lower().replace(" ", "-") if org else "isv"
    creds = registry.issue_push_credentials(slug, app_id, image.service_name)
    image.source = "hosted_registry"
    image.registry_or_url = f"{creds['registry_uri']}/{creds['repository']}"
    image.scan_status = "pending"
    db.commit()
    return creds


@router.put(
    "/apps/{app_id}/versions/{version_id}/settings",
    response_model=list[schemas.AppVersionSettingOut],
)
def upsert_settings(
    app_id: str,
    version_id: str,
    body: list[schemas.AppVersionSettingUpsert],
    db: Session = Depends(get_db),
    user: CurrentUser = Depends(require_role("ISV")),
):
    version = _get_version_owned(db, app_id, version_id, user)
    existing = {s.env_key: s for s in version.settings}
    for item in body:
        if item.env_key in existing:
            row = existing[item.env_key]
            for f, v in item.model_dump().items():
                setattr(row, f, v)
        else:
            db.add(models.AppVersionSetting(app_version_id=version_id, **item.model_dump()))
    db.commit()
    db.refresh(version)
    return version.settings


@router.post("/apps/{app_id}/versions/{version_id}/evidence")
def add_evidence(
    app_id: str,
    version_id: str,
    body: schemas.EvidenceRequest,
    db: Session = Depends(get_db),
    user: CurrentUser = Depends(require_role("ISV")),
):
    version = _get_version_owned(db, app_id, version_id, user)
    version.test_evidence_url = body.test_evidence_url
    db.commit()
    return {"ok": True}


@router.put("/apps/{app_id}/versions/{version_id}", response_model=schemas.AppVersionOut)
def update_version(
    app_id: str,
    version_id: str,
    body: schemas.HardwareRequirementsRequest,
    db: Session = Depends(get_db),
    user: CurrentUser = Depends(require_role("ISV")),
):
    version = _get_version_owned(db, app_id, version_id, user)
    version.hardware_requirements = body.hardware_requirements
    db.commit()
    db.refresh(version)
    return version


@router.post("/apps/{app_id}/versions/{version_id}/submit")
def submit_version(
    app_id: str,
    version_id: str,
    db: Session = Depends(get_db),
    user: CurrentUser = Depends(require_role("ISV")),
):
    app = _get_app_owned(db, app_id, user)
    version = _get_version_owned(db, app_id, version_id, user)

    missing = []
    if not app.license_id:
        missing.append({"field": "license_id", "reason": "no license selected"})
    if not version.images:
        missing.append({"field": "images", "reason": "at least one image reference required"})
    if not version.test_evidence_url:
        missing.append({"field": "test_evidence_url", "reason": "tested-on evidence required"})
    if missing:
        raise HTTPException(
            status_code=400,
            detail={"code": "validation_failed", "message": "Missing required fields", "fields": missing},
        )

    pending_scans = [i for i in version.images if i.source == "hosted_registry" and i.scan_status == "pending"]
    if pending_scans:
        raise HTTPException(
            status_code=409,
            detail={
                "code": "scan_incomplete",
                "message": "One or more hosted-registry images have not completed vulnerability scanning",
            },
        )

    version.status = "pending_review"
    version.submitted_at = datetime.now(timezone.utc)
    if app.status == "draft":
        app.status = "pending_review"
    db.commit()
    return {"status": "pending_review"}


@router.get("/isv/dashboard")
def isv_dashboard(
    db: Session = Depends(get_db),
    user: CurrentUser = Depends(require_role("ISV")),
):
    apps = db.query(models.App).filter_by(isv_org_id=user.org_id).all()
    counts = {"listed": 0, "pending_review": 0, "downloads": 0, "installs": 0}
    for a in apps:
        if a.status == "listed":
            counts["listed"] += 1
        if a.status == "pending_review":
            counts["pending_review"] += 1
    installs = (
        db.query(models.InstallTelemetryEvent)
        .filter(models.InstallTelemetryEvent.action == "install", models.InstallTelemetryEvent.result == "success")
        .all()
    )
    version_app_ids = {v.id: v.app_id for a in apps for v in a.versions}
    counts["installs"] = sum(1 for e in installs if e.app_version_id in version_app_ids)
    return {
        "apps": [
            {**schemas.AppOut.model_validate(a).model_dump(), "versions": [
                schemas.AppVersionOut.model_validate(v).model_dump() for v in a.versions
            ]}
            for a in apps
        ],
        "counts": counts,
    }
