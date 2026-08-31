# SPDX-FileCopyrightText: (C) 2026 Intel Corporation
# SPDX-License-Identifier: Apache-2.0
"""
Edge AI Catalog Service — local reference implementation (Tier 2).

Mirrors openapi/catalog-service.openapi.yaml. Mocked pieces (clearly
marked in their own modules): auth (auth.py), storage (storage.py),
ECR registry + vuln scan (registry.py). Everything else (data model,
onboarding validation, review state machine, install-token issue/redeem)
is real logic, matching edge-ai-catalog-design.md / technical-flows.md.

Run:
    uvicorn app.main:app --reload --port 8000
"""
from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from . import models
from .db import Base, engine
from .meta import dev_router, router as meta_router
from .routers import admin, catalog, isv

Base.metadata.create_all(bind=engine)

app = FastAPI(
    title="Edge AI Catalog Service (local reference implementation)",
    version="0.1.0",
    description=(
        "Local, fully-mocked (no real AWS) reference implementation of "
        "edge-ai-catalog-design.md. See README.md in this directory for "
        "what is real vs. mocked."
    ),
)

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_methods=["*"],
    allow_headers=["*"],
)

API_PREFIX = "/api/v1"
app.include_router(meta_router, prefix=API_PREFIX)
app.include_router(isv.router, prefix=API_PREFIX)
app.include_router(admin.router, prefix=API_PREFIX)
app.include_router(catalog.router, prefix=API_PREFIX)
app.include_router(dev_router)  # /dev/* — not versioned, local-impl-only


@app.get("/healthz")
def healthz():
    return {"status": "ok"}
