"use client";

import { useState } from "react";
import { api } from "@/lib/api";
import type { DocumentInfo, EvidenceTarget, SearchResponse } from "@/lib/types";
import { Badge, Button, EmptyState, ErrorBox, Spinner, locationLabel } from "./ui";

export function SearchPanel({ projectId, docs, onOpen }: { projectId: string; docs: DocumentInfo[]; onOpen: (t: EvidenceTarget) => void }) {
  const [query, setQuery] = useState("");
  const [docIds, setDocIds] = useState<string[]>([]);
  const [pageFrom, setPageFrom] = useState("");
  const [pageTo, setPageTo] = useState("");
  const [topK, setTopK] = useState(8);
  const [busy, setBusy] = useState(false);
  const [err, setErr] = useState<string | null>(null);
  const [res, setRes] = useState<SearchResponse | null>(null);
  const ready = docs.filter((d) => d.status === "ready");

  async function run(e: React.FormEvent) {
    e.preventDefault();
    if (!query.trim()) return;
    setBusy(true);
    setErr(null);
    try {
      setRes(
        await api.search(projectId, {
          query: query.trim(),
          top_k: topK,
          document_ids: docIds.length ? docIds : undefined,
          page_from: pageFrom ? Number(pageFrom) : undefined,
          page_to: pageTo ? Number(pageTo) : undefined,
        }),
      );
    } catch (e) {
      setErr((e as Error).message);
    } finally {
      setBusy(false);
    }
  }

  return (
    <div className="flex h-full min-h-0 flex-col">
      <form onSubmit={run} className="space-y-2 border-b border-slate-200 pb-3">
        <div className="flex gap-2">
          <input value={query} onChange={(e) => setQuery(e.target.value)} placeholder="关键词或自然语言查询" aria-label="检索查询"
            className="min-w-0 flex-1 rounded-md border border-slate-300 px-3 py-1.5 text-sm" />
          <Button type="submit" disabled={busy || !query.trim()} data-testid="search-button">{busy ? <Spinner /> : "检索"}</Button>
        </div>
        <div className="flex flex-wrap items-center gap-3 text-xs text-slate-600">
          <label className="flex items-center gap-1">
            文档
            <select multiple value={docIds} onChange={(e) => setDocIds(Array.from(e.target.selectedOptions).map((o) => o.value))}
              aria-label="按文档过滤" className="max-w-56 rounded border border-slate-300 bg-white text-xs" size={Math.min(3, Math.max(ready.length, 1))}>
              {ready.map((d) => <option key={d.id} value={d.id}>{d.filename}</option>)}
            </select>
          </label>
          <label className="flex items-center gap-1">页码
            <input type="number" min={1} value={pageFrom} onChange={(e) => setPageFrom(e.target.value)} aria-label="起始页" className="w-14 rounded border border-slate-300 px-1 py-0.5" />
            –
            <input type="number" min={1} value={pageTo} onChange={(e) => setPageTo(e.target.value)} aria-label="结束页" className="w-14 rounded border border-slate-300 px-1 py-0.5" />
          </label>
          <label className="flex items-center gap-1">Top-K
            <input type="number" min={1} max={50} value={topK} onChange={(e) => setTopK(Number(e.target.value) || 8)} className="w-14 rounded border border-slate-300 px-1 py-0.5" />
          </label>
          {docIds.length > 0 && <button type="button" className="text-indigo-700 underline" onClick={() => setDocIds([])}>清除文档过滤</button>}
        </div>
      </form>
      {err && <div className="mt-2"><ErrorBox message={err} onDismiss={() => setErr(null)} /></div>}
      <div className="min-h-0 flex-1 overflow-y-auto py-3">
        {!res && !busy && <EmptyState title="混合检索：关键词（全文索引）+ 向量相似度" hint="结果展示两路排名、词项覆盖率以及是否达到证据阈值" />}
        {res && (
          <div className="space-y-2" data-testid="search-results">
            <p className="text-xs text-slate-500">
              查询词项：{res.terms.join(" / ") || "（无）"} · 候选：关键词 {String(res.params.keyword_candidates)} / 向量 {String(res.params.vector_candidates)} ·
              {res.sufficient ? <Badge tone="green">存在达标证据</Badge> : <Badge tone="slate">无达标证据</Badge>}
            </p>
            {res.results.length === 0 && <EmptyState title="没有找到结果" />}
            {res.results.map((r, i) => (
              <button key={r.chunk_id} onClick={() => onOpen({ kind: "chunk", id: r.chunk_id, label: `#${i + 1}` })}
                className="block w-full rounded-md border border-slate-200 bg-white p-3 text-left hover:border-indigo-300" data-testid="search-result">
                <div className="flex flex-wrap items-center gap-1.5 text-xs">
                  <span className="font-semibold text-slate-800">#{i + 1} {r.document_name}</span>
                  <span className="text-slate-500">{locationLabel(r.page_number, r.line_start, r.line_end, r.page_mode)}</span>
                  {r.section_title && <span className="text-slate-400">§ {r.section_title}</span>}
                  {r.relevance.passes_threshold ? <Badge tone="green">达到证据阈值</Badge> : <Badge tone="slate">未达阈值</Badge>}
                </div>
                <p className="mt-1 line-clamp-4 whitespace-pre-wrap text-sm text-slate-700">{r.text}</p>
                <p className="mt-1 text-[11px] text-slate-500">
                  综合 {r.relevance.score.toFixed(3)} · 关键词排名 {r.relevance.keyword_rank ?? "—"} · 向量排名 {r.relevance.vector_rank ?? "—"}
                  （相似度 {r.relevance.vector_similarity?.toFixed(3) ?? "—"}）· IDF 加权覆盖率 {(r.relevance.term_coverage * 100).toFixed(0)}%
                  {r.relevance.matched_terms.length > 0 && <> · 命中：{r.relevance.matched_terms.join(" ")}</>}
                </p>
              </button>
            ))}
          </div>
        )}
      </div>
    </div>
  );
}
