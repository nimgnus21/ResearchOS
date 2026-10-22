"""Run the fixed evaluation set and write eval/results/eval_report.{md,json}.

Measures (offline, no model required):
  * retrieval recall@k   – an expected (document, page) appears in the top-k results
  * MRR                  – reciprocal rank of the first expected source
  * evidence key-fact hit – the selected evidence contains the expected fact string
  * citation integrity   – every stored citation resolves to a real chunk in the project with the
                           same document/page, and its quote is a substring of the chunk text
  * no-evidence behaviour – unanswerable questions are refused (insufficient_evidence)
  * false refusals        – answerable questions wrongly refused
If an LLM is configured (LLM_PROVIDER/LLM_API_KEY), the generated answers are evaluated too
(citation validity, status); otherwise that section is reported as "not run".

Usage: DATABASE_URL=... python eval/run_eval.py [--k 5]
"""
from __future__ import annotations

import argparse
import json
import os
import sys
import time
from datetime import datetime, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "backend"))
sys.path.insert(0, str(ROOT / "eval" / "corpus"))
os.environ.setdefault("DATABASE_URL", "postgresql+psycopg://postgres:postgres@localhost:5432/researchos_eval")
os.environ["INGEST_SYNC"] = "true"
import tempfile  # noqa: E402

