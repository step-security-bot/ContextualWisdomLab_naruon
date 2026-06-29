from fastapi import APIRouter, Depends, HTTPException
import datetime
import logging
from pydantic import BaseModel, Field
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select, func, union_all
from db.session import get_db, get_readonly_db
from db.models import Email, Attachment
from services.embedding import (
    STORAGE_EMBEDDING_DIMENSION,
    fit_embedding_vector,
    generate_embeddings,
)
from api.auth import AuthContext, get_auth_context
from services.exceptions import EmbeddingGenerationError
from services.llm_provider_selection import resolve_runtime_llm_provider

router = APIRouter(prefix="/api")
logger = logging.getLogger(__name__)
SEARCH_VECTOR_DIMENSIONS = STORAGE_EMBEDDING_DIMENSION


class SearchRequest(BaseModel):
    query: str
    limit: int = Field(default=10, ge=1, le=50)


class SearchResultItem(BaseModel):
    id: int
    source_message_id: str | None = None
    subject: str | None
    sender: str
    date: datetime.datetime
    snippet: str
    thread_id: str | None = None
    reply_count: int = 1
    score: float


class SearchResponse(BaseModel):
    results: list[SearchResultItem]


def thread_group_key():
    normalized_thread_id = func.nullif(
        func.btrim(func.btrim(Email.thread_id), "<>"), ""
    )
    normalized_message_id = func.nullif(
        func.btrim(func.btrim(Email.message_id), "<>"), ""
    )
    return func.coalesce(normalized_thread_id, normalized_message_id)


def _search_score(text_column, embedding_column, query: str, query_embedding):
    fts_score = func.ts_rank_cd(
        func.to_tsvector("english", text_column),
        func.plainto_tsquery("english", query),
    )
    if query_embedding is None:
        return fts_score
    vector_distance = embedding_column.cosine_distance(query_embedding)
    return fts_score - vector_distance


def build_email_search_stmt(query: str, query_embedding, owner_filters):
    search_score = _search_score(
        Email.body,
        Email.embedding,
        query,
        query_embedding,
    )

    return (
        select(
            Email.id,
            Email.message_id.label("source_message_id"),
            Email.subject,
            Email.sender,
            Email.date,
            thread_group_key().label("thread_id"),
            Email.body.label("content"),
            search_score.label("score"),
        )
        .select_from(Email)
        .where(*owner_filters)
    )


def build_attachment_search_stmt(query: str, query_embedding, owner_filters):
    search_score = _search_score(
        Attachment.content,
        Attachment.embedding,
        query,
        query_embedding,
    )

    return (
        select(
            Email.id,
            Email.message_id.label("source_message_id"),
            Email.subject,
            Email.sender,
            Email.date,
            thread_group_key().label("thread_id"),
            Attachment.content.label("content"),
            search_score.label("score"),
        )
        .select_from(Attachment)
        .join(Email, Attachment.email_id == Email.id)
        .where(*owner_filters)
    )


def process_search_results(
    rows, limit: int, thread_reply_counts: dict[str, int]
) -> list[SearchResultItem]:
    search_results = []
    seen_ids = set()
    for row in rows:
        if row.id in seen_ids:
            continue
        seen_ids.add(row.id)

        score = row.score
        snippet_source = row.content or ""
        snippet = (
            snippet_source[:200] + "..."
            if len(snippet_source) > 200
            else snippet_source
        )

        search_results.append(
            SearchResultItem(
                id=row.id,
                source_message_id=row.source_message_id,
                subject=row.subject,
                sender=row.sender,
                date=row.date,
                snippet=snippet,
                thread_id=row.thread_id,
                reply_count=thread_reply_counts.get(row.thread_id, 1)
                if row.thread_id
                else 1,
                score=float(score) if score is not None else 0.0,
            )
        )

        if len(search_results) >= limit:
            break

    return search_results


@router.post("/search", response_model=SearchResponse)
async def hybrid_search(
    request: SearchRequest,
    user_id: str | None = None,
    config_db: AsyncSession = Depends(get_db),
    search_db: AsyncSession = Depends(get_readonly_db),
    auth_context: AuthContext = Depends(get_auth_context),
):
    if user_id and user_id != auth_context.user_id:
        raise HTTPException(status_code=403, detail="Not authorized")
    target_user_id = user_id or auth_context.user_id

    if not request.query.strip():
        return SearchResponse(results=[])

    try:
        runtime_provider = await resolve_runtime_llm_provider(
            config_db,
            user_id=target_user_id,
            organization_id=auth_context.organization_id,
        )
        if runtime_provider is None:
            raise HTTPException(status_code=400, detail="OpenAI API key not configured")

        query_embedding = None
        try:
            embeddings = await generate_embeddings(
                [request.query],
                runtime_provider.api_key,
                base_url=runtime_provider.base_url,
                model=runtime_provider.embedding_model,
            )
            query_embedding = (
                fit_embedding_vector(embeddings[0], SEARCH_VECTOR_DIMENSIONS)
                if embeddings
                else None
            )
        except EmbeddingGenerationError:
            logger.info("Search embedding unavailable; using full-text search only")

        owner_filters = Email.owner_filters(
            target_user_id, auth_context.organization_id
        )
        stmt_email = build_email_search_stmt(
            request.query, query_embedding, owner_filters
        )
        stmt_att = build_attachment_search_stmt(
            request.query, query_embedding, owner_filters
        )

        combined = union_all(stmt_email, stmt_att).cte("combined_search")

        stmt = (
            select(
                combined.c.id,
                combined.c.source_message_id,
                combined.c.subject,
                combined.c.sender,
                combined.c.date,
                combined.c.thread_id,
                combined.c.content,
                combined.c.score,
            )
            .order_by(combined.c.score.desc())
            .limit(request.limit * 2)
        )

        result = await search_db.execute(stmt)
        rows = result.all()

        # ⚡ Bolt Optimization: Lazy thread reply counts
        # Impact: Prevents massive N+1 full-table aggregation on the Email table.
        # Fetching reply counts only for the matched search threads drastically reduces DB load.
        thread_reply_counts = {}
        matched_thread_ids = {row.thread_id for row in rows if row.thread_id}
        if matched_thread_ids:
            thread_key_expr = thread_group_key()
            counts_stmt = (
                select(thread_key_expr, func.count(Email.id))
                .select_from(Email)
                .where(*owner_filters, thread_key_expr.in_(matched_thread_ids))
                .group_by(thread_key_expr)
            )
            counts_result = await search_db.execute(counts_stmt)
            thread_reply_counts = {t_id: count for t_id, count in counts_result.all()}

        search_results = process_search_results(
            rows, request.limit, thread_reply_counts
        )

        return SearchResponse(results=search_results)
    except HTTPException:
        raise
    except Exception as e:
        logger.error("Search failed", exc_info=True)
        raise HTTPException(status_code=500, detail="Search failed") from e
