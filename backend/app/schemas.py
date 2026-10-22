import uuid
from datetime import date, datetime

from pydantic import BaseModel, ConfigDict, Field


class ORM(BaseModel):
    model_config = ConfigDict(from_attributes=True)


class ProjectCreate(BaseModel):
    name: str = Field(min_length=1, max_length=200)
    description: str = Field(default="", max_length=5000)


class ProjectUpdate(BaseModel):
    name: str | None = Field(default=None, min_length=1, max_length=200)
    description: str | None = Field(default=None, max_length=5000)


class ProjectOut(ORM):
    id: uuid.UUID
    name: str
    description: str
    created_at: datetime
    document_count: int = 0
    conversation_count: int = 0
    report_count: int = 0


class DocumentOut(ORM):
    id: uuid.UUID
    project_id: uuid.UUID
    filename: str
    file_type: str
    size_bytes: int
    content_hash: str
    status: str
    error_message: str | None
    attempts: int
    page_count: int | None
    page_mode: str | None
    title: str | None
    author: str | None
    published_date: date | None
    chunk_count: int
    doc_metadata: dict = Field(serialization_alias="metadata")
    created_at: datetime
    processed_at: datetime | None


class DocumentUpdate(BaseModel):
    published_date: date | None = None
    title: str | None = Field(default=None, max_length=500)


class UploadResult(BaseModel):
    filename: str
    ok: bool
    document: DocumentOut | None = None
    error: str | None = None
    status_code: int | None = None
    existing_document_id: uuid.UUID | None = None


class SearchRequest(BaseModel):
    query: str = Field(min_length=1, max_length=2000)
    top_k: int = Field(default=8, ge=1, le=50)
    document_ids: list[uuid.UUID] | None = None
    page_from: int | None = Field(default=None, ge=1)
    page_to: int | None = Field(default=None, ge=1)
    min_term_coverage: float | None = Field(default=None, ge=0, le=1)
    min_vector_sim: float | None = Field(default=None, ge=-1, le=1)


class AskRequest(BaseModel):
    question: str = Field(min_length=1, max_length=4000)
    conversation_id: uuid.UUID | None = None
    document_ids: list[uuid.UUID] | None = None


class CompareRequest(BaseModel):
    question: str = Field(min_length=1, max_length=4000)
    document_ids: list[uuid.UUID] | None = None


class ReportCreate(BaseModel):
    question: str = Field(min_length=1, max_length=4000)
    title: str | None = Field(default=None, max_length=300)


class ReportUpdate(BaseModel):
    title: str | None = Field(default=None, min_length=1, max_length=300)
    content_md: str | None = None


class ReportOut(ORM):
    id: uuid.UUID
    project_id: uuid.UUID
    title: str
    question: str
    content_md: str
    generation_mode: str
    sources: list
    retrieval_run_id: uuid.UUID | None
    created_at: datetime
    updated_at: datetime


class MessageOut(ORM):
    id: uuid.UUID
    conversation_id: uuid.UUID
    role: str
    kind: str
    content: str
    status: str | None
    payload: dict | None
    model_info: dict | None
    retrieval_run_id: uuid.UUID | None
    created_at: datetime


class ConversationOut(ORM):
    id: uuid.UUID
    project_id: uuid.UUID
    title: str
    created_at: datetime
