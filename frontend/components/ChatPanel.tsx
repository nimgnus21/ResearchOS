"use client";

import { useCallback, useEffect, useRef, useState } from "react";
import { api } from "@/lib/api";
import type { Conversation, EvidenceTarget, Message } from "@/lib/types";
import { AnswerView } from "./AnswerView";
import { Button, EmptyState, ErrorBox, Spinner, cx } from "./ui";

export function ChatPanel({ projectId, readyCount, onOpen, onActivity }: { projectId: string; readyCount: number; onOpen: (t: EvidenceTarget) => void; onActivity?: () => void }) {
  const [convs, setConvs] = useState<Conversation[]>([]);
  const [convId, setConvId] = useState<string | null>(null);
  const [messages, setMessages] = useState<Message[]>([]);
  const [question, setQuestion] = useState("");
  const [asking, setAsking] = useState(false);
  const [loading, setLoading] = useState(false);
  const [err, setErr] = useState<string | null>(null);
  const bottom = useRef<HTMLDivElement>(null);

  const loadConvs = useCallback(async () => {
    try {
      const all = await api.conversations(projectId);
      setConvs(all.filter((c) => !c.title.startsWith("比较：")));
    } catch (e) {
      setErr((e as Error).message);
    }
  }, [projectId]);

  useEffect(() => {
    setConvId(null);
    setMessages([]);
    loadConvs();
  }, [projectId, loadConvs]);

  useEffect(() => {
    if (!convId) return;
    setLoading(true);
    api
      .messages(projectId, convId)
      .then(setMessages)
      .catch((e) => setErr(e.message))
      .finally(() => setLoading(false));
  }, [projectId, convId]);

  useEffect(() => {
    bottom.current?.scrollIntoView({ behavior: "smooth" });
  }, [messages, asking]);

  async function ask(e: React.FormEvent) {
    e.preventDefault();
    const q = question.trim();
    if (!q) return;
    setAsking(true);
    setErr(null);
    const optimistic: Message = {
      id: "pending", conversation_id: convId ?? "", role: "user", kind: "qa", content: q, status: null,
      payload: null, model_info: null, retrieval_run_id: null, created_at: new Date().toISOString(),
    };
    setMessages((m) => [...m, optimistic]);
    setQuestion("");
    try {
      const answer = await api.ask(projectId, q, convId);
      if (!convId) {
        setConvId(answer.conversation_id);
        await loadConvs();
      }
      setMessages((m) => [...m.filter((x) => x.id !== "pending"), { ...optimistic, id: `u-${answer.id}` }, answer]);
      onActivity?.();
    } catch (e) {
      setMessages((m) => m.filter((x) => x.id !== "pending"));
      setQuestion(q);
      setErr((e as Error).message);
    } finally {
      setAsking(false);
    }
  }

  return (
    <div className="flex h-full min-h-0 flex-col">
      <div className="flex flex-wrap items-center gap-2 border-b border-slate-200 pb-2">
        <select
          aria-label="选择对话"
          value={convId ?? ""}
          onChange={(e) => setConvId(e.target.value || null)}
          className="min-w-0 max-w-full flex-1 rounded border border-slate-300 bg-white px-2 py-1 text-sm"
        >
          <option value="">— 新对话 —</option>
          {convs.map((c) => (
            <option key={c.id} value={c.id}>
              {c.title}
            </option>
          ))}
        </select>
        <Button size="sm" variant="secondary" onClick={() => { setConvId(null); setMessages([]); }}>新对话</Button>
        {convId && (
          <Button
            size="sm"
            variant="ghost"
            onClick={async () => {
              if (!confirm("删除该对话及其引用记录？")) return;
              await api.deleteConversation(projectId, convId).catch((e) => setErr(e.message));
              setConvId(null);
              setMessages([]);
              loadConvs();
            }}
          >
            删除对话
          </Button>
        )}
      </div>

      <div className="min-h-0 flex-1 space-y-4 overflow-y-auto py-3" data-testid="chat-thread">
        {loading && (
          <div className="flex items-center gap-2 text-sm text-slate-500">
            <Spinner /> 加载对话…
          </div>
        )}
        {!loading && messages.length === 0 && (
          <EmptyState
            title={readyCount ? "针对项目资料提问" : "项目中还没有可检索的文档"}
            hint={readyCount ? "回答只依据检索到的原文证据；证据不足时系统会明确说明无法确认" : "请先在左侧上传并等待文档处理完成"}
          />
        )}
        {messages.map((m) => (
          <div key={m.id} className={cx(m.role === "user" ? "flex justify-end" : "")}>
            {m.role === "user" ? (
              <div className="max-w-[85%] rounded-lg bg-indigo-600 px-3 py-2 text-sm text-white">{m.content}</div>
            ) : (
              <div className="rounded-lg border border-slate-200 bg-white p-3 shadow-sm">
                <AnswerView msg={m} onOpen={onOpen} />
              </div>
            )}
          </div>
        ))}
        {asking && (
          <div className="flex items-center gap-2 text-sm text-slate-500" data-testid="asking">
            <Spinner /> 正在检索证据并生成回答…
          </div>
        )}
        <div ref={bottom} />
      </div>

      {err && <ErrorBox message={err} onDismiss={() => setErr(null)} />}
      <form onSubmit={ask} className="mt-2 flex gap-2">
        <textarea
          value={question}
          onChange={(e) => setQuestion(e.target.value)}
          onKeyDown={(e) => {
            if (e.key === "Enter" && !e.shiftKey && !e.nativeEvent.isComposing) {
              e.preventDefault();
              (e.currentTarget.form as HTMLFormElement).requestSubmit();
            }
          }}
          placeholder="输入研究问题，Enter 发送，Shift+Enter 换行"
          aria-label="研究问题"
          rows={2}
          className="min-w-0 flex-1 resize-none rounded-md border border-slate-300 px-3 py-2 text-sm"
        />
        <Button type="submit" disabled={asking || !question.trim() || readyCount === 0} data-testid="ask-button">
          {asking ? <Spinner /> : "提问"}
        </Button>
      </form>
    </div>
  );
}
