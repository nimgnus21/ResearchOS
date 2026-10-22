"use client";

import { useEffect, useRef, useState } from "react";
import { api } from "@/lib/api";
import type { CitationView, DocumentInfo, EvidenceTarget, SourceView } from "@/lib/types";
import { Badge, Button, EmptyState, ErrorBox, Notice, SectionTitle, Spinner, formatBytes, locationLabel } from "./ui";

type State =
  | { status: "idle" }
  | { status: "loading" }
  | { status: "error"; message: string }
  | { status: "ok"; citation?: CitationView["citation"]; source: SourceView | null; notice?: string | null };

export function EvidencePanel({
  projectId,
  target,
  doc,
  onDocUpdated,
}: {
  projectId: string | null;
  target: EvidenceTarget | null;
  doc: DocumentInfo | null;
  onDocUpdated: () => void;
}) {
  const [state, setState] = useState<State>({ status: "idle" });
  const hl = useRef<HTMLElement>(null);

  useEffect(() => {
    if (!projectId || !target) {
      setState({ status: "idle" });
      return;
    }
    let cancelled = false;
    setState({ status: "loading" });
    const load = async () => {
      try {
        if (target.kind === "citation") {
          const c = await api.citation(projectId, target.id);
          if (!cancelled) setState({ status: "ok", citation: c.citation, source: c.source, notice: c.notice });
        } else {
          const s = await api.chunk(projectId, target.id);
          if (!cancelled) setState({ status: "ok", source: s });
        }
      } catch (e) {
        if (!cancelled) setState({ status: "error", message: (e as Error).message });
      }
    };
    load();
    return () => {
      cancelled = true;
    };
  }, [projectId, target]);

  useEffect(() => {
    hl.current?.scrollIntoView({ block: "center", behavior: "smooth" });
  }, [state]);

  if (!projectId) return <EmptyState title="选择一个研究项目" />;

  return (
    <div className="space-y-3" data-testid="evidence-panel">
      <SectionTitle>引用证据</SectionTitle>
      {state.status === "idle" && !doc && <EmptyState title="点击回答中的引用编号查看原文" hint="会显示来源文档、页码和高亮的原文片段" />}
      {state.status === "loading" && (
        <div className="flex items-center gap-2 text-sm text-slate-500">
          <Spinner /> 加载原文…
        </div>
      )}
      {state.status === "error" && <ErrorBox message={state.message} />}
      {state.status === "ok" && <SourceDetails label={target?.label} state={state} hlRef={hl} />}
      {doc && state.status === "idle" && <DocDetails projectId={projectId} doc={doc} onUpdated={onDocUpdated} />}
    </div>
  );
}

function SourceDetails({
  label,
  state,
  hlRef,
}: {
  label?: string;
  state: Extract<State, { status: "ok" }>;
  hlRef: React.RefObject<HTMLElement | null>;
}) {
  const { citation, source, notice } = state;
  if (!source) {
    return (
      <div className="space-y-2" data-testid="evidence-snapshot">
        <Notice>{notice ?? "原文不可用"}</Notice>
        {citation && (
          <div className="rounded-md border border-slate-200 bg-white p-3 text-sm">
            <p className="font-medium">《{citation.document_name}》 第 {citation.page_number} 页</p>
            <blockquote className="mt-2 border-l-2 border-slate-300 pl-2 text-slate-600">{citation.quote}</blockquote>
          </div>
        )}
      </div>
    );
  }
  const { chunk, document: d, page_text } = source;
  const before = page_text ? page_text.slice(0, chunk.char_start) : "";
  const mid = page_text ? page_text.slice(chunk.char_start, chunk.char_end) : chunk.text;
  const after = page_text ? page_text.slice(chunk.char_end) : "";
  return (
    <div className="space-y-3">
      <div className="rounded-md border border-slate-200 bg-white p-3 text-sm">
        <div className="flex flex-wrap items-center gap-1.5">
          {label && <Badge tone="indigo">{label}</Badge>}
          <span className="font-semibold text-slate-800" data-testid="evidence-doc-name">{d.filename}</span>
        </div>
        <p className="mt-1 text-xs text-slate-600" data-testid="evidence-location">
          {locationLabel(chunk.page_number, chunk.line_start, chunk.line_end, d.page_mode)}
          {chunk.section_title && <> · § {chunk.section_title}</>}
        </p>
        <dl className="mt-2 grid grid-cols-[auto_1fr] gap-x-2 gap-y-0.5 text-xs text-slate-600">
          {d.title && (<><dt className="text-slate-400">标题</dt><dd className="truncate">{d.title}</dd></>)}
          <dt className="text-slate-400">发布日期</dt>
          <dd>{d.published_date ?? "未知"}</dd>
          <dt className="text-slate-400">页数</dt>
          <dd>{d.page_count}（{pageModeLabel(d.page_mode)}）</dd>
        </dl>
        {citation && (
          <div className="mt-2 flex flex-wrap gap-1">
            {citation.quote_verified ? <Badge tone="green">引文已逐字核对</Badge> : <Badge tone="slate">显示检索片段</Badge>}
          </div>
        )}
        <div className="mt-2 flex flex-wrap gap-2">
          {source.pdf_page_url ? (
            <a className="text-xs font-medium text-indigo-700 underline" href={source.pdf_page_url} target="_blank" rel="noreferrer" data-testid="open-pdf-page">
              打开原始 PDF 第 {chunk.page_number} 页 ↗
            </a>
          ) : (
            <a className="text-xs font-medium text-indigo-700 underline" href={source.file_url} target="_blank" rel="noreferrer">
              {d.file_type === "docx" ? "下载原始文件" : "打开原始文件"} ↗
            </a>
          )}
        </div>
      </div>
      {citation && citation.quote_verified && (
        <blockquote className="border-l-4 border-amber-400 bg-amber-50 px-3 py-2 text-sm text-slate-800">“{citation.quote}”</blockquote>
      )}
      <div>
        <p className="mb-1 text-xs text-slate-500">第 {chunk.page_number} 页原文（高亮为引用片段）</p>
        <div className="max-h-[55vh] overflow-y-auto whitespace-pre-wrap break-words rounded-md border border-slate-200 bg-white p-3 text-[13px] leading-relaxed text-slate-700" data-testid="page-text">
          {source.page_text_truncated?.before && <span className="text-slate-400">［……前文省略……］{"\n"}</span>}
          {before}
          <mark ref={hlRef as React.RefObject<HTMLElement>} className="evidence-hl" data-testid="highlight">
            {mid}
          </mark>
          {after}
          {source.page_text_truncated?.after && <span className="text-slate-400">{"\n"}［……后文省略……］</span>}
        </div>
      </div>
    </div>
  );
}

