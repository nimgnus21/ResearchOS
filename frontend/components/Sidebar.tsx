"use client";

import { useRef, useState } from "react";
import { api } from "@/lib/api";
import type { DocumentInfo, DocStatus, Project, UploadResult } from "@/lib/types";
import { Badge, Button, EmptyState, ErrorBox, SectionTitle, Spinner, cx, formatBytes } from "./ui";

const STATUS: Record<DocStatus, { label: string; tone: "slate" | "blue" | "green" | "red" | "amber" }> = {
  pending: { label: "排队中", tone: "slate" },
  processing: { label: "处理中", tone: "blue" },
  ready: { label: "已就绪", tone: "green" },
  failed: { label: "失败", tone: "red" },
  needs_ocr: { label: "需要 OCR", tone: "amber" },
};

export function ProjectList({
  projects,
  loading,
  error,
  selectedId,
  onSelect,
  onChanged,
}: {
  projects: Project[];
  loading: boolean;
  error: string | null;
  selectedId: string | null;
  onSelect: (id: string | null) => void;
  onChanged: (selectId?: string | null) => void;
}) {
  const [creating, setCreating] = useState(false);
  const [name, setName] = useState("");
  const [desc, setDesc] = useState("");
  const [busy, setBusy] = useState(false);
  const [err, setErr] = useState<string | null>(null);

  async function create(e: React.FormEvent) {
    e.preventDefault();
    if (!name.trim()) return;
    setBusy(true);
    setErr(null);
    try {
      const p = await api.createProject(name.trim(), desc.trim());
      setName("");
      setDesc("");
      setCreating(false);
      onChanged(p.id);
    } catch (e) {
      setErr((e as Error).message);
    } finally {
      setBusy(false);
    }
  }

  async function remove(p: Project) {
    if (!confirm(`确定删除项目“${p.name}”？其中的文档、对话和报告将被永久删除。`)) return;
    try {
      await api.deleteProject(p.id);
      onChanged(selectedId === p.id ? null : selectedId);
    } catch (e) {
      setErr((e as Error).message);
    }
  }

  return (
    <section aria-label="研究项目">
      <SectionTitle
        right={
          <Button size="sm" variant="ghost" onClick={() => setCreating((v) => !v)} data-testid="new-project-toggle">
            {creating ? "取消" : "+ 新建"}
          </Button>
        }
      >
        研究项目
      </SectionTitle>
      {creating && (
        <form onSubmit={create} className="mb-3 space-y-2 rounded-md border border-slate-200 bg-white p-2">
          <input
            autoFocus
            required
            maxLength={200}
            value={name}
            onChange={(e) => setName(e.target.value)}
            placeholder="项目名称"
            aria-label="项目名称"
            className="w-full rounded border border-slate-300 px-2 py-1 text-sm"
          />
          <textarea
            value={desc}
            onChange={(e) => setDesc(e.target.value)}
            placeholder="描述（可选）"
            aria-label="项目描述"
            rows={2}
            className="w-full rounded border border-slate-300 px-2 py-1 text-sm"
          />
          <Button type="submit" size="sm" disabled={busy || !name.trim()} className="w-full">
            {busy ? <Spinner /> : null} 创建项目
          </Button>
        </form>
      )}
      {err && <ErrorBox message={err} onDismiss={() => setErr(null)} />}
      {error && <ErrorBox message={error} />}
      {loading ? (
        <div className="flex items-center gap-2 py-3 text-sm text-slate-500">
          <Spinner /> 加载项目…
        </div>
      ) : projects.length === 0 ? (
        <EmptyState title="还没有研究项目" hint="点击“新建”创建第一个项目" />
      ) : (
        <ul className="space-y-1" data-testid="project-list">
          {projects.map((p) => (
            <li key={p.id}>
              <div
                className={cx(
                  "group flex items-center justify-between rounded-md px-2 py-1.5 text-sm",
                  p.id === selectedId ? "bg-indigo-600 text-white" : "hover:bg-slate-200/70",
                )}
              >
                <button className="min-w-0 flex-1 text-left" onClick={() => onSelect(p.id)} title={p.description || p.name}>
                  <span className="block truncate font-medium">{p.name}</span>
                  <span className={cx("block text-[11px]", p.id === selectedId ? "text-indigo-100" : "text-slate-500")}>
                    {p.document_count} 文档 · {p.conversation_count} 对话 · {p.report_count} 报告
                  </span>
                </button>
                <button
                  onClick={() => remove(p)}
                  aria-label={`删除项目 ${p.name}`}
                  className={cx("ml-1 rounded px-1 text-xs opacity-60 hover:opacity-100", p.id === selectedId ? "text-white" : "text-rose-600")}
                >
                  删除
                </button>
              </div>
            </li>
          ))}
        </ul>
      )}
    </section>
  );
}

