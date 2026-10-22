"""Document ingestion pipeline: validate -> hash/dedupe -> store -> parse -> chunk -> embed -> index."""
from __future__ import annotations

import hashlib
import json
import logging
import shutil
import uuid
from concurrent.futures import ThreadPoolExecutor
from dataclasses import asdict
from pathlib import Path

from sqlalchemy import delete, func, select, update
from sqlalchemy.orm import Session

from app.config import get_settings
from app.db import session_factory
from app.models import Document, DocumentChunk, DocumentPage, utcnow
from app.services.chunking import chunk_pages
from app.services.embeddings import EmbeddingError, get_embedder
from app.services.parsing import NeedsOCR, ParseError, detect_file_type, parse_document
from app.services.text_utils import search_text

log = logging.getLogger(__name__)
_executor = ThreadPoolExecutor(max_workers=2, thread_name_prefix="ingest")


class UploadRejected(Exception):
    def __init__(self, message: str, status_code: int = 400, existing_id: uuid.UUID | None = None):
        super().__init__(message)
        self.status_code = status_code
        self.existing_id = existing_id


def storage_dir_for(project_id: uuid.UUID, document_id: uuid.UUID) -> Path:
    return get_settings().storage_dir / str(project_id) / str(document_id)


def create_document(db: Session, project_id: uuid.UUID, filename: str, data: bytes) -> Document:
    settings = get_settings()
    filename = Path(filename or "").name  # strip any client-supplied directories
    if not filename:
        raise UploadRejected("缺少文件名")
    if len(data) == 0:
        raise UploadRejected(f"{filename}：文件为空（0 字节）")
    max_bytes = settings.max_upload_mb * 1024 * 1024
    if len(data) > max_bytes:
        raise UploadRejected(f"{filename}：文件超过大小上限 {settings.max_upload_mb} MB", status_code=413)
    try:
        file_type = detect_file_type(filename, data[:8])
    except ParseError as exc:
        raise UploadRejected(f"{filename}：{exc}", status_code=415) from exc

    content_hash = hashlib.sha256(data).hexdigest()
    existing = db.scalar(
        select(Document).where(Document.project_id == project_id, Document.content_hash == content_hash)
    )
    if existing:
        raise UploadRejected(
            f"{filename}：与项目中已有文档《{existing.filename}》内容完全相同（重复文件）",
            status_code=409,
            existing_id=existing.id,
        )

    doc_id = uuid.uuid4()
    folder = storage_dir_for(project_id, doc_id)
    folder.mkdir(parents=True, exist_ok=True)
    path = folder / f"original.{file_type}"
    path.write_bytes(data)
    doc = Document(
        id=doc_id,
        project_id=project_id,
        filename=filename,
        file_type=file_type,
        size_bytes=len(data),
        content_hash=content_hash,
        storage_path=str(path),
        status="pending",
        doc_metadata={},
    )
    db.add(doc)
    db.commit()
    return doc


def schedule_processing(document_id: uuid.UUID):
    if get_settings().ingest_sync:
        process_document(document_id)
    else:
        _executor.submit(_safe_process, document_id)


def _safe_process(document_id: uuid.UUID):
    try:
        process_document(document_id)
    except Exception:  # noqa: BLE001 - keep the worker alive; error already recorded
        log.exception("ingestion crashed for %s", document_id)


def _fail(db: Session, doc: Document, status: str, message: str):
    db.rollback()
    db.execute(delete(DocumentChunk).where(DocumentChunk.document_id == doc.id))
    db.execute(delete(DocumentPage).where(DocumentPage.document_id == doc.id))
    db.execute(
        update(Document)
        .where(Document.id == doc.id)
        .values(status=status, error_message=message, chunk_count=0, processed_at=utcnow())
    )
    db.commit()


def _claim(db: Session, document_id: uuid.UUID, force: bool) -> bool:
    """Atomically move a document to 'processing'. Only one worker (in any process) can win,
    so a document is never processed twice concurrently."""
    allowed = ["pending", "ready", "failed", "needs_ocr"] if force else ["pending"]
    claimed = db.execute(
        update(Document)
        .where(Document.id == document_id, Document.status.in_(allowed))
        .values(status="processing", error_message=None, attempts=Document.attempts + 1,
                processing_started_at=utcnow())
        .returning(Document.id)
    ).first()
    db.commit()
    return claimed is not None


