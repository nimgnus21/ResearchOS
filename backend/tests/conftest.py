"""Test setup: a dedicated PostgreSQL database (researchos_test), synchronous ingestion,
temporary file storage, and no LLM unless a test injects a scripted test double."""
import os
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[2]
TEST_DB = os.environ.get(
    "TEST_DATABASE_URL", "postgresql+psycopg://postgres:postgres@localhost:5432/researchos_test"
)
os.environ["DATABASE_URL"] = TEST_DB
os.environ["INGEST_SYNC"] = "true"
os.environ["LLM_PROVIDER"] = "none"
os.environ["EMBEDDING_PROVIDER"] = "hash"
os.environ.pop("LLM_API_KEY", None)

sys.path.insert(0, str(ROOT / "eval" / "corpus"))


@pytest.fixture(scope="session", autouse=True)
def _database(tmp_path_factory):
    storage = tmp_path_factory.mktemp("storage")
    os.environ["STORAGE_DIR"] = str(storage)
    from alembic import command
    from alembic.config import Config

    from app.config import get_settings
    from app.db import reset_engine

    get_settings.cache_clear()
    cfg = Config(str(ROOT / "backend" / "alembic.ini"))
    cfg.set_main_option("script_location", str(ROOT / "backend" / "alembic"))
    cfg.attributes["database_url"] = TEST_DB
    command.downgrade(cfg, "base")
    command.upgrade(cfg, "head")
    reset_engine()
    yield
    reset_engine()


@pytest.fixture(scope="session")
def corpus_dir(tmp_path_factory) -> Path:
    import build_corpus

    out = tmp_path_factory.mktemp("corpus")
    build_corpus.OUT = out
    build_corpus.build()
    return out


@pytest.fixture()
def client():
    from fastapi.testclient import TestClient

    from app.main import app
    from app.services.llm import set_llm

    set_llm(None)
    with TestClient(app) as c:
        yield c
    set_llm(None)


@pytest.fixture()
def project(client):
    r = client.post("/api/projects", json={"name": "测试项目", "description": "pytest"})
    assert r.status_code == 201
    pid = r.json()["id"]
    yield pid
    client.delete(f"/api/projects/{pid}")


def upload(client, pid, path: Path, name: str | None = None, data: bytes | None = None):
    content = data if data is not None else path.read_bytes()
    return client.post(
        f"/api/projects/{pid}/documents",
        files=[("files", (name or path.name, content, "application/octet-stream"))],
    )


@pytest.fixture()
def loaded_project(client, project, corpus_dir):
    """A project with the full evaluation corpus ingested."""
    files = sorted(corpus_dir.iterdir())
    r = client.post(
        f"/api/projects/{project}/documents",
        files=[("files", (f.name, f.read_bytes(), "application/octet-stream")) for f in files],
    )
    assert r.status_code == 200, r.text
    docs = {d["filename"]: d for d in client.get(f"/api/projects/{project}/documents").json()}
    return project, docs


class ScriptedLLM:
    """Test double that returns a pre-written JSON payload and records the prompts it received.
    Used only in tests to exercise validation logic; it is never wired into the running app."""

    provider = "test-double"
    model = "scripted"

    def __init__(self, response):
        self.response = response
        self.calls: list[dict] = []

    def complete_json(self, system, user, schema, max_tokens=None):
        from app.services.llm import LLMResult

        self.calls.append({"system": system, "user": user, "schema": schema})
        data = self.response(user) if callable(self.response) else self.response
        return LLMResult(data=data, model=self.model, provider=self.provider, latency_ms=0)
