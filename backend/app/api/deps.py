"""Project-scoped lookups. Every child resource is fetched with BOTH its id and the project id
from the URL, so an id from another project yields 404 instead of leaking data."""
import uuid

from fastapi import HTTPException
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.models import Conversation, Document, ResearchProject, ResearchReport


def get_project(db: Session, project_id: uuid.UUID) -> ResearchProject:
    project = db.get(ResearchProject, project_id)
    if project is None:
        raise HTTPException(404, "研究项目不存在")
    return project


def get_document(db: Session, project_id: uuid.UUID, document_id: uuid.UUID) -> Document:
    doc = db.scalar(select(Document).where(Document.id == document_id, Document.project_id == project_id))
    if doc is None:
        raise HTTPException(404, "文档不存在或不属于当前项目")
    return doc


def get_conversation(db: Session, project_id: uuid.UUID, conversation_id: uuid.UUID) -> Conversation:
    conv = db.scalar(
        select(Conversation).where(Conversation.id == conversation_id, Conversation.project_id == project_id)
    )
    if conv is None:
        raise HTTPException(404, "对话不存在或不属于当前项目")
    return conv


def get_report(db: Session, project_id: uuid.UUID, report_id: uuid.UUID) -> ResearchReport:
    rep = db.scalar(
        select(ResearchReport).where(ResearchReport.id == report_id, ResearchReport.project_id == project_id)
    )
    if rep is None:
        raise HTTPException(404, "报告不存在或不属于当前项目")
    return rep
