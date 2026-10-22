import re
import uuid
from pathlib import Path
from urllib.parse import quote

from fastapi import APIRouter, Depends, File, HTTPException, Response, UploadFile
from fastapi.responses import FileResponse
from sqlalchemy import func, select, text
from sqlalchemy.orm import Session

from app.api.deps import get_conversation, get_document, get_project, get_report
from app.config import get_settings
from app.db import get_db
from app.models import (
    Citation,
    Conversation,
    Document,
    DocumentChunk,
    DocumentPage,
    Message,
    ResearchProject,
    ResearchReport,
    RetrievalRun,
)
from app.schemas import (
    AskRequest,
    CompareRequest,
    ConversationOut,
    DocumentOut,
    DocumentUpdate,
    MessageOut,
    ProjectCreate,
    ProjectOut,
    ProjectUpdate,
    ReportCreate,
    ReportOut,
    ReportUpdate,
    SearchRequest,
    UploadResult,
)
from app.services import ingestion
from app.services.compare import compare_documents
from app.services.embeddings import get_embedder
from app.services.llm import llm_status
from app.services.qa import answer_question
from app.services.report import generate_report
from app.services.retrieval import hybrid_search

router = APIRouter(prefix="/api")
PAGE_WINDOW = 4000  # characters of context shown around a cited chunk


# ------------------------------------------------------------------ health
@router.get("/health")
def health(db: Session = Depends(get_db)):
    db.execute(text("SELECT 1"))
    s = get_settings()
    emb = get_embedder()
    return {
        "status": "ok",
        "database": "ok",
        "llm": llm_status(),
        "embedding": {"provider": s.embedding_provider, "model": emb.name, "dim": emb.dim,
                      "semantic": s.embedding_provider != "hash"},
        "retrieval": {"min_term_coverage": s.retrieval_min_term_coverage, "min_vector_sim": s.retrieval_min_vector_sim},
        "max_upload_mb": s.max_upload_mb,
    }


# ------------------------------------------------------------------ projects
def _project_out(db: Session, p: ResearchProject) -> ProjectOut:
    out = ProjectOut.model_validate(p)
    out.document_count = db.scalar(select(func.count()).select_from(Document).where(Document.project_id == p.id)) or 0
    out.conversation_count = db.scalar(select(func.count()).select_from(Conversation).where(Conversation.project_id == p.id)) or 0
    out.report_count = db.scalar(select(func.count()).select_from(ResearchReport).where(ResearchReport.project_id == p.id)) or 0
    return out


@router.get("/projects", response_model=list[ProjectOut])
def list_projects(db: Session = Depends(get_db)):
    projects = db.scalars(select(ResearchProject).order_by(ResearchProject.created_at.desc())).all()
    return [_project_out(db, p) for p in projects]


@router.post("/projects", response_model=ProjectOut, status_code=201)
def create_project(body: ProjectCreate, db: Session = Depends(get_db)):
    if not body.name.strip():
        raise HTTPException(422, "项目名称不能为空")
    p = ResearchProject(name=body.name.strip(), description=body.description.strip())
    db.add(p)
    db.commit()
    return _project_out(db, p)


@router.get("/projects/{project_id}", response_model=ProjectOut)
def read_project(project_id: uuid.UUID, db: Session = Depends(get_db)):
    return _project_out(db, get_project(db, project_id))


@router.patch("/projects/{project_id}", response_model=ProjectOut)
def update_project(project_id: uuid.UUID, body: ProjectUpdate, db: Session = Depends(get_db)):
    p = get_project(db, project_id)
    if body.name is not None:
        p.name = body.name.strip()
    if body.description is not None:
        p.description = body.description.strip()
    db.commit()
    return _project_out(db, p)


@router.delete("/projects/{project_id}", status_code=204)
def delete_project(project_id: uuid.UUID, db: Session = Depends(get_db)):
    p = get_project(db, project_id)
    if db.scalar(select(func.count()).select_from(Document)
                 .where(Document.project_id == p.id, Document.status == "processing")):
        raise HTTPException(409, "项目中有文档正在处理，请等待处理完成后再删除")
    for doc in db.scalars(select(Document).where(Document.project_id == p.id)).all():
        ingestion.delete_document(db, doc)
    db.delete(p)
    db.commit()
    folder = get_settings().storage_dir / str(project_id)
    if folder.exists():
        import shutil

        shutil.rmtree(folder, ignore_errors=True)
    return Response(status_code=204)


# ------------------------------------------------------------------ documents
@router.get("/projects/{project_id}/documents", response_model=list[DocumentOut])
def list_documents(project_id: uuid.UUID, db: Session = Depends(get_db)):
    get_project(db, project_id)
    return db.scalars(select(Document).where(Document.project_id == project_id).order_by(Document.created_at)).all()


