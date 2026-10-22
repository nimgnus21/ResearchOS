"use client";

import { useCallback, useEffect, useState } from "react";
import ReactMarkdown from "react-markdown";
import remarkGfm from "remark-gfm";
import { api } from "@/lib/api";
import type { EvidenceTarget, Report } from "@/lib/types";
import { Badge, Button, CitationChip, EmptyState, ErrorBox, Spinner, cx } from "./ui";

function linkCitations(md: string) {
  return md.replace(/\[(E\d+)\](?!\()/g, "[$1](#cite-$1)");
}

export function ReportPanel({ projectId, readyCount, onOpen, onActivity }: { projectId: string; readyCount: number; onOpen: (t: EvidenceTarget) => void; onActivity?: () => void }) {
  const [reports, setReports] = useState<Report[]>([]);
  const [current, setCurrent] = useState<Report | null>(null);
  const [draft, setDraft] = useState("");
  const [mode, setMode] = useState<"preview" | "edit">("preview");
  const [question, setQuestion] = useState("");
  const [title, setTitle] = useState("");
  const [loading, setLoading] = useState(true);
  const [busy, setBusy] = useState<"" | "generate" | "save">("");
  const [err, setErr] = useState<string | null>(null);
  const [saved, setSaved] = useState(false);

  const load = useCallback(async () => {
    setLoading(true);
    try {
      setReports(await api.reports(projectId));
    } catch (e) {
      setErr((e as Error).message);
    } finally {
      setLoading(false);
    }
  }, [projectId]);

  useEffect(() => {
    setCurrent(null);
    load();
  }, [projectId, load]);

  function select(r: Report | null) {
    setCurrent(r);
    setDraft(r?.content_md ?? "");
    setMode("preview");
    setSaved(false);
  }

  async function generate(e: React.FormEvent) {
    e.preventDefault();
    setBusy("generate");
    setErr(null);
    try {
      const r = await api.createReport(projectId, question.trim(), title.trim() || undefined);
      setQuestion("");
      setTitle("");
      await load();
      select(r);
      onActivity?.();
    } catch (e) {
      setErr((e as Error).message);
    } finally {
      setBusy("");
    }
  }

  async function save() {
    if (!current) return;
    setBusy("save");
    setErr(null);
    try {
      const r = await api.updateReport(projectId, current.id, { content_md: draft });
      setCurrent(r);
      setSaved(true);
      load();
    } catch (e) {
      setErr((e as Error).message);
    } finally {
      setBusy("");
    }
  }

  const dirty = current ? draft !== current.content_md : false;

  return (
    <div className="flex h-full min-h-0 flex-col">
      <form onSubmit={generate} className="space-y-2 border-b border-slate-200 pb-3">
        <div className="flex flex-col gap-2 sm:flex-row">
          <input value={question} onChange={(e) => setQuestion(e.target.value)} placeholder="研究问题（报告将基于检索证据生成）" aria-label="报告研究问题"
            className="min-w-0 flex-1 rounded-md border border-slate-300 px-3 py-1.5 text-sm" />
          <input value={title} onChange={(e) => setTitle(e.target.value)} placeholder="报告标题（可选）" aria-label="报告标题"
            className="rounded-md border border-slate-300 px-3 py-1.5 text-sm sm:w-48" />
          <Button type="submit" disabled={!!busy || !question.trim() || readyCount === 0} data-testid="generate-report">
            {busy === "generate" ? <Spinner /> : null} 生成报告
          </Button>
        </div>
        <div className="flex flex-wrap items-center gap-2">
          <select aria-label="选择报告" value={current?.id ?? ""} onChange={(e) => select(reports.find((r) => r.id === e.target.value) ?? null)}
            className="min-w-0 max-w-full flex-1 rounded border border-slate-300 bg-white px-2 py-1 text-sm">
            <option value="">{loading ? "加载中…" : reports.length ? `选择已有报告（${reports.length}）` : "暂无报告"}</option>
            {reports.map((r) => <option key={r.id} value={r.id}>{r.title}</option>)}
          </select>
        </div>
      </form>
      {err && <div className="mt-2"><ErrorBox message={err} onDismiss={() => setErr(null)} /></div>}

      {busy === "generate" && <div className="mt-3 flex items-center gap-2 text-sm text-slate-500"><Spinner /> 正在检索证据并生成报告…</div>}
      {!current && busy !== "generate" && (
        <div className="mt-3"><EmptyState title="研究报告" hint="输入研究问题生成 Markdown 报告，可预览、编辑并下载" /></div>
      )}
      {current && (
        <div className="mt-3 flex min-h-0 flex-1 flex-col">
          <div className="mb-2 flex flex-wrap items-center gap-2">
            <Badge tone={current.generation_mode === "llm" ? "green" : "amber"}>
              {current.generation_mode === "llm" ? "模型综合 + 系统校验引用" : "证据汇编（未使用模型）"}
            </Badge>
            <div className="ml-auto flex flex-wrap gap-1">
              <div className="inline-flex rounded-md ring-1 ring-slate-300" role="tablist">
                {(["preview", "edit"] as const).map((m) => (
                  <button key={m} role="tab" aria-selected={mode === m} onClick={() => setMode(m)}
                    className={cx("px-2.5 py-1 text-xs", mode === m ? "bg-slate-800 text-white" : "bg-white text-slate-600", m === "preview" ? "rounded-l-md" : "rounded-r-md")}>
                    {m === "preview" ? "预览" : "编辑"}
                  </button>
                ))}
              </div>
              <Button size="sm" onClick={save} disabled={!dirty || busy === "save"} data-testid="save-report">
                {busy === "save" ? <Spinner /> : null} 保存
              </Button>
              <a href={api.exportUrl(projectId, current.id)} download className={cx("inline-flex items-center rounded-md px-2 py-1 text-xs font-medium ring-1",
                dirty ? "pointer-events-none text-slate-400 ring-slate-200" : "bg-white text-slate-700 ring-slate-300 hover:bg-slate-50")}
                title={dirty ? "请先保存修改" : "下载 Markdown"} data-testid="download-report">
                下载 .md
              </a>
              <Button size="sm" variant="danger" onClick={async () => {
                if (!confirm("删除该报告？")) return;
                try { await api.deleteReport(projectId, current.id); select(null); load(); onActivity?.(); } catch (e) { setErr((e as Error).message); }
              }}>删除</Button>
            </div>
          </div>
          {saved && !dirty && <p className="mb-1 text-xs text-emerald-700">已保存</p>}
          {dirty && <p className="mb-1 text-xs text-amber-700">有未保存的修改</p>}
          <div className="min-h-0 flex-1 overflow-y-auto">
            {mode === "edit" ? (
              <textarea value={draft} onChange={(e) => setDraft(e.target.value)} aria-label="报告 Markdown 编辑器" data-testid="report-editor"
                className="h-full min-h-[50vh] w-full rounded-md border border-slate-300 p-3 font-mono text-[13px] leading-relaxed" />
            ) : (
              <article className="prose prose-sm prose-slate max-w-none rounded-md border border-slate-200 bg-white p-4" data-testid="report-preview">
                <ReactMarkdown
                  remarkPlugins={[remarkGfm]}
                  components={{
                    a: ({ href, children }) => {
                      if (href?.startsWith("#cite-")) {
                        const label = href.slice(6);
                        const src = current.sources.find((s) => s.label === label);
                        return <CitationChip label={label} invalid={!src} onClick={src ? () => onOpen({ kind: "chunk", id: src.chunk_id, label }) : undefined} />;
                      }
                      return <a href={href} target="_blank" rel="noreferrer">{children}</a>;
                    },
                  }}
                >
                  {linkCitations(draft)}
                </ReactMarkdown>
              </article>
            )}
          </div>
        </div>
      )}
    </div>
  );
}
