"""6. Cross-project isolation, at API level and enforced by database constraints."""
import uuid

import pytest
from sqlalchemy import text
from sqlalchemy.exc import IntegrityError

from app.db import session_factory
from tests.conftest import upload


@pytest.fixture()
def two_projects(client, corpus_dir):
    a = client.post("/api/projects", json={"name": "A"}).json()["id"]
    b = client.post("/api/projects", json={"name": "B"}).json()["id"]
    doc_a = upload(client, a, corpus_dir / "kx200_revised_report_2024.pdf").json()[0]["document"]
    doc_b = upload(client, b, corpus_dir / "kx200_field_notes_en.md").json()[0]["document"]
    yield a, b, doc_a, doc_b
    client.delete(f"/api/projects/{a}")
    client.delete(f"/api/projects/{b}")


def test_search_and_ask_never_return_other_projects(client, two_projects):
    a, b, doc_a, doc_b = two_projects
    res = client.post(f"/api/projects/{b}/search", json={"query": "激光对中 角向不对中 0.35"}).json()
    assert all(r["document_id"] == doc_b["id"] for r in res["results"])
    ans = client.post(f"/api/projects/{b}/ask", json={"question": "角向不对中达到多少？"}).json()
    assert all(e["document_id"] == doc_b["id"] for e in ans["payload"]["evidence"])


def test_cross_project_ids_return_404(client, two_projects):
    a, b, doc_a, doc_b = two_projects
    assert client.get(f"/api/projects/{b}/documents/{doc_a['id']}").status_code == 404
    assert client.get(f"/api/projects/{b}/documents/{doc_a['id']}/file").status_code == 404
    assert client.get(f"/api/projects/{b}/documents/{doc_a['id']}/pages/1").status_code == 404
    assert client.delete(f"/api/projects/{b}/documents/{doc_a['id']}").status_code == 404
    assert client.post(f"/api/projects/{b}/search", json={"query": "x", "document_ids": [doc_a["id"]]}).status_code == 404
    assert client.post(f"/api/projects/{b}/ask", json={"question": "x", "document_ids": [doc_a["id"]]}).status_code == 404
    chunk_a = client.get(f"/api/projects/{a}/documents/{doc_a['id']}/chunks").json()[0]["id"]
    assert client.get(f"/api/projects/{b}/chunks/{chunk_a}").status_code == 404
    ans = client.post(f"/api/projects/{a}/ask", json={"question": "角向不对中达到多少？"}).json()
    cit = ans["payload"]["evidence"][0]["citation_id"]
    assert client.get(f"/api/projects/{a}/citations/{cit}").status_code == 200
    assert client.get(f"/api/projects/{b}/citations/{cit}").status_code == 404
    conv = ans["conversation_id"]
    assert client.get(f"/api/projects/{b}/conversations/{conv}/messages").status_code == 404
    assert client.post(f"/api/projects/{b}/ask", json={"question": "x", "conversation_id": conv}).status_code == 404


def test_database_rejects_mismatched_project_ids(client, two_projects):
    a, b, doc_a, doc_b = two_projects
    with session_factory() as db:
        with pytest.raises(IntegrityError):
            db.execute(
                text(
                    "INSERT INTO document_chunks (id, document_id, project_id, chunk_index, page_number, text, "
                    "char_start, char_end, text_hash, search_text) "
                    "VALUES (:id, :doc, :proj, 999, 1, 'x', 0, 1, repeat('0', 64), 'x')"
                ),
                {"id": uuid.uuid4(), "doc": doc_a["id"], "proj": b},
            )
        db.rollback()