os.environ["STORAGE_DIR"] = tempfile.mkdtemp(prefix="researchos-eval-")


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--k", type=int, default=5)
    args = ap.parse_args()

    from alembic import command
    from alembic.config import Config
    from sqlalchemy import select, text

    import build_corpus
    from app.config import get_settings
    from app.db import session_factory
    from app.models import Citation, Document, DocumentChunk, ResearchProject
    from app.services import ingestion
    from app.services.compare import compare_documents
    from app.services.llm import llm_status
    from app.services.qa import answer_question
    from app.services.retrieval import hybrid_search
    from app.services.text_utils import compact

    s = get_settings()
    cfg = Config(str(ROOT / "backend" / "alembic.ini"))
    cfg.set_main_option("script_location", str(ROOT / "backend" / "alembic"))
    cfg.attributes["database_url"] = s.database_url
    command.upgrade(cfg, "head")

    corpus = ROOT / "eval" / "corpus" / "files"
    build_corpus.OUT = corpus
    build_corpus.build()
    spec = json.loads((ROOT / "eval" / "questions.json").read_text(encoding="utf-8"))

    db = session_factory()
    project = ResearchProject(name=f"eval-{datetime.now(timezone.utc):%Y%m%d%H%M%S}", description="automatic evaluation")
    db.add(project)
    db.commit()
    pid = project.id
    t0 = time.monotonic()
    ingest = {}
    for f in sorted(corpus.iterdir()):
        doc = ingestion.create_document(db, pid, f.name, f.read_bytes())
        ingestion.process_document(doc.id)
        db.expire_all()
        d = db.get(Document, doc.id)
        ingest[f.name] = {"status": d.status, "chunks": d.chunk_count, "pages": d.page_count, "error": d.error_message}
    ingest_s = time.monotonic() - t0

    k = args.k
    rows = []
    for q in spec["answerable"]:
        out = hybrid_search(db, pid, q["question"], top_k=10, save=False)
        ranked = [(r.document_name, r.page_number) for r in out.results]
        expected = {tuple(e) for e in q["expected"]}
        first = next((i + 1 for i, x in enumerate(ranked) if x in expected), None)
        msg = answer_question(db, pid, q["question"])
        ev = msg.payload.get("evidence", [])
        fact_hit = any(all(compact(f) in compact(e["text"]) for f in q["key_facts"]) for e in ev)
        rows.append({
            "id": q["id"], "question": q["question"], "status": msg.status,
            "recall_at_k": first is not None and first <= k, "rank": first,
            "top1": f"{ranked[0][0]} p.{ranked[0][1]}" if ranked else None,
            "evidence_count": len(ev), "key_fact_in_evidence": fact_hit,
            "top1_correct": bool(ranked) and ranked[0] in expected,
        })
    unans = []
    for q in spec["unanswerable"]:
        msg = answer_question(db, pid, q["question"])
        best = msg.payload.get("near_misses", [{}])
        unans.append({"id": q["id"], "question": q["question"], "status": msg.status,
                      "refused": msg.status in ("insufficient_evidence", "insufficient"),
                      "best_coverage": (best[0].get("relevance", {}) or {}).get("term_coverage") if best else None})

    # citation integrity over everything stored for this project
    cits = db.scalars(select(Citation).where(Citation.project_id == pid)).all()
    bad = []
    for c in cits:
        ch = db.get(DocumentChunk, c.chunk_id) if c.chunk_id else None
        doc = db.get(Document, c.document_id) if c.document_id else None
        ok = (ch is not None and doc is not None and ch.project_id == pid and ch.document_id == doc.id
              and ch.page_number == c.page_number and doc.filename == c.document_name
              and compact(c.quote) in compact(ch.text))
        if not ok:
            bad.append(str(c.id))

    comp = compare_documents(db, pid, spec["comparison"]["question"])
    comp_docs = {d["document_name"]: d["has_evidence"] for d in comp.payload["documents"]}
    comp_cov = [n for n in spec["comparison"]["must_include_documents"] if comp_docs.get(n)]

    llm = llm_status()
    llm_section = None
    if llm["configured"]:
        answered = [r for r in rows]
        llm_rows = []
        for q in spec["answerable"] + spec["unanswerable"]:
            m = answer_question(db, pid, q["question"])
            v = (m.payload or {}).get("validation", {})
            llm_rows.append({"id": q["id"], "status": m.status, "invalid_ids": v.get("invalid_citation_ids", []),
                             "unverified_quotes": len(v.get("unverified_quotes", [])),
                             "unsupported": len(v.get("unsupported_statements", []))})
        llm_section = {"model": llm, "rows": llm_rows}

    n = len(rows)
    metrics = {
        f"recall@{k}": sum(r["recall_at_k"] for r in rows) / n,
        "mrr@10": sum(1 / r["rank"] for r in rows if r["rank"]) / n,
        "top1_accuracy": sum(r["top1_correct"] for r in rows) / n,
        "key_fact_in_evidence": sum(r["key_fact_in_evidence"] for r in rows) / n,
        "false_refusal_rate": sum(r["status"] == "insufficient_evidence" for r in rows) / n,
        "unanswerable_refusal_rate": sum(u["refused"] for u in unans) / len(unans),
        "citation_integrity": (len(cits) - len(bad)) / len(cits) if cits else None,
        "citations_checked": len(cits),
        "comparison_doc_coverage": len(comp_cov) / len(spec["comparison"]["must_include_documents"]),
    }
    result = {
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "config": {"embedding": s.embedding_provider, "top_k": s.retrieval_top_k,
                   "min_term_coverage": s.retrieval_min_term_coverage, "min_vector_sim": s.retrieval_min_vector_sim,
                   "chunk_target_chars": s.chunk_target_chars, "chunk_overlap_chars": s.chunk_overlap_chars},
        "ingestion": ingest, "ingestion_seconds": round(ingest_s, 2),
        "metrics": metrics, "answerable": rows, "unanswerable": unans,
        "comparison": {"status": comp.status, "documents_with_evidence": comp_docs},
        "bad_citations": bad, "llm": llm_section or {"run": False, "reason": llm.get("reason")},
    }
    out_dir = ROOT / "eval" / "results"
    out_dir.mkdir(parents=True, exist_ok=True)
    (out_dir / "eval_report.json").write_text(json.dumps(result, ensure_ascii=False, indent=2), encoding="utf-8")
    (out_dir / "eval_report.md").write_text(render_md(result, k), encoding="utf-8")

    db.close()
    with session_factory() as db2:  # clean up the eval project
        for d in db2.scalars(select(Document).where(Document.project_id == pid)).all():
            ingestion.delete_document(db2, d)
        db2.execute(text("DELETE FROM research_projects WHERE id = :p"), {"p": pid})
        db2.commit()
    import shutil

    shutil.rmtree(os.environ["STORAGE_DIR"], ignore_errors=True)
    print(render_md(result, k))


