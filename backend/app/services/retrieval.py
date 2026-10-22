"""Hybrid retrieval: PostgreSQL full-text (keyword) + pgvector (semantic) fused with RRF.

Evidence sufficiency is not decided by vector similarity alone: a chunk passes the evidence
threshold if enough of the query's content terms occur in it, or if its vector similarity is
very high. Both thresholds are configurable and recorded with every retrieval run.
"""
from __future__ import annotations

import math
import uuid
from dataclasses import asdict, dataclass, field

from sqlalchemy import text
from sqlalchemy.orm import Session

from app.config import get_settings
from app.models import RetrievalRun
from app.services.embeddings import get_embedder
from app.services.text_utils import boundary_bigrams, content_terms, tokenize, tsquery_or

RRF_K = 60


def term_stats(db: Session, project_id: uuid.UUID, terms: list[str]) -> dict[str, tuple[int, float]]:
    """BM25-style IDF of each query term over the project's ready chunks.

    Coverage is IDF-weighted so that terms present almost everywhere (e.g. a product name that
    appears in every document) cannot by themselves make a chunk count as evidence."""
    if not terms:
        return {}
    rows = db.execute(
        text(
            "WITH scope AS (SELECT c.tsv FROM document_chunks c JOIN documents d "
            "ON d.id = c.document_id AND d.project_id = c.project_id "
            "WHERE c.project_id = :pid AND d.status = 'ready') "
            "SELECT t, (SELECT count(*) FROM scope WHERE scope.tsv @@ to_tsquery('simple', quote_literal(t))), "
            "(SELECT count(*) FROM scope) FROM unnest(CAST(:terms AS text[])) AS t"
        ),
        {"pid": project_id, "terms": terms},
    ).all()
    return {term: (df, math.log(1.0 + (n - df + 0.5) / (df + 0.5))) for term, df, n in rows}


@dataclass
class Relevance:
    score: float = 0.0
    rrf: float = 0.0
    keyword_rank: int | None = None
    keyword_score: float | None = None
    vector_rank: int | None = None
    vector_similarity: float | None = None
    term_coverage: float = 0.0
    matched_terms: list[str] = field(default_factory=list)
    passes_threshold: bool = False


@dataclass
class SearchResult:
    chunk_id: str
    document_id: str
    document_name: str
    page_number: int
    page_mode: str | None
    section_title: str | None
    text: str
    char_start: int
    char_end: int
    line_start: int | None
    line_end: int | None
    published_date: str | None
    relevance: Relevance

    def to_dict(self) -> dict:
        return asdict(self)


@dataclass
class RetrievalOutcome:
    query: str
    terms: list[str]
    results: list[SearchResult]
    sufficient: bool
    params: dict
    run_id: uuid.UUID | None = None

    @property
    def evidence(self) -> list[SearchResult]:
        return [r for r in self.results if r.relevance.passes_threshold]


def _filters(document_ids, page_from, page_to) -> tuple[str, dict]:
    clauses, params = [], {}
    if document_ids:
        clauses.append("c.document_id = ANY(:doc_ids)")
        params["doc_ids"] = [uuid.UUID(str(d)) for d in document_ids]
    if page_from is not None:
        clauses.append("c.page_number >= :page_from")
        params["page_from"] = page_from
    if page_to is not None:
        clauses.append("c.page_number <= :page_to")
        params["page_to"] = page_to
    return ("".join(f" AND {c}" for c in clauses)), params


