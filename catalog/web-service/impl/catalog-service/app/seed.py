# SPDX-FileCopyrightText: (C) 2026 Intel Corporation
# SPDX-License-Identifier: Apache-2.0
"""Seed data for local dev/testing — one org+user per role."""
from sqlalchemy.orm import Session

from . import models

SEED_USERS = [
    {"email": "isv1@example-vendor.com", "name": "Isabel Vendor", "role": "ISV", "org": "Example ISV Inc", "org_type": "ISV"},
    {"email": "admin1@intel.com", "name": "Ada Min", "role": "ADMIN", "org": "Intel Catalog Governance", "org_type": "INTEL"},
    {"email": "si1@example-integrator.com", "name": "Sam Integrator", "role": "SI", "org": "Example SI Co", "org_type": "SI"},
    {"email": "oxm1@example-oxm.com", "name": "Otto Xm", "role": "OXM", "org": "Example OXM", "org_type": "OXM"},
]


def run_seed(db: Session) -> dict:
    created_users = []
    org_cache: dict[str, models.Organization] = {}
    for u in SEED_USERS:
        org = org_cache.get(u["org"]) or db.query(models.Organization).filter_by(name=u["org"]).first()
        if not org:
            org = models.Organization(name=u["org"], org_type=u["org_type"])
            db.add(org)
            db.flush()
        org_cache[u["org"]] = org

        user = db.query(models.User).filter_by(email=u["email"]).first()
        if not user:
            user = models.User(email=u["email"], name=u["name"])
            db.add(user)
            db.flush()

        role = db.query(models.UserRole).filter_by(user_id=user.id, role=u["role"]).first()
        if not role:
            db.add(models.UserRole(user_id=user.id, role=u["role"], org_id=org.id))

        created_users.append({"email": u["email"], "role": u["role"], "org_id": org.id, "user_id": user.id})

    db.commit()
    return {"users": created_users}
