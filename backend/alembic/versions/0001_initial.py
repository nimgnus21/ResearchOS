"""Initial schema: projects, documents, pages, chunks (+FTS, pgvector), retrieval runs,
conversations, messages, citations, reports.

Revision ID: 0001_initial
"""
from alembic import op

revision = "0001_initial"
down_revision = None
branch_labels = None
depends_on = None

UPGRADE_SQL = """
CREATE EXTENSION IF NOT EXISTS vector;

CREATE TABLE research_projects (
    id uuid PRIMARY KEY,
    name varchar(200) NOT NULL CHECK (length(trim(name)) > 0),
    description text NOT NULL DEFAULT '',
    created_at timestamptz NOT NULL DEFAULT now(),
    updated_at timestamptz NOT NULL DEFAULT now()
);

CREATE TABLE documents (
    id uuid PRIMARY KEY,
    project_id uuid NOT NULL REFERENCES research_projects(id) ON DELETE CASCADE,
    filename varchar(500) NOT NULL,
    file_type varchar(10) NOT NULL CHECK (file_type IN ('pdf','docx','txt','md')),
    size_bytes bigint NOT NULL,
    content_hash char(64) NOT NULL,
    storage_path text NOT NULL,
    status varchar(20) NOT NULL DEFAULT 'pending'
        CHECK (status IN ('pending','processing','ready','failed','needs_ocr')),
    error_message text,
    attempts integer NOT NULL DEFAULT 0,
    page_count integer,
    page_mode varchar(20),
    title text,
    author text,
    published_date date,
    metadata jsonb NOT NULL DEFAULT '{}'::jsonb,
    chunk_count integer NOT NULL DEFAULT 0,
    created_at timestamptz NOT NULL DEFAULT now(),
    processed_at timestamptz,
    CONSTRAINT uq_documents_project_hash UNIQUE (project_id, content_hash),
    CONSTRAINT uq_documents_id_project UNIQUE (id, project_id)
);
CREATE INDEX ix_documents_project ON documents(project_id, created_at);

CREATE TABLE document_pages (
    id bigserial PRIMARY KEY,
    document_id uuid NOT NULL,
    project_id uuid NOT NULL,
    page_number integer NOT NULL CHECK (page_number >= 1),
    text text NOT NULL,
    line_offset integer NOT NULL DEFAULT 0,
    CONSTRAINT fk_pages_document FOREIGN KEY (document_id, project_id)
        REFERENCES documents(id, project_id) ON DELETE CASCADE,
    CONSTRAINT uq_pages_doc_page UNIQUE (document_id, page_number)
);

CREATE TABLE document_chunks (
    id uuid PRIMARY KEY,
    document_id uuid NOT NULL,
    project_id uuid NOT NULL,
    chunk_index integer NOT NULL,
    page_number integer NOT NULL CHECK (page_number >= 1),
    section_title text,
    text text NOT NULL,
    char_start integer NOT NULL,
    char_end integer NOT NULL,
    line_start integer,
    line_end integer,
    text_hash char(64) NOT NULL,
    search_text text NOT NULL,
    tsv tsvector GENERATED ALWAYS AS (to_tsvector('simple'::regconfig, search_text)) STORED,
    embedding vector,
    embedding_model varchar(200),
    created_at timestamptz NOT NULL DEFAULT now(),
    CONSTRAINT fk_chunks_document FOREIGN KEY (document_id, project_id)
        REFERENCES documents(id, project_id) ON DELETE CASCADE,
    CONSTRAINT uq_chunks_doc_index UNIQUE (document_id, chunk_index),
    CONSTRAINT uq_chunks_id_project UNIQUE (id, project_id),
    CONSTRAINT ck_chunks_offsets CHECK (char_end >= char_start)
);
CREATE INDEX ix_chunks_project ON document_chunks(project_id);
CREATE INDEX ix_chunks_doc_page ON document_chunks(document_id, page_number);
CREATE INDEX ix_chunks_tsv ON document_chunks USING gin(tsv);

CREATE TABLE retrieval_runs (
    id uuid PRIMARY KEY,
    project_id uuid NOT NULL REFERENCES research_projects(id) ON DELETE CASCADE,
    purpose varchar(20) NOT NULL,
    query text NOT NULL,
    params jsonb NOT NULL DEFAULT '{}'::jsonb,
    results jsonb NOT NULL DEFAULT '[]'::jsonb,
    sufficient boolean NOT NULL DEFAULT false,
    created_at timestamptz NOT NULL DEFAULT now()
);
CREATE INDEX ix_retrieval_runs_project ON retrieval_runs(project_id, created_at);

CREATE TABLE conversations (
    id uuid PRIMARY KEY,
    project_id uuid NOT NULL REFERENCES research_projects(id) ON DELETE CASCADE,
    title varchar(300) NOT NULL,
    created_at timestamptz NOT NULL DEFAULT now(),
    CONSTRAINT uq_conversations_id_project UNIQUE (id, project_id)
);
CREATE INDEX ix_conversations_project ON conversations(project_id, created_at);

CREATE TABLE messages (
    id uuid PRIMARY KEY,
    conversation_id uuid NOT NULL,
    project_id uuid NOT NULL,
    role varchar(20) NOT NULL CHECK (role IN ('user','assistant')),
    kind varchar(20) NOT NULL DEFAULT 'qa' CHECK (kind IN ('qa','comparison')),
    content text NOT NULL,
    status varchar(30),
    payload jsonb,
    model_info jsonb,
    retrieval_run_id uuid REFERENCES retrieval_runs(id) ON DELETE SET NULL,
    created_at timestamptz NOT NULL DEFAULT now(),
    CONSTRAINT fk_messages_conversation FOREIGN KEY (conversation_id, project_id)
        REFERENCES conversations(id, project_id) ON DELETE CASCADE,
    CONSTRAINT uq_messages_id_project UNIQUE (id, project_id)
);
CREATE INDEX ix_messages_conversation ON messages(conversation_id, created_at);

CREATE TABLE citations (
    id uuid PRIMARY KEY,
    message_id uuid NOT NULL,
    project_id uuid NOT NULL,
    label varchar(20) NOT NULL,
    chunk_id uuid,
    document_id uuid,
    document_name text NOT NULL,
    page_number integer NOT NULL,
    quote text NOT NULL,
    quote_verified boolean NOT NULL DEFAULT false,
    relevance double precision,
    created_at timestamptz NOT NULL DEFAULT now(),
    CONSTRAINT fk_citations_message FOREIGN KEY (message_id, project_id)
        REFERENCES messages(id, project_id) ON DELETE CASCADE,
    -- Same-project guarantee; when the chunk is deleted only chunk_id is nulled (PG15+ syntax)
    CONSTRAINT fk_citations_chunk FOREIGN KEY (chunk_id, project_id)
        REFERENCES document_chunks(id, project_id) ON DELETE SET NULL (chunk_id),
    CONSTRAINT fk_citations_document FOREIGN KEY (document_id, project_id)
        REFERENCES documents(id, project_id) ON DELETE SET NULL (document_id),
    CONSTRAINT uq_citations_message_label UNIQUE (message_id, label)
);
CREATE INDEX ix_citations_message ON citations(message_id);
CREATE INDEX ix_citations_chunk ON citations(chunk_id);

CREATE TABLE research_reports (
    id uuid PRIMARY KEY,
    project_id uuid NOT NULL REFERENCES research_projects(id) ON DELETE CASCADE,
    title varchar(300) NOT NULL,
    question text NOT NULL,
    content_md text NOT NULL,
    generation_mode varchar(20) NOT NULL CHECK (generation_mode IN ('llm','evidence_only')),
    sources jsonb NOT NULL DEFAULT '[]'::jsonb,
    retrieval_run_id uuid REFERENCES retrieval_runs(id) ON DELETE SET NULL,
    created_at timestamptz NOT NULL DEFAULT now(),
    updated_at timestamptz NOT NULL DEFAULT now()
);
CREATE INDEX ix_reports_project ON research_reports(project_id, created_at);
"""

DOWNGRADE_SQL = """
DROP TABLE IF EXISTS research_reports, citations, messages, conversations, retrieval_runs,
    document_chunks, document_pages, documents, research_projects CASCADE;
"""


def upgrade():
    op.execute(UPGRADE_SQL)


def downgrade():
    op.execute(DOWNGRADE_SQL)