def hybrid_search(
    db: Session,
    project_id: uuid.UUID,
    query: str,
    *,
    top_k: int | None = None,
    document_ids: list | None = None,
    page_from: int | None = None,
    page_to: int | None = None,
    purpose: str = "search",
    save: bool = True,
    min_term_coverage: float | None = None,
    min_vector_sim: float | None = None,
) -> RetrievalOutcome:
    s = get_settings()
    top_k = top_k or s.retrieval_top_k
    n_candidates = max(s.retrieval_candidates, top_k * 3)
    min_cov = s.retrieval_min_term_coverage if min_term_coverage is None else min_term_coverage
    min_sim = s.retrieval_min_vector_sim if min_vector_sim is None else min_vector_sim
    terms = content_terms(query)
    stats = term_stats(db, project_id, terms)
    dropped = boundary_bigrams(query, {t for t, (df, _) in stats.items() if df > 0})
    terms = [t for t in terms if t not in dropped]
    idf = {t: stats[t][1] for t in terms}
    extra_sql, extra_params = _filters(document_ids, page_from, page_to)
    base_params = {"pid": project_id, "n": n_candidates, **extra_params}
    scope = (
        "FROM document_chunks c JOIN documents d ON d.id = c.document_id AND d.project_id = c.project_id "
        "WHERE c.project_id = :pid AND d.status = 'ready'" + extra_sql
    )

    keyword_hits: list[tuple[uuid.UUID, float]] = []
    if terms:
        rows = db.execute(
            text(
                "SELECT c.id, ts_rank_cd(c.tsv, q, 32) AS score "
                + scope.replace("WHERE", ", to_tsquery('simple', :tsq) q WHERE", 1)
                + " AND c.tsv @@ q ORDER BY score DESC, c.id LIMIT :n"
            ),
            {**base_params, "tsq": tsquery_or(terms)},
        ).all()
        keyword_hits = [(r[0], float(r[1])) for r in rows]

    embedder = get_embedder()
    qvec = embedder.embed([query])[0]
    vec_literal = "[" + ",".join(f"{v:.6f}" for v in qvec) + "]"
    rows = db.execute(
        text(
            "SELECT c.id, 1 - (c.embedding <=> CAST(:qv AS vector)) AS sim "
            + scope
            + " AND c.embedding IS NOT NULL AND c.embedding_model = :model "
            "ORDER BY c.embedding <=> CAST(:qv AS vector), c.id LIMIT :n"
        ),
        {**base_params, "qv": vec_literal, "model": embedder.name},
    ).all()
    vector_hits = [(r[0], float(r[1])) for r in rows]

    # Reciprocal-rank fusion over the union of candidates.
    rel: dict[uuid.UUID, Relevance] = {}
    for rank, (cid, score) in enumerate(keyword_hits, 1):
        r = rel.setdefault(cid, Relevance())
        r.keyword_rank, r.keyword_score = rank, round(score, 6)
        r.rrf += 1.0 / (RRF_K + rank)
    for rank, (cid, sim) in enumerate(vector_hits, 1):
        r = rel.setdefault(cid, Relevance())
        r.vector_rank, r.vector_similarity = rank, round(sim, 6)
        r.rrf += 1.0 / (RRF_K + rank)

    results: list[SearchResult] = []
    if rel:
        rows = db.execute(
            text(
                "SELECT c.id, c.document_id, d.filename, c.page_number, d.page_mode, c.section_title, c.text, "
                "c.char_start, c.char_end, c.line_start, c.line_end, d.published_date, c.text_hash, c.search_text "
                "FROM document_chunks c JOIN documents d ON d.id = c.document_id AND d.project_id = c.project_id "
                "WHERE c.project_id = :pid AND c.id = ANY(:ids)"
            ),
            {"pid": project_id, "ids": list(rel.keys())},
        ).all()
        max_rrf = max(r.rrf for r in rel.values()) or 1.0
        idf_total = sum(idf.values()) or 1.0
        seen_hash: dict[tuple, SearchResult] = {}
        for row in rows:
            r = rel[row.id]
            chunk_tokens = set(row.search_text.split())
            matched = [t for t in terms if t in chunk_tokens]
            r.matched_terms = matched
            r.term_coverage = round(sum(idf[t] for t in matched) / idf_total, 4) if terms else 0.0
            sim = r.vector_similarity or 0.0
            r.passes_threshold = r.term_coverage >= min_cov or sim >= min_sim
            r.score = round(0.5 * (r.rrf / max_rrf) + 0.3 * r.term_coverage + 0.2 * max(sim, 0.0), 6)
            res = SearchResult(
                chunk_id=str(row.id),
                document_id=str(row.document_id),
                document_name=row.filename,
                page_number=row.page_number,
                page_mode=row.page_mode,
                section_title=row.section_title,
                text=row.text,
                char_start=row.char_start,
                char_end=row.char_end,
                line_start=row.line_start,
                line_end=row.line_end,
                published_date=row.published_date.isoformat() if row.published_date else None,
                relevance=r,
            )
            # De-duplicate identical text within the same document (e.g. repeated boilerplate).
            key = (res.document_id, row.text_hash)
            if key in seen_hash and seen_hash[key].relevance.score >= r.score:
                continue
            seen_hash[key] = res
        results = sorted(seen_hash.values(), key=lambda x: (-x.relevance.score, x.chunk_id))[:top_k]

    sufficient = any(r.relevance.passes_threshold for r in results)
    params = {
        "top_k": top_k,
        "candidates": n_candidates,
        "min_term_coverage": min_cov,
        "min_vector_sim": min_sim,
        "embedding_model": embedder.name,
        "document_ids": [str(d) for d in document_ids] if document_ids else None,
        "page_from": page_from,
        "page_to": page_to,
        "query_terms": terms,
        "coverage_weighting": "idf",
        "dropped_boundary_terms": sorted(dropped),
        "keyword_candidates": len(keyword_hits),
        "vector_candidates": len(vector_hits),
    }
    outcome = RetrievalOutcome(query=query, terms=terms, results=results, sufficient=sufficient, params=params)
    if save:
        run = RetrievalRun(
            project_id=project_id,
            purpose=purpose,
            query=query,
            params=params,
            sufficient=sufficient,
            results=[
                {
                    "chunk_id": r.chunk_id,
                    "document_id": r.document_id,
                    "document_name": r.document_name,
                    "page_number": r.page_number,
                    "relevance": asdict(r.relevance),
                    "preview": r.text[:160],
                }
                for r in results
            ],
        )
        db.add(run)
        db.flush()
        outcome.run_id = run.id
    return outcome


__all__ = ["hybrid_search", "RetrievalOutcome", "SearchResult", "Relevance", "tokenize"]