def process_document(document_id: uuid.UUID, force: bool = False) -> str:
    """Run the pipeline for one document. Idempotent: previous pages/chunks are replaced.
    `force=True` reprocesses a document that is not pending (used by maintenance/tests)."""
    settings = get_settings()
    db = session_factory()
    try:
        if not _claim(db, document_id, force):
            return "skipped"
        doc = db.get(Document, document_id)
        if doc is None:
            return "missing"

        try:
            data = Path(doc.storage_path).read_bytes()
        except OSError as exc:
            _fail(db, doc, "failed", f"原始文件丢失：{exc}")
            return "failed"

        try:
            parsed = parse_document(doc.file_type, data)
        except NeedsOCR as exc:
            _fail(db, doc, "needs_ocr", str(exc))
            return "needs_ocr"
        except ParseError as exc:
            _fail(db, doc, "failed", str(exc))
            return "failed"
        except Exception as exc:  # noqa: BLE001
            log.exception("unexpected parse error")
            _fail(db, doc, "failed", f"解析时发生未预期错误：{type(exc).__name__}: {exc}")
            return "failed"

        track_lines = parsed.page_mode in ("none", "form_feed")
        chunks = chunk_pages(parsed.pages, settings.chunk_target_chars, settings.chunk_overlap_chars, track_lines)
        if not chunks:
            _fail(db, doc, "failed", "文档没有可分块的文本内容")
            return "failed"

        # Contextual chunk header: document title + section are indexed with each chunk, so a chunk
        # can be found by document-level terms ("初步调查报告") that only appear on another page.
        doc_label = parsed.title or Path(doc.filename).stem
        indexed = [f"{doc_label}\n{c.section_title or ''}\n{c.text}" for c in chunks]
        try:
            embedder = get_embedder()
            vectors = embedder.embed(indexed)
        except EmbeddingError as exc:
            _fail(db, doc, "failed", f"生成向量失败：{exc}")
            return "failed"

        # Persist parsed output (for audit) next to the original.
        folder = Path(doc.storage_path).parent
        (folder / "parsed.json").write_text(
            json.dumps(
                {
                    "page_mode": parsed.page_mode,
                    "title": parsed.title,
                    "author": parsed.author,
                    "published_date": parsed.published_date.isoformat() if parsed.published_date else None,
                    "metadata": parsed.metadata,
                    "warnings": parsed.warnings,
                    "pages": [asdict(p) for p in parsed.pages],
                },
                ensure_ascii=False,
                default=str,
            ),
            encoding="utf-8",
        )

        db.execute(delete(DocumentChunk).where(DocumentChunk.document_id == doc.id))
        db.execute(delete(DocumentPage).where(DocumentPage.document_id == doc.id))
        for p in parsed.pages:
            db.add(
                DocumentPage(
                    document_id=doc.id,
                    project_id=doc.project_id,
                    page_number=p.page_number,
                    text=p.text,
                    line_offset=p.line_offset,
                )
            )
        for idx, (c, vec, idx_text) in enumerate(zip(chunks, vectors, indexed, strict=True)):
            db.add(
                DocumentChunk(
                    document_id=doc.id,
                    project_id=doc.project_id,
                    chunk_index=idx,
                    page_number=c.page_number,
                    section_title=c.section_title,
                    text=c.text,
                    char_start=c.char_start,
                    char_end=c.char_end,
                    line_start=c.line_start,
                    line_end=c.line_end,
                    text_hash=hashlib.sha256(c.text.encode("utf-8")).hexdigest(),
                    search_text=search_text(idx_text),
                    embedding=vec,
                    embedding_model=embedder.name,
                )
            )
        meta = dict(parsed.metadata)
        meta["warnings"] = parsed.warnings
        doc.page_count = len(parsed.pages)
        doc.page_mode = parsed.page_mode
        doc.title = parsed.title
        doc.author = parsed.author
        if doc.published_date is None or (doc.doc_metadata or {}).get("published_date_source") != "user":
            doc.published_date = parsed.published_date
        else:
            meta["published_date_source"] = "user"
        doc.doc_metadata = meta
        doc.chunk_count = len(chunks)
        doc.status = "ready"
        doc.error_message = None
        doc.processed_at = utcnow()
        db.commit()
        return "ready"
    except Exception as exc:
        db.rollback()
        try:
            doc = db.get(Document, document_id)
            if doc is not None:
                _fail(db, doc, "failed", f"处理失败：{type(exc).__name__}: {exc}")
        finally:
            raise
    finally:
        db.close()


def delete_document(db: Session, doc: Document) -> dict:
    """Delete a document with its pages, chunks (incl. vectors) and stored files."""
    chunk_count = db.scalar(select(func.count()).select_from(DocumentChunk).where(DocumentChunk.document_id == doc.id))
    folder = Path(doc.storage_path).parent
    db.delete(doc)  # FK cascades remove pages/chunks; citations keep a snapshot with chunk_id = NULL
    db.commit()
    if folder.exists() and folder.is_relative_to(get_settings().storage_dir):
        shutil.rmtree(folder, ignore_errors=True)
    return {"deleted_chunks": chunk_count or 0, "files_removed": not folder.exists()}


def resume_unfinished():
    """On startup, re-queue pending documents and recover 'processing' jobs that are stale
    (abandoned by a crashed worker). Recent 'processing' jobs may belong to another live
    instance and are left alone."""
    from datetime import timedelta

    cutoff = utcnow() - timedelta(minutes=get_settings().ingest_stale_minutes)
    db = session_factory()
    try:
        db.execute(
            update(Document)
            .where(Document.status == "processing")
            .where((Document.processing_started_at.is_(None)) | (Document.processing_started_at < cutoff))
            .values(status="pending", error_message="上次处理中断，已重新排队")
        )
        db.commit()
        ids = db.scalars(select(Document.id).where(Document.status == "pending")).all()
    finally:
        db.close()
    for doc_id in ids:
        schedule_processing(doc_id)
    return len(ids)
