"use client";

import type { Claim, Evidence, EvidenceTarget, Message, Validation } from "@/lib/types";
import { Badge, CitationChip, Notice, cx, locationLabel } from "./ui";

export const STATUS_BADGE: Record<string, { label: string; tone: "green" | "amber" | "slate" | "red" | "blue" }> = {
  answered: { label: "有据回答", tone: "green" },
  partial: { label: "部分回答", tone: "amber" },
  insufficient: { label: "无法确认", tone: "slate" },
  insufficient_evidence: { label: "证据不足", tone: "slate" },
  llm_unavailable: { label: "未配置模型 · 仅证据", tone: "amber" },
  llm_error: { label: "模型调用失败", tone: "red" },
};

export function targetFor(ev: Evidence | undefined): EvidenceTarget | null {
  if (!ev) return null;
  return ev.citation_id
    ? { kind: "citation", id: ev.citation_id, label: ev.label }
    : { kind: "chunk", id: ev.chunk_id, label: ev.label };
}

export function Chips({ ids, evidence, onOpen }: { ids: string[]; evidence: Evidence[]; onOpen: (t: EvidenceTarget) => void }) {
  return (
    <>
      {ids.map((id) => {
        const ev = evidence.find((e) => e.label === id);
        const t = targetFor(ev);
        return <CitationChip key={id} label={id} invalid={!ev} onClick={t ? () => onOpen(t) : undefined} />;
      })}
    </>
  );
}

const CLAIM_TYPE = {
  fact: { label: "文档事实", tone: "blue" as const },
  inference: { label: "模型推断", tone: "violet" as const },
  unsupported: { label: "未经证实", tone: "red" as const },
};

export function ValidationNotice({ v }: { v?: Validation }) {
  if (!v) return null;
  const items: string[] = [];
  if (v.invalid_citation_ids.length) items.push(`已移除 ${v.invalid_citation_ids.length} 个不存在的引用编号（${v.invalid_citation_ids.join("、")}）`);
  if (v.unverified_quotes.length) items.push(`${v.unverified_quotes.length} 条引文与原文不一致，已改为显示检索原文`);
  if (v.unsupported_statements.length) items.push(`${v.unsupported_statements.length} 条陈述缺少有效引用，已标记为“未经证实”`);
  items.push(...v.warnings);
  if (!items.length) return <Badge tone="green">引用校验通过</Badge>;
  return (
    <Notice>
      <p className="font-medium">引用校验</p>
      <ul className="ml-4 list-disc">
        {items.map((s, i) => (
          <li key={i}>{s}</li>
        ))}
      </ul>
    </Notice>
  );
}

export function EvidenceList({ evidence, onOpen, title = "检索到的证据" }: { evidence: Evidence[]; onOpen: (t: EvidenceTarget) => void; title?: string }) {
  if (!evidence.length) return null;
  return (
    <details className="group rounded-md border border-slate-200 bg-slate-50" open={evidence.length <= 3}>
      <summary className="cursor-pointer px-3 py-1.5 text-xs font-medium text-slate-600">
        {title}（{evidence.length}）
      </summary>
      <ul className="divide-y divide-slate-200">
        {evidence.map((e) => (
          <li key={e.label}>
            <button className="w-full px-3 py-2 text-left hover:bg-white" onClick={() => onOpen(targetFor(e)!)} data-testid="evidence-item">
              <div className="flex flex-wrap items-center gap-1.5 text-xs">
                <Badge tone="indigo">{e.label}</Badge>
                <span className="font-medium text-slate-700">{e.document_name}</span>
                <span className="text-slate-500">{locationLabel(e.page_number, e.line_start, e.line_end, e.page_mode)}</span>
                <span className="text-slate-400">相关度 {e.relevance.score.toFixed(2)} · 覆盖 {(e.relevance.term_coverage * 100).toFixed(0)}%</span>
              </div>
              <p className="mt-1 line-clamp-3 text-xs text-slate-600">{e.text}</p>
            </button>
          </li>
        ))}
      </ul>
    </details>
  );
}

