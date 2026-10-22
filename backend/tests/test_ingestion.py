"""Pipeline via the API: statuses, dedupe, limits, OCR, retry, metadata, 8. delete cleanup."""
import json
from pathlib import Path

from sqlalchemy import func, select, text

from app.db import session_factory
from app.models import Document, DocumentChunk, DocumentPage
from tests.conftest import upload


def test_upload_all_formats_and_statuses(client, loaded_project):
    pid, docs = loaded_project
    assert docs["kx200_incident_report_2023.pdf"]["status"] == "ready"
    assert docs["kx200_vendor_bulletin.docx"]["status"] == "ready"
    assert docs["operation_log_summary.txt"]["status"] == "ready"
    assert docs["maintenance_team_memo.md"]["status"] == "ready"
    scanned = docs["scanned_inspection_sheet.pdf"]
    assert scanned["status"] == "needs_ocr"
    assert "OCR" in scanned["error_message"]
    assert scanned["chunk_count"] == 0
    for d in docs.values():
        assert len(d["content_hash"]) == 64


def test_chunk_records_keep_page_section_and_vectors(client, loaded_project):
    pid, docs = loaded_project
    did = docs["kx200_revised_report_2024.pdf"]["id"]
    chunks = client.get(f"/api/projects/{pid}/documents/{did}/chunks").json()
    assert {c["page_number"] for c in chunks} == {1, 2, 3, 4}
    root = next(c for c in chunks if "0.35 mm/100 mm" in c["text"])
    assert root["page_number"] == 2 and root["section_title"] == "二、根本原因"
    page = client.get(f"/api/projects/{pid}/documents/{did}/pages/2").json()
    assert page["text"][root["char_start"]:root["char_end"]] == root["text"]
    assert all(c["embedding_model"].startswith("hash-lexical") for c in chunks)
    with session_factory() as db:
        n_vec = db.scalar(text("SELECT count(*) FROM document_chunks WHERE document_id = :d AND embedding IS NOT NULL"), {"d": did})
        assert n_vec == len(chunks)
    # parsed output is persisted next to the original file
    doc = client.get(f"/api/projects/{pid}/documents/{did}").json()
    assert doc["metadata"]["published_date_source"] == "document_text"


def test_txt_chunks_have_line_numbers(client, loaded_project):
    pid, docs = loaded_project
    did = docs["operation_log_summary.txt"]["id"]
    chunks = client.get(f"/api/projects/{pid}/documents/{did}/chunks").json()
    p2 = next(c for c in chunks if c["page_number"] == 2)
    assert p2["line_start"] >= 8 and "62°C" in p2["text"]


def test_duplicate_detection(client, project, corpus_dir):
    f = corpus_dir / "maintenance_team_memo.md"
    assert upload(client, project, f).status_code == 200
    r = upload(client, project, f, name="renamed_copy.md")
    assert r.status_code == 409
    assert "重复" in r.json()["detail"]["message"]
    assert r.json()["detail"]["existing_document_id"]


def test_same_file_allowed_in_different_projects(client, project, corpus_dir):
    other = client.post("/api/projects", json={"name": "other"}).json()["id"]
    try:
        f = corpus_dir / "maintenance_team_memo.md"
        assert upload(client, project, f).status_code == 200
        assert upload(client, other, f).status_code == 200
    finally:
        client.delete(f"/api/projects/{other}")


def test_rejects_empty_unsupported_and_oversized(client, project, monkeypatch):
    r = upload(client, project, Path("empty.txt"), data=b"")
    assert r.status_code == 400 and "为空" in r.json()["detail"]["message"]
    r = upload(client, project, Path("a.exe"), data=b"MZ....")
    assert r.status_code == 415
    r = upload(client, project, Path("fake.pdf"), data=b"not a pdf at all")
    assert r.status_code == 415
    from app.config import get_settings

    monkeypatch.setattr(get_settings(), "max_upload_mb", 0)
    r = upload(client, project, Path("big.txt"), data=b"x" * 10)
    assert r.status_code == 413


def test_batch_upload_reports_per_file_results(client, project):
    r = client.post(
        f"/api/projects/{project}/documents",
        files=[("files", ("ok.txt", "轴承温度。".encode(), "text/plain")), ("files", ("bad.txt", b"", "text/plain"))],
    )
    assert r.status_code == 200
    res = {x["filename"]: x for x in r.json()}
    assert res["ok.txt"]["ok"] and not res["bad.txt"]["ok"]


def test_corrupt_file_fails_and_retry_reprocesses(client, project):
    r = upload(client, project, Path("broken.pdf"), data=b"%PDF-1.7 garbage \x00\x01")
    doc = r.json()[0]["document"]
    doc = client.get(f"/api/projects/{project}/documents/{doc['id']}").json()
    assert doc["status"] == "failed" and "损坏" in doc["error_message"]
    assert doc["attempts"] == 1
    # Simulate fixing the stored file (e.g. a transient storage problem) and retry.
    import pymupdf

    good = pymupdf.open()
    good.new_page().insert_text((50, 50), "Recovered content about bearings.")
    with session_factory() as db:
        path = db.get(Document, __import__("uuid").UUID(doc["id"])).storage_path
    Path(path).write_bytes(good.tobytes())
    r = client.post(f"/api/projects/{project}/documents/{doc['id']}/retry")
    assert r.status_code == 200
    doc = client.get(f"/api/projects/{project}/documents/{doc['id']}").json()
    assert doc["status"] == "ready" and doc["attempts"] == 2 and doc["chunk_count"] == 1
    # ready documents cannot be "retried"
    assert client.post(f"/api/projects/{project}/documents/{doc['id']}/retry").status_code == 409


