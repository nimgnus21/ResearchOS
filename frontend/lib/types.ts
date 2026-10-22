export interface Health {
  status: string;
  llm: { configured: boolean; provider: string | null; model: string | null; reason?: string };
  embedding: { provider: string; model: string; dim: number; semantic: boolean };
  retrieval: { min_term_coverage: number; min_vector_sim: number };
  max_upload_mb: number;
}

export interface Project {
  id: string;
  name: string;
  description: string;
  created_at: string;
  document_count: number;
  conversation_count: number;
  report_count: number;
}

export type DocStatus = "pending" | "processing" | "ready" | "failed" | "needs_ocr";

export interface DocumentInfo {
  id: string;
  project_id: string;
  filename: string;
  file_type: "pdf" | "docx" | "txt" | "md";
  size_bytes: number;
  content_hash: string;
  status: DocStatus;
  error_message: string | null;
  attempts: number;
  page_count: number | null;
  page_mode: string | null;
  title: string | null;
  author: string | null;
  published_date: string | null;
  chunk_count: number;
  metadata: Record<string, unknown> & { warnings?: string[]; published_date_source?: string };
  created_at: string;
  processed_at: string | null;
}

export interface UploadResult {
  filename: string;
  ok: boolean;
  document: DocumentInfo | null;
  error: string | null;
  status_code: number | null;
}

export interface Relevance {
  score: number;
  rrf: number;
  keyword_rank: number | null;
  keyword_score: number | null;
  vector_rank: number | null;
  vector_similarity: number | null;
  term_coverage: number;
  matched_terms: string[];
  passes_threshold: boolean;
}

export interface SearchResult {
  chunk_id: string;
  document_id: string;
  document_name: string;
  page_number: number;
  page_mode: string | null;
  section_title: string | null;
  text: string;
  line_start: number | null;
  line_end: number | null;
  published_date: string | null;
  relevance: Relevance;
}

export interface Evidence extends SearchResult {
  label: string;
  doc_label?: string;
  citation_id?: string | null;
}

export interface SearchResponse {
  query: string;
  terms: string[];
  sufficient: boolean;
  params: Record<string, unknown>;
  retrieval_run_id: string;
  results: SearchResult[];
}

export interface Claim {
  statement: string;
  type: "fact" | "inference" | "unsupported";
  evidence_ids: string[];
  quote: string | null;
  quote_verified?: boolean;
  supported?: boolean;
}

export interface Validation {
  invalid_citation_ids: string[];
  unverified_quotes: { quote: string; evidence_ids: string[] }[];
  unsupported_statements: string[];
  warnings: string[];
  valid: boolean;
}

export interface Conversation {
  id: string;
  project_id: string;
  title: string;
  created_at: string;
}

export interface Message {
  id: string;
  conversation_id: string;
  role: "user" | "assistant";
  kind: "qa" | "comparison";
  content: string;
  status: string | null;
  payload: Record<string, any> | null; // eslint-disable-line @typescript-eslint/no-explicit-any
  model_info: { provider: string; model: string; latency_ms: number } | null;
  retrieval_run_id: string | null;
  created_at: string;
}

export interface Report {
  id: string;
  project_id: string;
  title: string;
  question: string;
  content_md: string;
  generation_mode: "llm" | "evidence_only";
  sources: { label: string; chunk_id: string; document_id: string; document_name: string; page_number: number }[];
  created_at: string;
  updated_at: string;
}

export interface SourceView {
  chunk: {
    id: string;
    page_number: number;
    section_title: string | null;
    text: string;
    char_start: number;
    char_end: number;
    line_start: number | null;
    line_end: number | null;
  };
  document: DocumentInfo;
  page_text: string | null;
  page_text_truncated?: { before: boolean; after: boolean };
  file_url: string;
  pdf_page_url: string | null;
}

export interface CitationView {
  citation: {
    id: string;
    label: string;
    document_name: string;
    page_number: number;
    quote: string;
    quote_verified: boolean;
    relevance: number | null;
  };
  source_available: boolean;
  source: SourceView | null;
  notice: string | null;
}

export type EvidenceTarget =
  | { kind: "citation"; id: string; label?: string }
  | { kind: "chunk"; id: string; label?: string; quote?: string | null };
