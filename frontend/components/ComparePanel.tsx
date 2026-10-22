"use client";

import { useCallback, useEffect, useState } from "react";
import { api } from "@/lib/api";
import type { Conversation, DocumentInfo, Evidence, EvidenceTarget, Message } from "@/lib/types";
import { Chips, EvidenceList, STATUS_BADGE, ValidationNotice } from "./AnswerView";
import { Badge, Button, EmptyState, ErrorBox, Notice, Spinner } from "./ui";

const CAT_TONE: Record<string, "red" | "blue" | "amber" | "green"> = {
  contradiction: "red",
  temporal_change: "blue",
  different_conditions: "amber",
  supplementary: "green",
};

export function ComparePanel({ projectId, docs, onOpen, onActivity }: { projectId: string; docs: DocumentInfo[]; onOpen: (t: EvidenceTarget) => void; onActivity?: () => void }) {
  const ready = docs.filter((d) => d.status === "ready");
  const [question, setQuestion] = useState("");
  const [selected, setSelected] = useState<string[]>([]);
  const [busy, setBusy] = useState(false);
  const [err, setErr] = useState<string | null>(null);
  const [result, setResult] = useState<Message | null>(null);
  const [history, setHistory] = useState<Conversation[]>([]);

  const loadHistory = useCallback(async () => {
    try {
      setHistory((await api.conversations(projectId)).filter((c) => c.title.startsWith("比较：")));
    } catch (e) {
      setErr((e as Error).message);
    }
  }, [projectId]);

  useEffect(() => {
    setResult(null);
    loadHistory();
  }, [projectId, loadHistory]);

  async function run(e: React.FormEvent) {
    e.preventDefault();
    setBusy(true);
    setErr(null);
    try {
      setResult(await api.compare(projectId, question.trim(), selected));
      loadHistory();
      onActivity?.();
    } catch (e) {
      setErr((e as Error).message);
    } finally {
      setBusy(false);
    }
  }

  async function openHistory(cid: string) {
    setErr(null);
    try {
      const msgs = await api.messages(projectId, cid);
      setResult(msgs.find((m) => m.role === "assistant") ?? null);
    } catch (e) {
      setErr((e as Error).message);
    }
  }

  return (
    <div className="flex h-full min-h-0 flex-col">
      <form onSubmit={run} className="space-y-2 border-b border-slate-200 pb-3">
        <textarea value={question} onChange={(e) => setQuestion(e.target.value)} rows={2} aria-label="比较问题"
          placeholder="例如：比较这些文档对同一故障原因的解释" className="w-full rounded-md border border-slate-300 px-3 py-2 text-sm" />
        <fieldset className="flex flex-wrap gap-x-3 gap-y-1 text-xs text-slate-700">
          <legend className="mb-1 text-slate-500">参与比较的文档（不选则使用全部已就绪文档）</legend>
          {ready.map((d) => (
            <label key={d.id} className="flex items-center gap-1">
              <input type="checkbox" checked={selected.includes(d.id)}
                onChange={(e) => setSelected((s) => (e.target.checked ? [...s, d.id] : s.filter((x) => x !== d.id)))} />
              {d.filename}
            </label>
          ))}
        </fieldset>
        <div className="flex flex-wrap items-center gap-2">
          <Button type="submit" disabled={busy || !question.trim() || ready.length < 2} data-testid="compare-button">
            {busy ? <Spinner /> : null} 开始比较
          </Button>
          {ready.length < 2 && <span className="text-xs text-slate-500">至少需要 2 份已就绪文档</span>}
          {history.length > 0 && (
            <select aria-label="历史比较" className="ml-auto max-w-60 rounded border border-slate-300 bg-white px-2 py-1 text-xs" value=""
              onChange={(e) => e.target.value && openHistory(e.target.value)}>
              <option value="">历史比较（{history.length}）</option>
              {history.map((h) => <option key={h.id} value={h.id}>{h.title.replace("比较：", "")}</option>)}
            </select>
          )}
        </div>
      </form>
      {err && <div className="mt-2"><ErrorBox message={err} onDismiss={() => setErr(null)} /></div>}
      <div className="min-h-0 flex-1 overflow-y-auto py-3">
        {busy && <div className="flex items-center gap-2 text-sm text-slate-500"><Spinner /> 正在逐文档检索证据并比较…</div>}
        {!busy && !result && <EmptyState title="跨文档比较" hint="逐文档检索证据，区分真正矛盾、时间变化、适用条件差异与补充信息" />}
        {!busy && result && <ComparisonView msg={result} onOpen={onOpen} />}
      </div>
    </div>
  );
}