def test_reprocessing_is_idempotent(client, project, corpus_dir):
    from app.services.ingestion import process_document

    doc = upload(client, project, corpus_dir / "kx200_incident_report_2023.pdf").json()[0]["document"]
    before = client.get(f"/api/projects/{project}/documents/{doc['id']}/chunks").json()
    process_document(__import__("uuid").UUID(doc["id"]), force=True)
    after = client.get(f"/api/projects/{project}/documents/{doc['id']}/chunks").json()
    assert len(after) == len(before)


def test_delete_document_cleans_chunks_vectors_pages_and_files(client, loaded_project):
    pid, docs = loaded_project
    target = docs["kx200_revised_report_2024.pdf"]
    did = target["id"]
    # make a citation pointing at this document
    ans = client.post(f"/api/projects/{pid}/ask", json={"question": "激光对中检测显示的角向不对中是多少？"}).json()
    cit_ids = [e["citation_id"] for e in ans["payload"]["evidence"] if e["document_id"] == did]
    assert cit_ids
    with session_factory() as db:
        storage = Path(db.get(Document, __import__("uuid").UUID(did)).storage_path).parent
    assert (storage / "parsed.json").exists()
    before = client.post(f"/api/projects/{pid}/search", json={"query": "角向不对中 0.35"}).json()
    assert any(r["document_id"] == did for r in before["results"])

    r = client.delete(f"/api/projects/{pid}/documents/{did}")
    assert r.status_code == 200 and r.json()["deleted_chunks"] == target["chunk_count"]
    with session_factory() as db:
        assert db.scalar(select(func.count()).select_from(DocumentChunk).where(DocumentChunk.document_id == did)) == 0
        assert db.scalar(select(func.count()).select_from(DocumentPage).where(DocumentPage.document_id == did)) == 0
    assert not storage.exists()
    after = client.post(f"/api/projects/{pid}/search", json={"query": "角向不对中 0.35"}).json()
    assert all(r["document_id"] != did for r in after["results"])
    assert client.get(f"/api/projects/{pid}/documents/{did}").status_code == 404
    # citation survives as a snapshot, explicitly flagged as no longer available
    c = client.get(f"/api/projects/{pid}/citations/{cit_ids[0]}").json()
    assert c["source_available"] is False and c["notice"]
    assert c["citation"]["document_name"] == "kx200_revised_report_2024.pdf"


def test_delete_project_removes_everything(client, corpus_dir):
    pid = client.post("/api/projects", json={"name": "to-delete"}).json()["id"]
    upload(client, pid, corpus_dir / "maintenance_team_memo.md")
    assert client.delete(f"/api/projects/{pid}").status_code == 204
    assert client.get(f"/api/projects/{pid}").status_code == 404
    with session_factory() as db:
        assert db.scalar(text("SELECT count(*) FROM document_chunks WHERE project_id = :p"), {"p": pid}) == 0


def test_user_can_set_published_date_and_it_survives_reprocessing(client, project, corpus_dir):
    from app.services.ingestion import process_document

    doc = upload(client, project, corpus_dir / "kx200_field_notes_en.md").json()[0]["document"]
    r = client.patch(f"/api/projects/{project}/documents/{doc['id']}", json={"published_date": "2020-01-01"})
    assert r.json()["published_date"] == "2020-01-01"
    process_document(__import__("uuid").UUID(doc["id"]), force=True)
    d = client.get(f"/api/projects/{project}/documents/{doc['id']}").json()
    assert d["published_date"] == "2020-01-01"


def test_processing_claim_prevents_double_processing(client, project, corpus_dir):
    import uuid as _uuid

    from app.services.ingestion import process_document

    doc = upload(client, project, corpus_dir / "maintenance_team_memo.md").json()[0]["document"]
    did = _uuid.UUID(doc["id"])
    with session_factory() as db:
        db.execute(text("UPDATE documents SET status='processing', processing_started_at=now() WHERE id=:d"), {"d": did})
        db.commit()
    assert process_document(did) == "skipped"  # another worker holds the claim
    with session_factory() as db:
        assert db.get(Document, did).attempts == 1


def test_stale_processing_job_is_recovered(client, project, corpus_dir):
    import uuid as _uuid

    from app.services.ingestion import resume_unfinished

    doc = upload(client, project, corpus_dir / "kx200_field_notes_en.md").json()[0]["document"]
    did = _uuid.UUID(doc["id"])
    with session_factory() as db:
        db.execute(text("UPDATE documents SET status='processing', processing_started_at=now() - interval '2 hours' WHERE id=:d"), {"d": did})
        db.commit()
    resume_unfinished()  # INGEST_SYNC=true -> processed inline
    d = client.get(f"/api/projects/{project}/documents/{did}").json()
    assert d["status"] == "ready" and d["attempts"] == 2


def test_citation_view_windows_very_long_pages(client, project):
    lines = "".join(f"第{i}行：普通运行记录，温度正常。\n" for i in range(20000))
    body = (lines + "关键记录：轴承在第 20001 行出现异常振动 9.9 mm/s。\n" + lines).encode()
    doc = upload(client, project, None, name="long.txt", data=body).json()[0]["document"]
    res = client.post(f"/api/projects/{project}/search", json={"query": "异常振动 9.9"}).json()
    top = res["results"][0]
    assert "9.9 mm/s" in top["text"] and top["line_start"] <= 20001 <= top["line_end"]
    src = client.get(f"/api/projects/{project}/chunks/{top['chunk_id']}").json()
    assert len(src["page_text"]) < 12000 and src["page_text_truncated"] == {"before": True, "after": True}
    assert src["page_text"][src["chunk"]["char_start"]:src["chunk"]["char_end"]] == src["chunk"]["text"]
