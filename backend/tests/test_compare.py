from app.services.llm import set_llm
from tests.conftest import ScriptedLLM

Q = "比较这些文档对 KX-200 轴承过热根本原因的解释"


def test_compare_without_llm_returns_per_document_evidence(client, loaded_project):
    pid, docs = loaded_project
    r = client.post(f"/api/projects/{pid}/compare", json={"question": Q})
    assert r.status_code == 200, r.text
    m = r.json()
    assert m["kind"] == "comparison" and m["status"] == "llm_unavailable"
    per_doc = {d["document_name"]: d for d in m["payload"]["documents"]}
    assert "scanned_inspection_sheet.pdf" not in per_doc  # not ready -> not compared
    assert per_doc["kx200_revised_report_2024.pdf"]["has_evidence"]
    assert per_doc["maintenance_team_memo.md"]["has_evidence"]
    # documents are ordered by publication date
    dates = [d["published_date"] for d in m["payload"]["documents"] if d["published_date"]]
    assert dates == sorted(dates)
    labels = {e["label"] for e in m["payload"]["evidence"]}
    for d in per_doc.values():
        assert set(d["evidence_ids"]) <= labels


def test_compare_requires_two_documents(client, project, corpus_dir):
    from tests.conftest import upload

    upload(client, project, corpus_dir / "maintenance_team_memo.md")
    r = client.post(f"/api/projects/{project}/compare", json={"question": Q})
    assert r.status_code == 400 and "至少需要 2 份" in r.json()["detail"]


def test_compare_validates_model_output(client, loaded_project):
    pid, docs = loaded_project

    def respond(user):
        # find evidence labels per doc from the prompt to build a realistic answer
        import re

        blocks = re.findall(r'<evidence id="(E\d+)" document="([^"]+)" page="\d+" doc="(D\d+)"', user)
        by_doc = {}
        for lab, name, d in blocks:
            by_doc.setdefault(name, []).append((lab, d))
        rev = by_doc["kx200_revised_report_2024.pdf"][0]
        memo = by_doc["maintenance_team_memo.md"][0]
        init = by_doc["kx200_incident_report_2023.pdf"][0]
        return {
            "summary": "各文档对根本原因的解释不同。",
            "dimensions": [{"name": "根本原因", "description": "故障根本原因"}],
            "document_positions": [
                {"doc": rev[1], "dimension": "根本原因", "conclusion": "安装不对中", "evidence_ids": [rev[0]], "quote": ""},
                {"doc": memo[1], "dimension": "根本原因", "conclusion": "批次材料缺陷", "evidence_ids": [rev[0]], "quote": ""},
                {"doc": "D99", "dimension": "根本原因", "conclusion": "x", "evidence_ids": [], "quote": ""},
            ],
            "agreements": [{"statement": "都发生了过热", "evidence_ids": [rev[0], init[0]]}],
            "differences": [
                {"statement": "材料是否有缺陷", "category": "contradiction", "explanation": "", "evidence_ids": [rev[0], memo[0]]},
                {"statement": "原因从润滑变为对中", "category": "temporal_change", "explanation": "", "evidence_ids": [init[0], rev[0]]},
                {"statement": "单方面矛盾", "category": "contradiction", "explanation": "", "evidence_ids": [memo[0]]},
                {"statement": "无依据", "category": "supplementary", "explanation": "", "evidence_ids": ["E404"]},
            ],
            "possible_reasons": [{"statement": "班组未看到实验室检验", "type": "inference", "evidence_ids": []}],
            "undetermined": [{"question": "B-2207 其他轴承", "reason": "无检验数据"}],
        }

    set_llm(ScriptedLLM(respond))
    m = client.post(f"/api/projects/{pid}/compare", json={"question": Q}).json()
    p = m["payload"]
    assert m["status"] == "answered"
    assert len(p["document_positions"]) == 2  # D99 dropped
    memo_pos = p["document_positions"][1]
    assert memo_pos["evidence_ids"] == [] and memo_pos["supported"] is False  # cross-doc evidence removed
    contra, temporal, single, nosrc = p["differences"]
    assert contra["category_label"].startswith("A.") and "needs_review" not in contra
    assert temporal["category_label"].startswith("B.")
    assert single.get("needs_review") is True
    assert nosrc["supported"] is False and "E404" in p["validation"]["invalid_citation_ids"]
    assert p["possible_reasons"][0]["supported"] is False  # inference w/o evidence is allowed but flagged
    assert any("D99" in w for w in p["validation"]["warnings"])
