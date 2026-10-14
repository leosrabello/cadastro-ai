"""Tests run inside the backend container against a real PostgreSQL database (created and
migrated with the real Alembic migration), real Tesseract OCR, and Redis db 15.

    docker compose run --rm api pytest
"""

import os
import shutil
import tempfile
import uuid
from datetime import date

import pytest
from cryptography.fernet import Fernet
from sqlalchemy import create_engine, text
from sqlalchemy.engine import make_url

_base = os.environ.get("DATABASE_URL", "postgresql+psycopg://cadastro:cadastro@localhost:5432/cadastro")
_test_url = make_url(_base).set(database="cadastro_test")
_tmp = tempfile.mkdtemp(prefix="cadastro-test-")
os.environ.update(
    {
        "DATABASE_URL": _test_url.render_as_string(hide_password=False),
        "REDIS_URL": os.environ.get("REDIS_URL", "redis://redis:6379/0").rsplit("/", 1)[0] + "/15",
        "JWT_SECRET": "test-secret-" + "x" * 40,
        "STORAGE_ENCRYPTION_KEY": Fernet.generate_key().decode(),
        "STORAGE_DIR": os.path.join(_tmp, "docs"),
        "WATCH_ALLOWED_ROOTS": os.path.join(_tmp, "watch"),
        "APP_ENV": "test",
        "AI_PROVIDER": "none",
        "BOOTSTRAP_ADMIN_EMAIL": "",
        "BOOTSTRAP_ADMIN_PASSWORD": "",
    }
)

from app.config import get_settings  # noqa: E402

get_settings.cache_clear()


def _create_database():
    admin = create_engine(make_url(_base).set(database="postgres"), isolation_level="AUTOCOMMIT")
    with admin.connect() as c:
        c.execute(text("DROP DATABASE IF EXISTS cadastro_test WITH (FORCE)"))
        c.execute(text("CREATE DATABASE cadastro_test"))
    admin.dispose()


@pytest.fixture(scope="session", autouse=True)
def database():
    _create_database()
    from alembic import command
    from alembic.config import Config

    cfg = Config(os.path.join(os.path.dirname(__file__), "..", "alembic.ini"))
    cfg.set_main_option("script_location", os.path.join(os.path.dirname(__file__), "..", "alembic"))
    command.upgrade(cfg, "head")
    yield
    shutil.rmtree(_tmp, ignore_errors=True)


TABLES = [
    "extracted_fields", "findings", "processing_jobs", "decisions", "ingest_records", "watcher_status",
    "app_settings", "counters", "user_sessions", "documents", "registrations", "signature_contracts",
    "signature_trackings", "portfolio_clients", "commercials", "data_imports", "users",
]


@pytest.fixture(autouse=True)
def clean(database):
    from app.db import engine
    from app.pipeline import ai, ocr
    from app.ratelimit import _client

    with engine().begin() as c:
        c.execute(text("ALTER TABLE audit_events DISABLE TRIGGER USER"))
        c.execute(text("TRUNCATE audit_events, " + ", ".join(TABLES) + " RESTART IDENTITY CASCADE"))
        c.execute(text("ALTER TABLE audit_events ENABLE TRIGGER USER"))
    try:
        _client().flushdb()
    except Exception:
        pass
    from app.settings_store import seed_defaults
    from app.db import session_scope

    with session_scope() as db:
        seed_defaults(db)
    ocr.set_provider(None)
    ai.set_provider(None)
    import app.worker as worker

    worker._inline_runner = lambda doc_id: worker.execute(doc_id, can_retry=False)
    yield
    worker._inline_runner = None
    ocr.set_provider(None)
    ai.set_provider(None)


@pytest.fixture
def client():
    from fastapi.testclient import TestClient

    from app.main import app

    with TestClient(app) as c:
        yield c


PASSWORD = "Senha-Forte-123"


def make_user(role: str, email: str | None = None):
    from app.db import session_scope
    from app.models import User
    from app.security import hash_password

    with session_scope() as db:
        u = User(email=email or f"{role}-{uuid.uuid4().hex[:6]}@teste.local", name=f"{role.title()} Teste", role=role,
                 password_hash=hash_password(PASSWORD))
        db.add(u)
        db.flush()
        return u.email


def login(client, email: str) -> dict:
    r = client.post("/api/auth/login", json={"email": email, "password": PASSWORD})
    assert r.status_code == 200, r.text
    return {"Authorization": f"Bearer {r.json()['token']}"}


@pytest.fixture
def analyst(client):
    return login(client, make_user("analyst"))


@pytest.fixture
def supervisor(client):
    return login(client, make_user("supervisor"))


@pytest.fixture
def admin(client):
    return login(client, make_user("admin"))


@pytest.fixture
def auditor(client):
    return login(client, make_user("auditor"))


def new_registration(client, headers, name="MARIA APARECIDA DOS SANTOS SILVA", cpf=None, kind="PF", modality="normal", client_id=None):
    body = {"kind": kind, "subject_name": name, "modality": modality}
    if client_id:
        body["client_id"] = client_id
    if cpf:
        body["tax_id"] = cpf
    r = client.post("/api/registrations", json=body, headers=headers)
    assert r.status_code == 201, r.text
    return r.json()


def upload(client, headers, reg_id, name, data, mime="application/octet-stream"):
    return client.post(f"/api/registrations/{reg_id}/documents", files=[("files", (name, data, mime))], headers=headers)


def today() -> date:
    return date.today()