export function DocumentLibrary({
  projectId,
  docs,
  loading,
  error,
  maxUploadMb,
  onChanged,
  onOpenDoc,
}: {
  projectId: string;
  docs: DocumentInfo[];
  loading: boolean;
  error: string | null;
  maxUploadMb: number;
  onChanged: () => void;
  onOpenDoc: (d: DocumentInfo) => void;
}) {
  const input = useRef<HTMLInputElement>(null);
  const [uploading, setUploading] = useState(false);
  const [results, setResults] = useState<UploadResult[]>([]);
  const [err, setErr] = useState<string | null>(null);
  const [drag, setDrag] = useState(false);

  async function uploadFiles(files: File[]) {
    if (!files.length) return;
    setUploading(true);
    setErr(null);
    setResults([]);
    try {
      const res = await api.upload(projectId, files);
      setResults(res.filter((r) => !r.ok));
      onChanged();
    } catch (e) {
      setErr((e as Error).message);
    } finally {
      setUploading(false);
      if (input.current) input.current.value = "";
    }
  }

  async function act(fn: () => Promise<unknown>) {
    setErr(null);
    try {
      await fn();
      onChanged();
    } catch (e) {
      setErr((e as Error).message);
    }
  }

  return (
    <section aria-label="文档库" className="mt-5">
      <SectionTitle>文档库</SectionTitle>
      <div
        onDragOver={(e) => {
          e.preventDefault();
          setDrag(true);
        }}
        onDragLeave={() => setDrag(false)}
        onDrop={(e) => {
          e.preventDefault();
          setDrag(false);
          uploadFiles(Array.from(e.dataTransfer.files));
        }}
        className={cx(
          "rounded-md border-2 border-dashed px-3 py-3 text-center text-xs text-slate-500 transition",
          drag ? "border-indigo-400 bg-indigo-50" : "border-slate-300 bg-white",
        )}
      >
        <input
          ref={input}
          type="file"
          multiple
          accept=".pdf,.docx,.txt,.md,.markdown"
          className="hidden"
          data-testid="file-input"
          onChange={(e) => uploadFiles(Array.from(e.target.files ?? []))}
        />
        <Button size="sm" variant="secondary" onClick={() => input.current?.click()} disabled={uploading}>
          {uploading ? <Spinner /> : null} {uploading ? "上传中…" : "上传文档"}
        </Button>
        <p className="mt-1">或拖拽文件到此处 · PDF / DOCX / TXT / Markdown · ≤ {maxUploadMb} MB</p>
      </div>
      {err && <div className="mt-2"><ErrorBox message={err} onDismiss={() => setErr(null)} /></div>}
      {results.map((r) => (
        <div key={r.filename} className="mt-2">
          <ErrorBox message={r.error ?? `${r.filename} 上传失败`} onDismiss={() => setResults((x) => x.filter((y) => y !== r))} />
        </div>
      ))}
      {error && <div className="mt-2"><ErrorBox message={error} /></div>}

      <div className="mt-2">
        {loading && docs.length === 0 ? (
          <div className="flex items-center gap-2 py-3 text-sm text-slate-500">
            <Spinner /> 加载文档…
          </div>
        ) : docs.length === 0 ? (
          <EmptyState title="项目中还没有文档" hint="上传多份文档后即可检索、问答和比较" />
        ) : (
          <ul className="space-y-1.5" data-testid="document-list">
            {docs.map((d) => {
              const st = STATUS[d.status];
              return (
                <li key={d.id} className="rounded-md border border-slate-200 bg-white p-2 text-xs" data-testid="document-item" data-status={d.status}>
                  <div className="flex items-start justify-between gap-2">
                    <button className="min-w-0 text-left" onClick={() => onOpenDoc(d)} title="查看文档信息">
                      <span className="block truncate text-sm font-medium text-slate-800">{d.filename}</span>
                      <span className="text-slate-500">
                        {d.file_type.toUpperCase()} · {formatBytes(d.size_bytes)}
                        {d.status === "ready" && ` · ${d.page_count} 页 · ${d.chunk_count} 块`}
                        {d.published_date && ` · ${d.published_date}`}
                      </span>
                    </button>
                    <Badge tone={st.tone}>
                      {(d.status === "processing" || d.status === "pending") && <Spinner className="h-3 w-3" />}
                      {st.label}
                    </Badge>
                  </div>
                  {d.error_message && <p className="mt-1 break-words text-[11px] text-rose-700">{d.error_message}</p>}
                  <div className="mt-1 flex gap-1">
                    {(d.status === "failed" || d.status === "needs_ocr") && (
                      <Button size="sm" variant="secondary" onClick={() => act(() => api.retryDocument(projectId, d.id))}>
                        重试
                      </Button>
                    )}
                    <Button
                      size="sm"
                      variant="ghost"
                      disabled={d.status === "processing"}
                      onClick={() => {
                        if (confirm(`删除《${d.filename}》？其分块、向量和文件将被一并清除。`)) act(() => api.deleteDocument(projectId, d.id));
                      }}
                    >
                      删除
                    </Button>
                  </div>
                </li>
              );
            })}
          </ul>
        )}
      </div>
    </section>
  );
}
