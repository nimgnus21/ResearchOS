"""5. Hybrid retrieval: merging, de-duplication, ranking, filters, thresholds, logging."""
import uuid

from app.db import session_factory
from app.models import RetrievalRun
from tests.conftest import upload


def _search(client, pid, **body):
    r = client.post(f"/api/projects/{pid}/search", json=body)
    assert r.status_code == 200, r.text
    return r.json()


def test_result_fields_and_merge(client, loaded_project):
    pid, docs = loaded_project
    res = _search(client, pid, query="修订报告的补脂周期是多少运行小时", top_k=8)
    assert res["results"]
    ids = [r["chunk_id"] for r in res["results"]]
    assert len(ids) == len(set(ids)), "merged candidates must be de-duplicated"
    for r in res["results"]:
        for key in ("document_id", "document_name", "page_number", "chunk_id", "text", "relevance"):
            assert key in r
        rel = r["relevance"]
        assert rel["keyword_rank"] is not None or rel["vector_rank"] is not None
    # union of both retrievers: at least one result found by both
    assert any(r["relevance"]["keyword_rank"] and r["relevance"]["vector_rank"] for r in res["results"])
    scores = [r["relevance"]["score"] for r in res["results"]]
    assert scores == sorted(scores, reverse=True)
    assert res["params"]["keyword_candidates"] > 0 and res["params"]["vector_candidates"] > 0


def test_top_result_is_correct_page(client, loaded_project):
    pid, docs = loaded_project
    top = _search(client, pid, query="激光对中检测显示的角向不对中是多少")["results"][0]
    assert top["document_name"] == "kx200_revised_report_2024.pdf" and top["page_number"] == 2


def test_english_query(client, loaded_project):
    pid, _ = loaded_project
    top = _search(client, pid, query="What was the bearing overheating at Site 7 linked to?")["results"][0]
    assert top["document_name"] == "kx200_field_notes_en.md"
    assert "misalignment" in top["text"]


def test_document_and_page_filters(client, loaded_project):
    pid, docs = loaded_project
    did = docs["kx200_incident_report_2023.pdf"]["id"]
    res = _search(client, pid, query="补脂周期", document_ids=[did])
    assert res["results"] and all(r["document_id"] == did for r in res["results"])
    res = _search(client, pid, query="补脂周期", document_ids=[did], page_from=3, page_to=3)
    assert res["results"] and all(r["page_number"] == 3 for r in res["results"])


def test_thresholds_are_configurable_and_logged(client, loaded_project):
    pid, _ = loaded_project
    strict = _search(client, pid, query="补脂周期 火星基地", min_term_coverage=1.0, min_vector_sim=1.0)
    assert strict["sufficient"] is False
    assert all(not r["relevance"]["passes_threshold"] for r in strict["results"])
    loose = _search(client, pid, query="补脂周期", min_term_coverage=0.1)
    assert loose["sufficient"] is True
    with session_factory() as db:
        run = db.get(RetrievalRun, uuid.UUID(loose["retrieval_run_id"]))
        assert run.purpose == "search" and run.params["min_term_coverage"] == 0.1
        assert [r["chunk_id"] for r in run.results] == [r["chunk_id"] for r in loose["results"]]


def test_vector_similarity_alone_does_not_make_evidence(client, loaded_project):
    pid, _ = loaded_project
    res = _search(client, pid, query="KX-200 泵的采购价格是多少？")
    assert res["results"], "vector search always returns nearest neighbours"
    assert res["sufficient"] is False


def test_identical_text_in_same_document_is_deduplicated(client, project):
    para = "重复的免责声明：本文件仅供内部参考使用。"
    body = (para + "\f" + para + "\f" + "轴承温度为 70 度。").encode()
    upload(client, project, None, name="dup.txt", data=body)
    res = _search(client, project, query="免责声明 内部参考")
    texts = [r["text"] for r in res["results"]]
    assert texts.count(para) == 1


def test_failed_documents_are_not_searchable(client, loaded_project):
    pid, docs = loaded_project
    res = _search(client, pid, query="现场点检表 扫描件 轴承温度 71")
    assert all(r["document_name"] != "scanned_inspection_sheet.pdf" for r in res["results"])