function ComparisonView({ msg, onOpen }: { msg: Message; onOpen: (t: EvidenceTarget) => void }) {
  const p = msg.payload ?? {};
  const evidence: Evidence[] = p.evidence ?? [];
  const docs: { doc: string; document_name: string; published_date: string | null; evidence_ids: string[]; has_evidence: boolean }[] = p.documents ?? [];
  const status = STATUS_BADGE[msg.status ?? ""] ?? { label: msg.status, tone: "slate" as const };
  const dims: { name: string; description: string }[] = p.dimensions ?? [];
  const positions: { doc: string; dimension: string; conclusion: string; evidence_ids: string[]; supported?: boolean }[] = p.document_positions ?? [];

  return (
    <div className="space-y-4" data-testid="comparison" data-status={msg.status}>
      <div className="flex flex-wrap items-center gap-2">
        <Badge tone={status.tone}>{status.label}</Badge>
        <span className="text-sm font-medium text-slate-800">{p.question}</span>
      </div>
      {msg.status !== "answered" && <Notice>{msg.content}</Notice>}
      {p.summary && <p className="text-[15px] leading-relaxed">{p.summary}</p>}

      {dims.length > 0 && (
        <div className="overflow-x-auto">
          <table className="w-full min-w-[480px] border-collapse text-sm">
            <thead>
              <tr className="bg-slate-50 text-left text-xs text-slate-500">
                <th className="border border-slate-200 px-2 py-1">文档</th>
                {dims.map((d) => <th key={d.name} className="border border-slate-200 px-2 py-1" title={d.description}>{d.name}</th>)}
              </tr>
            </thead>
            <tbody>
              {docs.map((d) => (
                <tr key={d.doc} className="align-top">
                  <td className="border border-slate-200 px-2 py-1 text-xs">
                    <span className="font-semibold">{d.doc}</span> {d.document_name}
                    <div className="text-slate-400">{d.published_date ?? "日期未知"}</div>
                  </td>
                  {dims.map((dim) => {
                    const pos = positions.find((x) => x.doc === d.doc && x.dimension === dim.name);
                    return (
                      <td key={dim.name} className="border border-slate-200 px-2 py-1">
                        {pos ? (
                          <>
                            <span className={pos.supported === false ? "text-rose-700" : ""}>{pos.conclusion}</span>
                            <Chips ids={pos.evidence_ids} evidence={evidence} onOpen={onOpen} />
                          </>
                        ) : (
                          <span className="text-slate-400">—</span>
                        )}
                      </td>
                    );
                  })}
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      )}

      {(p.agreements?.length ?? 0) > 0 && (
        <section>
          <h4 className="text-xs font-semibold text-slate-500">一致之处</h4>
          <ul className="ml-4 list-disc text-sm">
            {p.agreements.map((a: { statement: string; evidence_ids: string[] }, i: number) => (
              <li key={i}>{a.statement}<Chips ids={a.evidence_ids} evidence={evidence} onOpen={onOpen} /></li>
            ))}
          </ul>
        </section>
      )}
      {(p.differences?.length ?? 0) > 0 && (
        <section>
          <h4 className="text-xs font-semibold text-slate-500">不一致之处</h4>
          <ul className="space-y-2">
            {p.differences.map((d: { statement: string; category: string; category_label: string; explanation: string; evidence_ids: string[]; needs_review?: boolean; supported?: boolean }, i: number) => (
              <li key={i} className="rounded-md border border-slate-200 bg-white px-3 py-2 text-sm" data-testid="difference">
                <div className="flex flex-wrap items-center gap-1.5">
                  <Badge tone={CAT_TONE[d.category] ?? "slate"}>{d.category_label}</Badge>
                  {d.needs_review && <Badge tone="red">需人工复核</Badge>}
                  {d.supported === false && <Badge tone="red">缺少有效引用</Badge>}
                </div>
                <p className="mt-1">{d.statement}<Chips ids={d.evidence_ids} evidence={evidence} onOpen={onOpen} /></p>
                {d.explanation && <p className="mt-0.5 text-xs text-slate-500">判断依据：{d.explanation}</p>}
              </li>
            ))}
          </ul>
        </section>
      )}
      {(p.possible_reasons?.length ?? 0) > 0 && (
        <section>
          <h4 className="text-xs font-semibold text-slate-500">可能的原因</h4>
          <ul className="ml-4 list-disc text-sm">
            {p.possible_reasons.map((r: { statement: string; type: string; evidence_ids: string[] }, i: number) => (
              <li key={i}><Badge tone={r.type === "fact" ? "blue" : "violet"}>{r.type === "fact" ? "事实" : "推断"}</Badge> {r.statement}<Chips ids={r.evidence_ids} evidence={evidence} onOpen={onOpen} /></li>
            ))}
          </ul>
        </section>
      )}
      {(p.undetermined?.length ?? 0) > 0 && (
        <section>
          <h4 className="text-xs font-semibold text-slate-500">无法判断的部分</h4>
          <ul className="ml-4 list-disc text-sm">
            {p.undetermined.map((u: { question: string; reason: string }, i: number) => <li key={i}>{u.question}：<span className="text-slate-500">{u.reason}</span></li>)}
          </ul>
        </section>
      )}
      {p.validation && <ValidationNotice v={p.validation} />}

      <section>
        <h4 className="mb-1 text-xs font-semibold text-slate-500">逐文档证据矩阵</h4>
        <div className="grid gap-2 md:grid-cols-2">
          {docs.map((d) => (
            <div key={d.doc} className="rounded-md border border-slate-200 bg-white p-2" data-testid="doc-evidence-card">
              <p className="text-xs font-semibold">{d.doc} · {d.document_name}</p>
              <p className="text-[11px] text-slate-400">发布日期：{d.published_date ?? "未知"}</p>
              {d.has_evidence ? (
                <EvidenceList evidence={evidence.filter((e) => d.evidence_ids.includes(e.label))} onOpen={onOpen} title="相关证据" />
              ) : (
                <p className="mt-1 text-xs text-slate-500">该文档未检索到与问题相关的证据</p>
              )}
            </div>
          ))}
        </div>
      </section>
    </div>
  );
}
