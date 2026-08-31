# SPDX-FileCopyrightText: (C) 2026 Intel Corporation
# SPDX-License-Identifier: Apache-2.0
"""
Local reference-implementation DB layer.

Production (per edge-ai-catalog-design.md §9.1) uses RDS Postgres. This
local/mocked reference implementation uses SQLite so the whole stack runs
with zero external infra — swap CATALOG_DB_URL to a Postgres DSN and it
works unchanged (SQLAlchemy Core/ORM only, no SQLite-specific features).
"""
import os

from sqlalchemy import create_engine
from sqlalchemy.orm import DeclarativeBase, sessionmaker

DB_URL = os.environ.get(
    "CATALOG_DB_URL", "sqlite:///./catalog.db"
)

connect_args = {"check_same_thread": False} if DB_URL.startswith("sqlite") else {}
engine = create_engine(DB_URL, connect_args=connect_args)
SessionLocal = sessionmaker(autocommit=False, autoflush=False, bind=engine)


class Base(DeclarativeBase):
    pass


def get_db():
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()