export function AnswerView({ msg, onOpen }: { msg: Message; onOpen: (t: EvidenceTarget) => void }) {
  const p = msg.payload ?? {};
  const evidence: Evidence[] = p.evidence ?? [];
  const status = STATUS_BADGE[msg.status ?? ""] ?? { label: msg.status ?? "", tone: "slate" as const };
  const claims: Claim[] = p.claims ?? [];
  return (
    <div className="space-y-3" data-testid="answer" data-status={msg.status}>
      <div className="flex flex-wrap items-center gap-2">
        <Badge tone={status.tone}>{status.label}</Badge>
        {msg.model_info && (
          <span className="text-[11px] text-slate-400">
            {msg.model_info.provider} / {msg.model_info.model} · {(msg.model_info.latency_ms / 1000).toFixed(1)}s
          </span>
        )}
      </div>

      {p.conclusion ? (
        <div>
          <h4 className="text-xs font-semibold text-slate-500">结论</h4>
          <p className="mt-0.5 whitespace-pre-wrap text-[15px] leading-relaxed text-slate-900">
            {p.conclusion}
            <Chips ids={p.conclusion_evidence_ids ?? []} evidence={evidence} onOpen={onOpen} />
          </p>
        </div>
      ) : (
        <p className="text-sm text-slate-700">{msg.content}</p>
      )}

      {claims.length > 0 && (
        <div>
          <h4 className="text-xs font-semibold text-slate-500">支持结论的证据</h4>
          <ul className="mt-1 space-y-2">
            {claims.map((c, i) => {
              const t = CLAIM_TYPE[c.type] ?? CLAIM_TYPE.unsupported;
              return (
                <li key={i} className={cx("rounded-md border px-3 py-2 text-sm", c.type === "unsupported" ? "border-rose-200 bg-rose-50" : "border-slate-200 bg-white")}>
                  <div className="flex flex-wrap items-start gap-1.5">
                    <Badge tone={t.tone}>{t.label}</Badge>
                    <span className="flex-1">
                      {c.statement}
                      <Chips ids={c.evidence_ids} evidence={evidence} onOpen={onOpen} />
                    </span>
                  </div>
                  {c.quote && c.quote_verified && <p className="mt-1 border-l-2 border-amber-300 pl-2 text-xs text-slate-600">“{c.quote}”</p>}
                </li>
              );
            })}
          </ul>
        </div>
      )}

      {(p.uncertainties?.length ?? 0) > 0 && (
        <div>
          <h4 className="text-xs font-semibold text-slate-500">不确定性</h4>
          <ul className="ml-4 list-disc text-sm text-slate-700">
            {p.uncertainties.map((u: string, i: number) => <li key={i}>{u}</li>)}
          </ul>
        </div>
      )}
      {(p.information_gaps?.length ?? 0) > 0 && (
        <div>
          <h4 className="text-xs font-semibold text-slate-500">信息缺口</h4>
          <ul className="ml-4 list-disc text-sm text-slate-700">
            {p.information_gaps.map((u: string, i: number) => <li key={i}>{u}</li>)}
          </ul>
        </div>
      )}
      {msg.status === "llm_unavailable" && (
        <Notice>未配置大模型（在后端 .env 中设置 LLM_PROVIDER 与 LLM_API_KEY）。系统没有生成任何结论，以下是检索到的原文证据。</Notice>
      )}
      {msg.status === "llm_error" && <Notice>{p.error}</Notice>}
      {p.validation && <ValidationNotice v={p.validation} />}
      <EvidenceList evidence={evidence} onOpen={onOpen} />
      {(p.near_misses?.length ?? 0) > 0 && (
        <EvidenceList
          title="最接近但未达阈值的片段（不作为证据）"
          evidence={(p.near_misses as Evidence[]).map((e, i) => ({ ...e, label: `候选${i + 1}` }))}
          onOpen={onOpen}
        />
      )}
    </div>
  );
}
