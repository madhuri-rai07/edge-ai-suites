# SPDX-FileCopyrightText: (C) 2026 Intel Corporation
# SPDX-License-Identifier: Apache-2.0
"""
/me (real per design §7) + /dev/* endpoints (local-reference-impl-only:
mocked storage PUT/GET, seed data, and a manual "simulate the ECR push
completed" trigger standing in for the EventBridge webhook).
"""
from fastapi import APIRouter, Depends, HTTPException, Request
from sqlalchemy.orm import Session

from . import models, registry, schemas, storage
from .auth import CurrentUser, get_current_user
from .db import get_db

router = APIRouter(tags=["meta"])


@router.get("/me", response_model=schemas.UserProfile)
def me(user: CurrentUser = Depends(get_current_user), db: Session = Depends(get_db)):
    roles = db.query(models.UserRole).filter_by(user_id=user.user_id).all()
    return schemas.UserProfile(
        user_id=user.user_id,
        email=user.email,
        roles=[r.role for r in roles],
        org_id=user.org_id,
        org_type=user.org_type,
    )


# ------------------------------------------------------- /dev (mocked) --
dev_router = APIRouter(prefix="/dev", tags=["dev"])


@dev_router.put("/storage/{key:path}")
async def dev_storage_put(key: str, request: Request):
    data = await request.body()
    storage.write_bytes(key, data)
    return {"ok": True, "bytes": len(data)}


@dev_router.get("/storage/{key:path}")
def dev_storage_get(key: str):
    if not storage.exists(key):
        raise HTTPException(status_code=404, detail={"code": "not_found", "message": "No such object"})
    return {"key": key, "size": len(storage.read_bytes(key))}


@dev_router.post("/simulate-ecr-push/{image_id}")
def simulate_ecr_push(image_id: str, db: Session = Depends(get_db)):
    """
    Stands in for: ISV runs `docker push` -> ECR EventBridge rule fires ->
    catalog webhook -> async vuln-scan worker completes. See
    app/registry.py module docstring.
    """
    image = db.query(models.AppVersionImage).filter_by(id=image_id).first()
    if not image:
        raise HTTPException(status_code=404, detail={"code": "not_found", "message": "Image not found"})
    image.scan_status = registry.simulate_scan(image.source)
    db.commit()
    return {"image_id": image_id, "scan_status": image.scan_status}


@dev_router.post("/seed")
def dev_seed(db: Session = Depends(get_db)):
    from .seed import run_seed

    return run_seed(db)
