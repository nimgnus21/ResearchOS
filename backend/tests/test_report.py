"""10. Report generation, editing and export."""
from app.services.llm import set_llm
from tests.conftest import ScriptedLLM

SECTIONS = ["## 研究问题", "## 执行摘要", "## 主要发现", "## 跨文档比较", "## 不确定性和限制", "## 待进一步调查的问题", "## 引用来源清单"]


def test_evidence_only_report_edit_and_export(client, loaded_project):
    pid, _ = loaded_project
    r = client.post(f"/api/projects/{pid}/reports", json={"question": "KX-200 轴承过热的根本原因是什么？"})
    assert r.status_code == 201, r.text
    rep = r.json()
    assert rep["generation_mode"] == "evidence_only"
    md = rep["content_md"]
    for s in SECTIONS:
        assert s in md
    assert "未配置大模型" in md
    assert rep["sources"] and all(s["page_number"] >= 1 for s in rep["sources"])
    for s in rep["sources"]:
        assert f"[{s['label']}]" in md and s["document_name"] in md

    edited = md.replace("_（待撰写）_", "人工撰写的摘要：安装不对中是根本原因。", 1)
    r = client.put(f"/api/projects/{pid}/reports/{rep['id']}", json={"content_md": edited, "title": "修订后的标题"})
    assert r.status_code == 200 and r.json()["title"] == "修订后的标题"

    exp = client.get(f"/api/projects/{pid}/reports/{rep['id']}/export")
    assert exp.status_code == 200
    assert exp.headers["content-type"].startswith("text/markdown")
    assert "attachment" in exp.headers["content-disposition"]
    assert exp.content.decode("utf-8") == edited
    assert client.get(f"/api/projects/{pid}/reports/{rep['id']}/export?format=pdf").status_code == 400
    assert len(client.get(f"/api/projects/{pid}/reports").json()) == 1


def test_report_for_unanswerable_question(client, loaded_project):
    pid, _ = loaded_project
    rep = client.post(f"/api/projects/{pid}/reports", json={"question": "KX-200 的采购价格和保修期是多少？"}).json()
    assert "无法支持该研究问题" in rep["content_md"]
    assert rep["sources"] == []


def test_llm_report_renders_only_validated_citations(client, loaded_project):
    pid, _ = loaded_project

    def respond(user):
        return {
            "title": "KX-200 轴承过热根因研究",
            "executive_summary": [{"text": "修订报告认定根因为安装不对中。", "type": "fact", "evidence_ids": ["E1"]}],
            "key_findings": [
                {"text": "真实发现", "type": "fact", "evidence_ids": ["E1", "E2"]},
                {"text": "编造发现", "type": "fact", "evidence_ids": ["E999"]},
            ],
            "comparison": [{"text": "初步报告与修订报告结论不同", "category": "temporal_change", "evidence_ids": ["E2"]}],
            "uncertainties": ["批次轴承的检验数据不足"],
            "further_questions": ["B-2207 批次其他轴承是否也合格？"],
        }

    set_llm(ScriptedLLM(respond))
    rep = client.post(f"/api/projects/{pid}/reports", json={"question": "KX-200 轴承过热的根本原因是什么？"}).json()
    md = rep["content_md"]
    assert rep["generation_mode"] == "llm"
    for s in SECTIONS:
        assert s in md
    assert "E999" not in md.split("## 引用来源清单")[1]
    assert "**[未经证实]** 编造发现 *（无有效引用）*" in md
    assert "1 个无效引用编号已被移除" in md
    assert "B. 发布时间不同导致的信息变化" in md
    assert [s["label"] for s in rep["sources"]] == ["E1", "E2"]