@router.post("/projects/{project_id}/documents", response_model=list[UploadResult])
async def upload_documents(project_id: uuid.UUID, files: list[UploadFile] = File(...), db: Session = Depends(get_db)):
    get_project(db, project_id)
    max_bytes = get_settings().max_upload_mb * 1024 * 1024
    results: list[UploadResult] = []
    to_process = []
    for f in files:
        data = await f.read(max_bytes + 1)
        try:
            doc = ingestion.create_document(db, project_id, f.filename or "", data)
            to_process.append(doc.id)
            results.append(UploadResult(filename=doc.filename, ok=True, document=DocumentOut.model_validate(doc)))
        except ingestion.UploadRejected as exc:
            db.rollback()
            results.append(UploadResult(filename=f.filename or "", ok=False, error=str(exc),
                                        status_code=exc.status_code, existing_document_id=exc.existing_id))
    for doc_id in to_process:
        ingestion.schedule_processing(doc_id)
    if not any(r.ok for r in results) and len(results) == 1:
        r = results[0]
        raise HTTPException(r.status_code or 400, {"message": r.error, "existing_document_id": str(r.existing_document_id) if r.existing_document_id else None})
    return results


@router.get("/projects/{project_id}/documents/{document_id}", response_model=DocumentOut)
def read_document(project_id: uuid.UUID, document_id: uuid.UUID, db: Session = Depends(get_db)):
    return get_document(db, project_id, document_id)


@router.patch("/projects/{project_id}/documents/{document_id}", response_model=DocumentOut)
def update_document(project_id: uuid.UUID, document_id: uuid.UUID, body: DocumentUpdate, db: Session = Depends(get_db)):
    doc = get_document(db, project_id, document_id)
    fields = body.model_fields_set
    if "published_date" in fields:
        doc.published_date = body.published_date
        doc.doc_metadata = {**(doc.doc_metadata or {}), "published_date_source": "user"}
    if "title" in fields:
        doc.title = body.title
    db.commit()
    return doc


@router.delete("/projects/{project_id}/documents/{document_id}")
def remove_document(project_id: uuid.UUID, document_id: uuid.UUID, db: Session = Depends(get_db)):
    doc = get_document(db, project_id, document_id)
    if doc.status == "processing":
        raise HTTPException(409, "文档正在处理中，请稍后再删除")
    return ingestion.delete_document(db, doc)


@router.post("/projects/{project_id}/documents/{document_id}/retry", response_model=DocumentOut)
def retry_document(project_id: uuid.UUID, document_id: uuid.UUID, db: Session = Depends(get_db)):
    doc = get_document(db, project_id, document_id)
    if doc.status not in ("failed", "needs_ocr"):
        raise HTTPException(409, f"只有失败的文档可以重试（当前状态：{doc.status}）")
    doc.status = "pending"
    doc.error_message = None
    db.commit()
    ingestion.schedule_processing(doc.id)
    db.refresh(doc)
    return doc


@router.get("/projects/{project_id}/documents/{document_id}/file")
def download_original(project_id: uuid.UUID, document_id: uuid.UUID, db: Session = Depends(get_db)):
    doc = get_document(db, project_id, document_id)
    path = Path(doc.storage_path)
    if not path.exists():
        raise HTTPException(410, "原始文件已不存在")
    media = {"pdf": "application/pdf", "txt": "text/plain; charset=utf-8", "md": "text/markdown; charset=utf-8",
             "docx": "application/vnd.openxmlformats-officedocument.wordprocessingml.document"}[doc.file_type]
    disposition = "inline" if doc.file_type in ("pdf", "txt", "md") else "attachment"
    return FileResponse(path, media_type=media,
                        headers={"Content-Disposition": f"{disposition}; filename*=UTF-8''{quote(doc.filename)}"})


@router.get("/projects/{project_id}/documents/{document_id}/pages/{page_number}")
def read_page(project_id: uuid.UUID, document_id: uuid.UUID, page_number: int, db: Session = Depends(get_db)):
    doc = get_document(db, project_id, document_id)
    page = db.scalar(select(DocumentPage).where(DocumentPage.document_id == doc.id, DocumentPage.page_number == page_number))
    if page is None:
        raise HTTPException(404, f"第 {page_number} 页不存在")
    return {"document_id": str(doc.id), "page_number": page.page_number, "page_count": doc.page_count,
            "page_mode": doc.page_mode, "text": page.text, "line_offset": page.line_offset}


