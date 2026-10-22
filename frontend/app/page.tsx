"use client";

import { useCallback, useEffect, useState } from "react";
import { api } from "@/lib/api";
import type { DocumentInfo, EvidenceTarget, Health, Project } from "@/lib/types";
import { ChatPanel } from "@/components/ChatPanel";
import { ComparePanel } from "@/components/ComparePanel";
import { EvidencePanel } from "@/components/EvidencePanel";
import { ReportPanel } from "@/components/ReportPanel";
import { SearchPanel } from "@/components/SearchPanel";
import { DocumentLibrary, ProjectList } from "@/components/Sidebar";
import { Badge, EmptyState, ErrorBox, cx } from "@/components/ui";

const TABS = [
  { id: "qa", label: "问答" },
  { id: "search", label: "检索" },
  { id: "compare", label: "跨文档比较" },
  { id: "report", label: "研究报告" },
] as const;
type Tab = (typeof TABS)[number]["id"];
type MobilePane = "library" | "work" | "evidence";

export default function Workbench() {
  const [health, setHealth] = useState<Health | null>(null);
  const [healthErr, setHealthErr] = useState<string | null>(null);
  const [projects, setProjects] = useState<Project[]>([]);
  const [projectsLoading, setProjectsLoading] = useState(true);
  const [projectsErr, setProjectsErr] = useState<string | null>(null);
  const [pid, setPid] = useState<string | null>(null);
  const [docs, setDocs] = useState<DocumentInfo[]>([]);
  const [docsLoading, setDocsLoading] = useState(false);
  const [docsErr, setDocsErr] = useState<string | null>(null);
  const [tab, setTab] = useState<Tab>("qa");
  const [target, setTarget] = useState<EvidenceTarget | null>(null);
  const [openDoc, setOpenDoc] = useState<DocumentInfo | null>(null);
  const [pane, setPane] = useState<MobilePane>("work");

  useEffect(() => {
    api.health().then(setHealth).catch((e) => setHealthErr(e.message));
  }, []);

  const loadProjects = useCallback(async (selectId?: string | null) => {
    setProjectsLoading(true);
    try {
      const ps = await api.projects();
      setProjects(ps);
      setProjectsErr(null);
      if (selectId !== undefined) setPid(selectId);
      else setPid((cur) => cur ?? ps[0]?.id ?? null);
    } catch (e) {
      setProjectsErr((e as Error).message);
    } finally {
      setProjectsLoading(false);
    }
  }, []);

  useEffect(() => {
    loadProjects();
  }, [loadProjects]);

  const loadDocs = useCallback(async () => {
    if (!pid) return;
    try {
      const d = await api.documents(pid);
      setDocs(d);
      setDocsErr(null);
      setOpenDoc((cur) => (cur ? d.find((x) => x.id === cur.id) ?? null : null));
    } catch (e) {
      setDocsErr((e as Error).message);
    } finally {
      setDocsLoading(false);
    }
  }, [pid]);

  useEffect(() => {
    setDocs([]);
    setTarget(null);
    setOpenDoc(null);
    if (pid) {
      setDocsLoading(true);
      loadDocs();
    }
  }, [pid, loadDocs]);

  // Poll while documents are being processed.
  const busyDocs = docs.some((d) => d.status === "pending" || d.status === "processing");
  useEffect(() => {
    if (!busyDocs) return;
    const t = setInterval(loadDocs, 1500);
    return () => clearInterval(t);
  }, [busyDocs, loadDocs]);

  const openEvidence = useCallback((t: EvidenceTarget) => {
    setOpenDoc(null);
    setTarget(t);
    setPane("evidence");
  }, []);

  const refreshCounts = useCallback(() => {
    api.projects().then(setProjects).catch(() => undefined);
  }, []);

  const project = projects.find((p) => p.id === pid) ?? null;
  const readyCount = docs.filter((d) => d.status === "ready").length;

  return (
    <div className="flex h-dvh flex-col">
      <header className="flex flex-wrap items-center gap-2 border-b border-slate-200 bg-white px-4 py-2">
        <h1 className="text-base font-bold tracking-tight text-slate-900">ResearchOS</h1>
        <span className="hidden text-xs text-slate-500 sm:inline">证据驱动的多文档研究工作台</span>
        <div className="ml-auto flex flex-wrap items-center gap-1.5" data-testid="health">
          {healthErr && <Badge tone="red">后端不可用</Badge>}
          {health && (
            <>
              <Badge tone={health.llm.configured ? "green" : "amber"} title={health.llm.reason}>
                {health.llm.configured ? `模型：${health.llm.model}` : "未配置大模型"}
              </Badge>
              <Badge tone={health.embedding.semantic ? "green" : "slate"} title={health.embedding.model}>
                {health.embedding.semantic ? "语义向量" : "离线词法向量"}
              </Badge>
            </>
          )}
        </div>
      </header>

      {/* Mobile pane switcher */}
      <nav className="flex border-b border-slate-200 bg-white lg:hidden" aria-label="面板切换">
        {(["library", "work", "evidence"] as const).map((p) => (
          <button key={p} onClick={() => setPane(p)} className={cx("flex-1 py-2 text-sm", pane === p ? "border-b-2 border-indigo-600 font-semibold text-indigo-700" : "text-slate-500")}>
            {{ library: "资料", work: "工作区", evidence: "证据" }[p]}
          </button>
        ))}
      </nav>

      {healthErr && <div className="p-2"><ErrorBox message={`${healthErr}（后端地址见 README）`} /></div>}

      <div className="flex min-h-0 flex-1">
        <aside className={cx("w-full shrink-0 overflow-y-auto border-r border-slate-200 bg-slate-50 p-3 lg:block lg:w-72", pane === "library" ? "block" : "hidden")}>
          <ProjectList
            projects={projects}
            loading={projectsLoading}
            error={projectsErr}
            selectedId={pid}
            onSelect={(id) => { setPid(id); setPane("work"); }}
            onChanged={(sel) => loadProjects(sel)}
          />
          {pid && (
            <DocumentLibrary
              projectId={pid}
              docs={docs}
              loading={docsLoading}
              error={docsErr}
              maxUploadMb={health?.max_upload_mb ?? 50}
              onChanged={() => { loadDocs(); loadProjects(pid); }}
              onOpenDoc={(d) => { setTarget(null); setOpenDoc(d); setPane("evidence"); }}
            />
          )}
        </aside>

        <main className={cx("min-w-0 flex-1 flex-col bg-white lg:flex", pane === "work" ? "flex" : "hidden")}>
          {!project ? (
            <div className="p-6"><EmptyState title="创建或选择一个研究项目" hint="所有检索、问答和报告都限定在当前项目范围内" /></div>
          ) : (
            <>
              <div className="border-b border-slate-200 px-4 pt-3">
                <p className="truncate text-sm font-semibold text-slate-800" data-testid="current-project">{project.name}</p>
                {project.description && <p className="truncate text-xs text-slate-500">{project.description}</p>}
                <div className="mt-2 flex gap-1 overflow-x-auto" role="tablist">
                  {TABS.map((t) => (
                    <button key={t.id} role="tab" aria-selected={tab === t.id} onClick={() => setTab(t.id)}
                      className={cx("whitespace-nowrap rounded-t-md px-3 py-1.5 text-sm", tab === t.id ? "border border-b-white border-slate-200 bg-white font-semibold text-indigo-700 -mb-px" : "text-slate-500 hover:text-slate-800")}>
                      {t.label}
                    </button>
                  ))}
                </div>
              </div>
              <div className="min-h-0 flex-1 p-4">
                {tab === "qa" && <ChatPanel projectId={project.id} readyCount={readyCount} onOpen={openEvidence} onActivity={refreshCounts} />}
                {tab === "search" && <SearchPanel projectId={project.id} docs={docs} onOpen={openEvidence} />}
                {tab === "compare" && <ComparePanel projectId={project.id} docs={docs} onOpen={openEvidence} onActivity={refreshCounts} />}
                {tab === "report" && <ReportPanel projectId={project.id} readyCount={readyCount} onOpen={openEvidence} onActivity={refreshCounts} />}
              </div>
            </>
          )}
        </main>

        <aside className={cx("w-full shrink-0 overflow-y-auto border-l border-slate-200 bg-slate-50 p-3 lg:block lg:w-[26rem]", pane === "evidence" ? "block" : "hidden")}>
          <EvidencePanel projectId={pid} target={target} doc={openDoc} onDocUpdated={loadDocs} />
        </aside>
      </div>
    </div>
  );
}
