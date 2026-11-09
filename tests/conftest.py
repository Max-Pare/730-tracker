# SPDX-License-Identifier: AGPL-3.0-or-later
import re
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).parent))

PASSWORD = "una-password-lunga"


@pytest.fixture
def settings(tmp_path):
    from app.config import Settings

    s = Settings(data_dir=tmp_path / "data")
    s.database_url = f"sqlite:///{tmp_path / 'data' / 'tracker.db'}"
    # Cheap KDF for tests (production default: 64 MiB, t=3).
    s.kdf_memory_kib = 1024
    s.kdf_time_cost = 1
    return s


@pytest.fixture
def app(settings):
    from app.main import create_app

    return create_app(settings)


def make_client(app):
    from fastapi.testclient import TestClient

    return TestClient(app, base_url="http://testserver")


@pytest.fixture
def client(app):
    return make_client(app)


def csrf_of(client) -> str:
    html = client.get("/account").text
    return re.search(r'name="csrf" value="([^"]+)"', html).group(1)


def register(client, username, password=PASSWORD, invite=""):
    r = client.post("/register", data={"username": username, "password": password, "password2": password, "invite": invite})
    code = re.search(r'id="recovery-code">([^<]+)<', r.text)
    return r, (code.group(1).strip() if code else None)


def create_invite(admin_client) -> str:
    r = admin_client.post("/admin/invites", data={"csrf": csrf_of(admin_client), "note": "test"})
    return re.search(r"invite=([A-Za-z0-9_\-]+)", r.text).group(1)


@pytest.fixture
def two_users(app):
    """(admin_client, alice_client, bob_client) with alice/bob invited by admin."""
    admin = make_client(app)
    register(admin, "admin")
    clients = [admin]
    for name in ("alice", "bob"):
        c = make_client(app)
        r, _ = register(c, name, invite=create_invite(admin))
        assert r.status_code == 200, r.text
        clients.append(c)
    return tuple(clients)
