# SPDX-FileCopyrightText: (C) 2026 Intel Corporation
# SPDX-License-Identifier: Apache-2.0
"""
MOCKED auth shim for the local reference implementation.

Production (edge-ai-catalog-design.md §4.1, flow A1) uses SSO/Cognito +
an allowlist + a server-side session cookie. This local implementation has
no real IdP, so it is replaced by two request headers that a real
Storefront would never send un-authenticated in production:

    X-Debug-User-Email : an email seeded via /dev/seed (see seed.py)
    X-Debug-Role        : which of that user's roles to act as (OXM|ISV|SI|ADMIN)

This is intentionally loud/ugly (`X-Debug-*` prefix) so nobody mistakes it
for production auth. Swapping in real SSO only requires replacing
`get_current_user` below with real session-cookie validation — every
router downstream depends only on `CurrentUser`, not on how it was derived.
"""
from dataclasses import dataclass

from fastapi import Depends, Header, HTTPException
from sqlalchemy.orm import Session

from . import models
from .db import get_db


@dataclass
class CurrentUser:
    user_id: str
    email: str
    role: str
    org_id: str
    org_type: str


def get_current_user(
    x_debug_user_email: str | None = Header(default=None),
    x_debug_role: str | None = Header(default=None),
    db: Session = Depends(get_db),
) -> CurrentUser:
    if not x_debug_user_email:
        raise HTTPException(
            status_code=401,
            detail={"code": "unauthorized", "message": "Missing X-Debug-User-Email (mocked auth)"},
        )
    user = db.query(models.User).filter_by(email=x_debug_user_email).first()
    if not user:
        raise HTTPException(
            status_code=401,
            detail={"code": "unauthorized", "message": "Unknown user (mocked auth) — seed it first"},
        )
    roles = db.query(models.UserRole).filter_by(user_id=user.id).all()
    if not roles:
        raise HTTPException(
            status_code=403,
            detail={"code": "forbidden", "message": "User has no roles assigned"},
        )
    chosen = None
    if x_debug_role:
        chosen = next((r for r in roles if r.role == x_debug_role), None)
        if not chosen:
            raise HTTPException(
                status_code=403,
                detail={"code": "forbidden", "message": f"User has no role {x_debug_role}"},
            )
    else:
        chosen = roles[0]
    org = db.query(models.Organization).filter_by(id=chosen.org_id).first()
    return CurrentUser(
        user_id=user.id,
        email=user.email,
        role=chosen.role,
        org_id=chosen.org_id,
        org_type=org.org_type if org else "",
    )


def require_role(*allowed_roles: str):
    def _dep(user: CurrentUser = Depends(get_current_user)) -> CurrentUser:
        if user.role not in allowed_roles:
            raise HTTPException(
                status_code=403,
                detail={
                    "code": "forbidden",
                    "message": f"Role {user.role} not permitted; requires one of {allowed_roles}",
                },
            )
        return user

    return _dep