def pct(x):
    return "n/a" if x is None else f"{x * 100:.1f}%"


def render_md(r: dict, k: int) -> str:
    m = r["metrics"]
    L = [
        "# ResearchOS 评估报告", "",
        f"生成时间：{r['generated_at']}  ",
        f"配置：embedding=`{r['config']['embedding']}`，min_term_coverage={r['config']['min_term_coverage']}，"
        f"min_vector_sim={r['config']['min_vector_sim']}，chunk={r['config']['chunk_target_chars']}/{r['config']['chunk_overlap_chars']}", "",
        "## 指标汇总", "",
        "| 指标 | 结果 |", "|---|---|",
        f"| 检索召回率 recall@{k} | {pct(m[f'recall@{k}'])} |",
        f"| MRR@10 | {m['mrr@10']:.3f} |",
        f"| Top-1 来源准确率 | {pct(m['top1_accuracy'])} |",
        f"| 关键事实出现在所选证据中 | {pct(m['key_fact_in_evidence'])} |",
        f"| 引用完整性（引用→真实文档/页码/原文） | {pct(m['citation_integrity'])}（检查 {m['citations_checked']} 条） |",
        f"| 无答案问题的拒答率 | {pct(m['unanswerable_refusal_rate'])} |",
        f"| 可回答问题被误拒率 | {pct(m['false_refusal_rate'])} |",
        f"| 比较功能文档覆盖率 | {pct(m['comparison_doc_coverage'])} |", "",
        "## 文档处理", "", "| 文件 | 状态 | 页数 | 分块 | 说明 |", "|---|---|---|---|---|",
    ]
    for name, d in r["ingestion"].items():
        L.append(f"| {name} | {d['status']} | {d['pages'] or '-'} | {d['chunks']} | {(d['error'] or '').replace('|', '/')} |")
    L += ["", "## 可回答问题", "", "| ID | 问题 | 首个正确来源排名 | Top-1 | 关键事实命中 | 状态 |", "|---|---|---|---|---|---|"]
    for x in r["answerable"]:
        L.append(f"| {x['id']} | {x['question']} | {x['rank'] or '未召回'} | {x['top1']} | {'✅' if x['key_fact_in_evidence'] else '❌'} | {x['status']} |")
    L += ["", "## 无法回答的问题", "", "| ID | 问题 | 状态 | 是否拒答 | 最佳候选覆盖率 |", "|---|---|---|---|---|"]
    for x in r["unanswerable"]:
        L.append(f"| {x['id']} | {x['question']} | {x['status']} | {'✅' if x['refused'] else '❌'} | {x['best_coverage']} |")
    L += ["", "## 跨文档比较", "", f"状态：`{r['comparison']['status']}`", ""]
    for name, has in r["comparison"]["documents_with_evidence"].items():
        L.append(f"- {name}：{'有相关证据' if has else '无相关证据'}")
    L += ["", "## 大模型回答评估", ""]
    if r["llm"].get("rows"):
        L += [f"模型：{r['llm']['model']}", "", "| ID | 状态 | 无效引用 | 未验证引文 | 无依据陈述 |", "|---|---|---|---|---|"]
        for x in r["llm"]["rows"]:
            L.append(f"| {x['id']} | {x['status']} | {', '.join(x['invalid_ids']) or '-'} | {x['unverified_quotes']} | {x['unsupported']} |")
    else:
        L.append(f"未运行：{r['llm'].get('reason')}。以上指标均不依赖模型；配置 LLM_PROVIDER 与 LLM_API_KEY 后重新运行可评估生成回答。")
    L += ["", "> 注：", "> - 默认 embedding 为离线哈希词法向量（非神经语义模型），语义/跨语言召回能力有限（例如英文现场笔记无法被中文比较问题召回）。",
          "> - 语料与问题均由开发者编写，规模很小；检索规则（IDF 加权覆盖率、跨词二元组过滤、上下文块头）曾针对本评估暴露的失败做过修正，因此指标存在乐观偏差，不代表在真实资料上的表现。", ""]
    return "\n".join(L)


if __name__ == "__main__":
    main()