@router.get("/projects/{project_id}/documents/{document_id}/chunks")
def list_chunks(project_id: uuid.UUID, document_id: uuid.UUID, page: int | None = None, db: Session = Depends(get_db)):
    doc = get_document(db, project_id, document_id)
    q = select(DocumentChunk).where(DocumentChunk.document_id == doc.id, DocumentChunk.project_id == project_id)
    if page is not None:
        q = q.where(DocumentChunk.page_number == page)
    rows = db.scalars(q.order_by(DocumentChunk.chunk_index)).all()
    return [{"id": str(c.id), "chunk_index": c.chunk_index, "page_number": c.page_number, "section_title": c.section_title,
             "char_start": c.char_start, "char_end": c.char_end, "line_start": c.line_start, "line_end": c.line_end,
             "text": c.text, "embedding_model": c.embedding_model} for c in rows]


# ------------------------------------------------------------------ evidence lookup
def _source_view(db: Session, project_id: uuid.UUID, chunk_id: uuid.UUID | None) -> dict | None:
    if chunk_id is None:
        return None
    chunk = db.scalar(select(DocumentChunk).where(DocumentChunk.id == chunk_id, DocumentChunk.project_id == project_id))
    if chunk is None:
        return None
    doc = db.get(Document, chunk.document_id)
    # Return a window of the page around the chunk so very long pages (e.g. a large text file
    # without page breaks) stay readable; offsets are rebased to the window.
    win_start = max(0, chunk.char_start - PAGE_WINDOW)
    row = db.execute(
        select(func.substr(DocumentPage.text, win_start + 1, (chunk.char_end - win_start) + PAGE_WINDOW),
               func.length(DocumentPage.text))
        .where(DocumentPage.document_id == doc.id, DocumentPage.page_number == chunk.page_number)
    ).first()
    page_text, page_len = (row[0], row[1]) if row else (None, 0)
    return {
        "chunk": {"id": str(chunk.id), "page_number": chunk.page_number, "section_title": chunk.section_title,
                  "text": chunk.text, "char_start": chunk.char_start - win_start, "char_end": chunk.char_end - win_start,
                  "line_start": chunk.line_start, "line_end": chunk.line_end},
        "document": DocumentOut.model_validate(doc).model_dump(mode="json", by_alias=True),
        "page_text": page_text,
        "page_text_truncated": {"before": win_start > 0, "after": page_len > win_start + len(page_text or "")},
        "file_url": f"/api/projects/{project_id}/documents/{doc.id}/file",
        "pdf_page_url": (f"/api/projects/{project_id}/documents/{doc.id}/file#page={chunk.page_number}"
                         if doc.file_type == "pdf" else None),
    }


@router.get("/projects/{project_id}/citations/{citation_id}")
def read_citation(project_id: uuid.UUID, citation_id: uuid.UUID, db: Session = Depends(get_db)):
    get_project(db, project_id)
    cit = db.scalar(select(Citation).where(Citation.id == citation_id, Citation.project_id == project_id))
    if cit is None:
        raise HTTPException(404, "引用不存在或不属于当前项目")
    source = _source_view(db, project_id, cit.chunk_id)
    return {
        "citation": {"id": str(cit.id), "label": cit.label, "message_id": str(cit.message_id),
                     "document_name": cit.document_name, "page_number": cit.page_number, "quote": cit.quote,
                     "quote_verified": cit.quote_verified, "relevance": cit.relevance},
        "source_available": source is not None,
        "source": source,
        "notice": None if source else "该引用对应的源文档已被删除，仅保留引用快照",
    }


@router.get("/projects/{project_id}/chunks/{chunk_id}")
def read_chunk(project_id: uuid.UUID, chunk_id: uuid.UUID, db: Session = Depends(get_db)):
    get_project(db, project_id)
    source = _source_view(db, project_id, chunk_id)
    if source is None:
        raise HTTPException(404, "文本块不存在或不属于当前项目")
    return source


# ------------------------------------------------------------------ retrieval
@router.post("/projects/{project_id}/search")
def search(project_id: uuid.UUID, body: SearchRequest, db: Session = Depends(get_db)):
    get_project(db, project_id)
    if body.document_ids:
        for d in body.document_ids:
            get_document(db, project_id, d)
    outcome = hybrid_search(db, project_id, body.query, top_k=body.top_k, document_ids=body.document_ids,
                            page_from=body.page_from, page_to=body.page_to, purpose="search",
                            min_term_coverage=body.min_term_coverage, min_vector_sim=body.min_vector_sim)
    db.commit()
    return {"query": outcome.query, "terms": outcome.terms, "sufficient": outcome.sufficient,
            "params": outcome.params, "retrieval_run_id": str(outcome.run_id),
            "results": [r.to_dict() for r in outcome.results]}


@router.get("/projects/{project_id}/retrieval-runs/{run_id}")
def read_retrieval_run(project_id: uuid.UUID, run_id: uuid.UUID, db: Session = Depends(get_db)):
    run = db.scalar(select(RetrievalRun).where(RetrievalRun.id == run_id, RetrievalRun.project_id == project_id))
    if run is None:
        raise HTTPException(404, "检索记录不存在")
    return {"id": str(run.id), "purpose": run.purpose, "query": run.query, "params": run.params,
            "results": run.results, "sufficient": run.sufficient, "created_at": run.created_at.isoformat()}