function pageModeLabel(m: string | null) {
  return (
    {
      physical: "PDF 物理页",
      explicit_breaks: "按分页符划分的逻辑页",
      rendered_breaks: "按 Word 渲染分页的逻辑页",
      form_feed: "按换页符划分",
      none: "无分页，按行号定位",
    }[m ?? ""] ?? "未知"
  );
}

function DocDetails({ projectId, doc, onUpdated }: { projectId: string; doc: DocumentInfo; onUpdated: () => void }) {
  const [date, setDate] = useState(doc.published_date ?? "");
  const [busy, setBusy] = useState(false);
  const [err, setErr] = useState<string | null>(null);
  useEffect(() => setDate(doc.published_date ?? ""), [doc]);
  const warnings = doc.metadata?.warnings ?? [];
  return (
    <div className="space-y-2 rounded-md border border-slate-200 bg-white p-3 text-sm" data-testid="doc-details">
      <p className="font-semibold">{doc.filename}</p>
      <dl className="grid grid-cols-[auto_1fr] gap-x-2 gap-y-0.5 text-xs text-slate-600">
        <dt className="text-slate-400">状态</dt><dd>{doc.status}</dd>
        <dt className="text-slate-400">标题</dt><dd>{doc.title ?? "—"}</dd>
        <dt className="text-slate-400">作者</dt><dd>{doc.author ?? "—"}</dd>
        <dt className="text-slate-400">大小</dt><dd>{formatBytes(doc.size_bytes)}</dd>
        <dt className="text-slate-400">页数</dt><dd>{doc.page_count ?? "—"}（{pageModeLabel(doc.page_mode)}）</dd>
        <dt className="text-slate-400">分块</dt><dd>{doc.chunk_count}</dd>
        <dt className="text-slate-400">处理次数</dt><dd>{doc.attempts}</dd>
        <dt className="text-slate-400">SHA-256</dt><dd className="truncate font-mono" title={doc.content_hash}>{doc.content_hash.slice(0, 16)}…</dd>
        <dt className="text-slate-400">日期来源</dt><dd>{String(doc.metadata?.published_date_source ?? "—")}</dd>
      </dl>
      {warnings.length > 0 && <Notice>{warnings.join("；")}</Notice>}
      <form
        className="flex items-end gap-2"
        onSubmit={async (e) => {
          e.preventDefault();
          setBusy(true);
          setErr(null);
          try {
            await api.updateDocument(projectId, doc.id, { published_date: date || null });
            onUpdated();
          } catch (e) {
            setErr((e as Error).message);
          } finally {
            setBusy(false);
          }
        }}
      >
        <label className="text-xs text-slate-600">
          发布日期（用于判断时间变化）
          <input type="date" value={date} onChange={(e) => setDate(e.target.value)} className="mt-0.5 block rounded border border-slate-300 px-2 py-1 text-sm" />
        </label>
        <Button size="sm" variant="secondary" type="submit" disabled={busy}>保存</Button>
      </form>
      {err && <ErrorBox message={err} />}
      <a className="text-xs font-medium text-indigo-700 underline" href={`/api/projects/${projectId}/documents/${doc.id}/file`} target="_blank" rel="noreferrer">
        打开原始文件 ↗
      </a>
    </div>
  );
}
