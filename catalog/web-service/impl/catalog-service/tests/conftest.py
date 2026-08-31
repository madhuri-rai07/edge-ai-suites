# SPDX-FileCopyrightText: (C) 2026 Intel Corporation
# SPDX-License-Identifier: Apache-2.0
import os
import tempfile

import pytest


@pytest.fixture()
def client():
    """Fresh app + fresh SQLite DB + fresh local file storage dir per test."""
    db_fd, db_path = tempfile.mkstemp(suffix=".db")
    os.close(db_fd)
    os.remove(db_path)
    storage_dir = tempfile.mkdtemp()
    os.environ["CATALOG_DB_URL"] = f"sqlite:///{db_path}"
    os.environ["CATALOG_STORAGE_DIR"] = storage_dir

    # Force re-import so db.py/storage.py pick up the new env vars.
    import sys

    for mod in list(sys.modules):
        if mod == "app" or mod.startswith("app."):
            del sys.modules[mod]

    from fastapi.testclient import TestClient

    from app.main import app

    with TestClient(app) as c:
        yield c

    os.remove(db_path)