# ------------------------------------------------------------------ QA + comparison
@router.get("/projects/{project_id}/conversations", response_model=list[ConversationOut])
def list_conversations(project_id: uuid.UUID, db: Session = Depends(get_db)):
    get_project(db, project_id)
    return db.scalars(select(Conversation).where(Conversation.project_id == project_id)
                      .order_by(Conversation.created_at.desc())).all()


@router.get("/projects/{project_id}/conversations/{conversation_id}/messages", response_model=list[MessageOut])
def list_messages(project_id: uuid.UUID, conversation_id: uuid.UUID, db: Session = Depends(get_db)):
    conv = get_conversation(db, project_id, conversation_id)
    return db.scalars(select(Message).where(Message.conversation_id == conv.id, Message.project_id == project_id)
                      .order_by(Message.created_at, Message.role.desc())).all()


@router.delete("/projects/{project_id}/conversations/{conversation_id}", status_code=204)
def delete_conversation(project_id: uuid.UUID, conversation_id: uuid.UUID, db: Session = Depends(get_db)):
    db.delete(get_conversation(db, project_id, conversation_id))
    db.commit()
    return Response(status_code=204)


def _require_ready_docs(db: Session, project_id: uuid.UUID, document_ids):
    if document_ids:
        for d in document_ids:
            get_document(db, project_id, d)
    n = db.scalar(select(func.count()).select_from(Document)
                  .where(Document.project_id == project_id, Document.status == "ready")) or 0
    return n


@router.post("/projects/{project_id}/ask", response_model=MessageOut)
def ask(project_id: uuid.UUID, body: AskRequest, db: Session = Depends(get_db)):
    get_project(db, project_id)
    _require_ready_docs(db, project_id, body.document_ids)
    try:
        return answer_question(db, project_id, body.question, body.conversation_id, body.document_ids)
    except LookupError as exc:
        raise HTTPException(404, str(exc)) from exc


@router.post("/projects/{project_id}/compare", response_model=MessageOut)
def compare(project_id: uuid.UUID, body: CompareRequest, db: Session = Depends(get_db)):
    get_project(db, project_id)
    _require_ready_docs(db, project_id, body.document_ids)
    try:
        return compare_documents(db, project_id, body.question, body.document_ids)
    except ValueError as exc:
        raise HTTPException(400, str(exc)) from exc


# ------------------------------------------------------------------ reports
@router.get("/projects/{project_id}/reports", response_model=list[ReportOut])
def list_reports(project_id: uuid.UUID, db: Session = Depends(get_db)):
    get_project(db, project_id)
    return db.scalars(select(ResearchReport).where(ResearchReport.project_id == project_id)
                      .order_by(ResearchReport.created_at.desc())).all()


@router.post("/projects/{project_id}/reports", response_model=ReportOut, status_code=201)
def create_report(project_id: uuid.UUID, body: ReportCreate, db: Session = Depends(get_db)):
    get_project(db, project_id)
    return generate_report(db, project_id, body.question, body.title)


@router.get("/projects/{project_id}/reports/{report_id}", response_model=ReportOut)
def read_report(project_id: uuid.UUID, report_id: uuid.UUID, db: Session = Depends(get_db)):
    return get_report(db, project_id, report_id)


@router.put("/projects/{project_id}/reports/{report_id}", response_model=ReportOut)
def update_report(project_id: uuid.UUID, report_id: uuid.UUID, body: ReportUpdate, db: Session = Depends(get_db)):
    rep = get_report(db, project_id, report_id)
    if body.title is not None:
        rep.title = body.title
    if body.content_md is not None:
        rep.content_md = body.content_md
    db.commit()
    return rep


@router.delete("/projects/{project_id}/reports/{report_id}", status_code=204)
def delete_report(project_id: uuid.UUID, report_id: uuid.UUID, db: Session = Depends(get_db)):
    db.delete(get_report(db, project_id, report_id))
    db.commit()
    return Response(status_code=204)


@router.get("/projects/{project_id}/reports/{report_id}/export")
def export_report(project_id: uuid.UUID, report_id: uuid.UUID, format: str = "md", db: Session = Depends(get_db)):
    rep = get_report(db, project_id, report_id)
    if format != "md":
        raise HTTPException(400, "目前仅支持 Markdown（format=md）导出")
    safe = re.sub(r"[\\/:*?\"<>|\s]+", "_", rep.title).strip("_")[:80] or "report"
    return Response(
        content=rep.content_md.encode("utf-8"),
        media_type="text/markdown; charset=utf-8",
        headers={"Content-Disposition": f"attachment; filename=\"report.md\"; filename*=UTF-8''{quote(safe)}.md"},
    )
