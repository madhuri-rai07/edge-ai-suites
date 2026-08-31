# SPDX-FileCopyrightText: (C) 2026 Intel Corporation
# SPDX-License-Identifier: Apache-2.0
"""Intel Admin review/governance endpoints — flow C1/C2/C3."""
from datetime import datetime, timedelta, timezone

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session

from .. import models, schemas
from ..auth import CurrentUser, require_role
from ..db import get_db

router = APIRouter(prefix="/admin", tags=["admin"])


@router.get("/reviews", response_model=list[schemas.AppVersionOut])
def list_reviews(
    status: str | None = None,
    isv: str | None = None,
    db: Session = Depends(get_db),
    user: CurrentUser = Depends(require_role("ADMIN")),
):
    q = db.query(models.AppVersion)
    if status:
        q = q.filter(models.AppVersion.status == status)
    else:
        q = q.filter(models.AppVersion.status == "pending_review")
    if isv:
        q = q.join(models.App).filter(models.App.isv_org_id == isv)
    return q.all()


def _get_version(db: Session, version_id: str) -> models.AppVersion:
    version = db.query(models.AppVersion).filter_by(id=version_id).first()
    if not version:
        raise HTTPException(status_code=404, detail={"code": "not_found", "message": "Version not found"})
    return version


@router.post("/reviews/{version_id}/approve", response_model=schemas.AppVersionOut)
def approve(
    version_id: str,
    db: Session = Depends(get_db),
    user: CurrentUser = Depends(require_role("ADMIN")),
):
    version = _get_version(db, version_id)
    version.status = "listed"
    version.reviewed_at = datetime.now(timezone.utc)
    version.reviewer_id = user.user_id
    app = db.query(models.App).filter_by(id=version.app_id).first()
    app.status = "listed"
    db.add(models.ReviewEvent(app_version_id=version_id, actor_id=user.user_id, action="approve"))
    db.commit()
    db.refresh(version)
    return version


@router.post("/reviews/{version_id}/send-back", response_model=schemas.AppVersionOut)
def send_back(
    version_id: str,
    body: schemas.ReviewActionRequest,
    db: Session = Depends(get_db),
    user: CurrentUser = Depends(require_role("ADMIN")),
):
    version = _get_version(db, version_id)
    version.status = "sent_back"
    version.reviewed_at = datetime.now(timezone.utc)
    version.reviewer_id = user.user_id
    version.review_comments = body.comments
    db.add(
        models.ReviewEvent(
            app_version_id=version_id, actor_id=user.user_id, action="send_back", comments=body.comments
        )
    )
    db.commit()
    db.refresh(version)
    return version


@router.post("/reviews/{version_id}/reject", response_model=schemas.AppVersionOut)
def reject(
    version_id: str,
    body: schemas.ReviewActionRequest,
    db: Session = Depends(get_db),
    user: CurrentUser = Depends(require_role("ADMIN")),
):
    version = _get_version(db, version_id)
    version.status = "rejected"
    version.reviewed_at = datetime.now(timezone.utc)
    version.reviewer_id = user.user_id
    version.review_comments = body.comments
    db.add(
        models.ReviewEvent(
            app_version_id=version_id, actor_id=user.user_id, action="reject", comments=body.comments
        )
    )
    db.commit()
    db.refresh(version)
    return version


@router.post("/apps/{app_id}/suspend", response_model=schemas.AppOut)
def suspend(
    app_id: str,
    body: dict | None = None,
    db: Session = Depends(get_db),
    user: CurrentUser = Depends(require_role("ADMIN")),
):
    app = db.query(models.App).filter_by(id=app_id).first()
    if not app:
        raise HTTPException(status_code=404, detail={"code": "not_found", "message": "App not found"})
    app.status = "suspended"
    reason = (body or {}).get("reason") if body else None
    db.add(
        models.ReviewEvent(app_version_id=app.versions[-1].id if app.versions else "", actor_id=user.user_id, action="suspend", comments=reason)
    )
    db.commit()
    db.refresh(app)
    return app


@router.post("/apps/{app_id}/resume", response_model=schemas.AppOut)
def resume(
    app_id: str,
    db: Session = Depends(get_db),
    user: CurrentUser = Depends(require_role("ADMIN")),
):
    app = db.query(models.App).filter_by(id=app_id).first()
    if not app:
        raise HTTPException(status_code=404, detail={"code": "not_found", "message": "App not found"})
    app.status = "listed"
    db.commit()
    db.refresh(app)
    return app


@router.delete("/apps/{app_id}", status_code=204)
def remove(
    app_id: str,
    db: Session = Depends(get_db),
    user: CurrentUser = Depends(require_role("ADMIN")),
):
    app = db.query(models.App).filter_by(id=app_id).first()
    if not app:
        raise HTTPException(status_code=404, detail={"code": "not_found", "message": "App not found"})
    app.status = "removed"
    db.commit()


@router.post("/invitations", response_model=schemas.InvitationOut, status_code=201)
def invite(
    body: schemas.InvitationCreateRequest,
    db: Session = Depends(get_db),
    user: CurrentUser = Depends(require_role("ADMIN")),
):
    inv = models.Invitation(
        email=body.email,
        role=body.role,
        org_id=body.org_id,
        invited_by=user.user_id,
        status="pending",
        expires_at=datetime.now(timezone.utc) + timedelta(days=7),
    )
    db.add(inv)
    db.commit()
    db.refresh(inv)
    return inv


@router.put("/users/{user_id}/roles")
def set_roles(
    user_id: str,
    body: dict,
    db: Session = Depends(get_db),
    user: CurrentUser = Depends(require_role("ADMIN")),
):
    roles = body.get("roles", [])
    db.query(models.UserRole).filter_by(user_id=user_id).delete()
    for r in roles:
        db.add(models.UserRole(user_id=user_id, role=r, org_id=user.org_id))
    db.commit()
    target = db.query(models.User).filter_by(id=user_id).first()
    if not target:
        raise HTTPException(status_code=404, detail={"code": "not_found", "message": "User not found"})
    return {"user_id": user_id, "roles": roles}


@router.delete("/users/{user_id}", status_code=204)
def revoke_user(
    user_id: str,
    db: Session = Depends(get_db),
    user: CurrentUser = Depends(require_role("ADMIN")),
):
    db.query(models.UserRole).filter_by(user_id=user_id).delete()
    db.commit()
