import type {
  CitationView,
  Conversation,
  DocumentInfo,
  Health,
  Message,
  Project,
  Report,
  SearchResponse,
  SourceView,
  UploadResult,
} from "./types";

export class ApiError extends Error {
  constructor(
    message: string,
    public status: number,
  ) {
    super(message);
  }
}

function detailMessage(detail: unknown): string {
  if (!detail) return "";
  if (typeof detail === "string") return detail;
  if (Array.isArray(detail)) return detail.map((d) => d?.msg ?? JSON.stringify(d)).join("；");
  if (typeof detail === "object" && detail && "message" in detail) return String((detail as { message: unknown }).message);
  return JSON.stringify(detail);
}

async function request<T>(path: string, init?: RequestInit): Promise<T> {
  let res: Response;
  try {
    res = await fetch(path, init);
  } catch {
    throw new ApiError("无法连接后端服务，请确认 API 已启动", 0);
  }
  if (!res.ok) {
    let msg = `请求失败（HTTP ${res.status}）`;
    try {
      const body = await res.json();
      msg = detailMessage(body.detail) || msg;
    } catch {
      /* non-JSON error body */
    }
    throw new ApiError(msg, res.status);
  }
  if (res.status === 204) return undefined as T;
  return res.json() as Promise<T>;
}

const json = (method: string, body: unknown): RequestInit => ({
  method,
  headers: { "content-type": "application/json" },
  body: JSON.stringify(body),
});

const P = (pid: string) => `/api/projects/${pid}`;

export const api = {
  health: () => request<Health>("/api/health"),
  projects: () => request<Project[]>("/api/projects"),
  createProject: (name: string, description: string) => request<Project>("/api/projects", json("POST", { name, description })),
  deleteProject: (pid: string) => request<void>(P(pid), { method: "DELETE" }),

  documents: (pid: string) => request<DocumentInfo[]>(`${P(pid)}/documents`),
  upload: async (pid: string, files: File[]): Promise<UploadResult[]> => {
    const fd = new FormData();
    files.forEach((f) => fd.append("files", f));
    try {
      return await request<UploadResult[]>(`${P(pid)}/documents`, { method: "POST", body: fd });
    } catch (e) {
      // single-file failures come back as an HTTP error; normalise to a per-file result
      if (e instanceof ApiError && files.length === 1 && e.status > 0) {
        return [{ filename: files[0].name, ok: false, document: null, error: e.message, status_code: e.status }];
      }
      throw e;
    }
  },
  deleteDocument: (pid: string, did: string) =>
    request<{ deleted_chunks: number; files_removed: boolean }>(`${P(pid)}/documents/${did}`, { method: "DELETE" }),
  retryDocument: (pid: string, did: string) => request<DocumentInfo>(`${P(pid)}/documents/${did}/retry`, { method: "POST" }),
  updateDocument: (pid: string, did: string, body: { published_date?: string | null }) =>
    request<DocumentInfo>(`${P(pid)}/documents/${did}`, json("PATCH", body)),

  search: (pid: string, body: { query: string; top_k?: number; document_ids?: string[]; page_from?: number; page_to?: number }) =>
    request<SearchResponse>(`${P(pid)}/search`, json("POST", body)),

  conversations: (pid: string) => request<Conversation[]>(`${P(pid)}/conversations`),
  messages: (pid: string, cid: string) => request<Message[]>(`${P(pid)}/conversations/${cid}/messages`),
  deleteConversation: (pid: string, cid: string) => request<void>(`${P(pid)}/conversations/${cid}`, { method: "DELETE" }),
  ask: (pid: string, question: string, conversation_id?: string | null, document_ids?: string[]) =>
    request<Message>(`${P(pid)}/ask`, json("POST", { question, conversation_id: conversation_id ?? null, document_ids: document_ids?.length ? document_ids : null })),
  compare: (pid: string, question: string, document_ids?: string[]) =>
    request<Message>(`${P(pid)}/compare`, json("POST", { question, document_ids: document_ids?.length ? document_ids : null })),

  citation: (pid: string, cid: string) => request<CitationView>(`${P(pid)}/citations/${cid}`),
  chunk: (pid: string, chunkId: string) => request<SourceView>(`${P(pid)}/chunks/${chunkId}`),

  reports: (pid: string) => request<Report[]>(`${P(pid)}/reports`),
  createReport: (pid: string, question: string, title?: string) =>
    request<Report>(`${P(pid)}/reports`, json("POST", { question, title: title || null })),
  updateReport: (pid: string, rid: string, body: { title?: string; content_md?: string }) =>
    request<Report>(`${P(pid)}/reports/${rid}`, json("PUT", body)),
  deleteReport: (pid: string, rid: string) => request<void>(`${P(pid)}/reports/${rid}`, { method: "DELETE" }),
  exportUrl: (pid: string, rid: string) => `${P(pid)}/reports/${rid}/export?format=md`,
};
