import datetime
from unittest.mock import AsyncMock, patch

import pytest
from fastapi.testclient import TestClient

from db.models import LLMProvider
from db.session import get_db, get_readonly_db
from main import app
from services.exceptions import EmbeddingGenerationError
from services.llm_provider_selection import LOCAL_PROVIDER_API_KEY

pytestmark = pytest.mark.usefixtures("dev_auth_dependency_overrides")


class MockRow:
    def __init__(self, id, subject, sender, content, score):
        self.id = id
        self.source_message_id = "<test@example.com>"
        self.subject = subject
        self.sender = sender
        self.content = content
        self.score = score
        self.date = datetime.datetime(2026, 4, 27, 10, 0, tzinfo=datetime.timezone.utc)
        self.thread_id = "thread-123"
        self.reply_count = 2


class MockResult:
    def all(self):
        return [MockRow(1, "Test Subject", "test@test.com", "Test Body", 1.0)]


class MockTenantConfigResult:
    def __init__(self, config):
        self.config = config

    def scalar_one_or_none(self):
        return self.config


class MockScalars:
    def __init__(self, items):
        self.items = items

    def first(self):
        return self.items[0] if self.items else None


class MockProviderResult:
    def __init__(self, providers):
        self.providers = providers

    def scalars(self):
        return MockScalars(self.providers)


class MockTenantConfig:
    def __init__(self):
        self.openai_api_key = "test-key"


class MockSession:
    def __init__(self, providers=None):
        self.providers = providers or []

    async def execute(self, stmt):
        statement_text = str(stmt).lower()
        if "llm_providers" in statement_text:
            return MockProviderResult(self.providers)
        if "tenant_configs" in statement_text:
            return MockTenantConfigResult(MockTenantConfig())
        return MockResult()

    async def scalar(self, stmt):
        return MockTenantConfig()


async def override_get_db():
    yield MockSession()


class CapturingMockSession(MockSession):
    def __init__(self, providers=None):
        super().__init__(providers=providers)
        self.statements = []

    async def execute(self, stmt):
        self.statements.append(stmt)
        return await super().execute(stmt)


@pytest.fixture
def client():
    app.dependency_overrides[get_db] = override_get_db
    app.dependency_overrides[get_readonly_db] = override_get_db
    with TestClient(app, headers={"X-User-Id": "testuser"}) as c:
        yield c
    app.dependency_overrides.clear()


@patch("api.search.generate_embeddings", new_callable=AsyncMock)
def test_search_endpoint_success(mock_generate_embeddings, client):
    mock_generate_embeddings.return_value = [[0.1] * 1536]

    response = client.post("/api/search", json={"query": "test query"})
    if response.status_code != 200:
        import traceback

        traceback.print_exc()
        print(response.json())

    assert response.status_code == 200
    data = response.json()
    assert "results" in data
    assert len(data["results"]) == 1
    assert data["results"][0]["id"] == 1
    assert data["results"][0]["subject"] == "Test Subject"
    assert data["results"][0]["date"] == "2026-04-27T10:00:00Z"
    assert data["results"][0]["source_message_id"] == "<test@example.com>"
    assert data["results"][0]["thread_id"] == "thread-123"
    assert data["results"][0]["reply_count"] == 2


@patch("api.search.generate_embeddings", new_callable=AsyncMock)
def test_search_endpoint_uses_active_provider_embedding_model(mock_generate_embeddings):
    provider = LLMProvider(
        id=4,
        user_id="admin",
        organization_id="org-acme",
        name="Local Gemma4",
        provider_type="ollama",
        base_url="http://ollama:11434/v1",
        model_identifier="gemma4",
        embedding_model="embeddinggemma",
        api_key=None,
        is_active=True,
    )
    mock_generate_embeddings.return_value = [[0.1] * 1536]
    session = MockSession(providers=[provider])

    async def override_scoped_db():
        yield session

    app.dependency_overrides[get_db] = override_scoped_db
    app.dependency_overrides[get_readonly_db] = override_scoped_db
    try:
        with TestClient(
            app,
            headers={"X-User-Id": "testuser", "X-Organization-Id": "org-acme"},
        ) as client:
            response = client.post("/api/search", json={"query": "test query"})
    finally:
        app.dependency_overrides.clear()

    assert response.status_code == 200
    mock_generate_embeddings.assert_awaited_once_with(
        ["test query"],
        LOCAL_PROVIDER_API_KEY,
        base_url="http://ollama:11434/v1",
        model="embeddinggemma",
    )


def test_search_reply_counts_group_by_coalesced_thread_key():
    from api.search import build_reply_counts_subquery

    subquery = build_reply_counts_subquery()
    sql = str(subquery.select()).lower()

    assert "coalesce(nullif(btrim(btrim(email_records.thread_id)" in sql
    assert "nullif(btrim(btrim(email_records.message_id)" in sql
    assert "coalesce(email_records.thread_id, email_records.message_id)" not in sql
    assert "count(email_records.id)" in sql
    assert "group by coalesce(nullif(btrim(btrim(email_records.thread_id)" in sql


@patch("api.search.generate_embeddings", new_callable=AsyncMock)
def test_search_endpoint_query_is_scoped_to_current_user(mock_generate_embeddings):
    mock_generate_embeddings.return_value = [[0.1] * 1536]
    session = CapturingMockSession()

    async def override_scoped_db():
        yield session

    app.dependency_overrides[get_db] = override_scoped_db
    app.dependency_overrides[get_readonly_db] = override_scoped_db
    try:
        with TestClient(
            app,
            headers={"X-User-Id": "testuser", "X-Organization-Id": "org-acme"},
        ) as client:
            response = client.post("/api/search", json={"query": "test query"})
    finally:
        app.dependency_overrides.clear()

    assert response.status_code == 200
    query_text = str(session.statements[-1]).lower()
    assert "email_records.user_id" in query_text
    assert "email_records.organization_id" in query_text
    query_params = session.statements[-1].compile().params
    user_scope_params = {
        value for key, value in query_params.items() if key.startswith("user_id")
    }
    organization_scope_params = {
        value
        for key, value in query_params.items()
        if key.startswith("organization_id")
    }
    assert user_scope_params == {"testuser"}
    assert organization_scope_params == {"org-acme"}


@patch("api.search.generate_embeddings", new_callable=AsyncMock)
def test_search_falls_back_to_full_text_when_embedding_provider_fails(
    mock_generate_embeddings,
):
    mock_generate_embeddings.side_effect = EmbeddingGenerationError(
        "Failed to generate embeddings: invalid provider key"
    )
    session = CapturingMockSession()

    async def override_scoped_db():
        yield session

    app.dependency_overrides[get_db] = override_scoped_db
    app.dependency_overrides[get_readonly_db] = override_scoped_db
    try:
        with TestClient(
            app,
            headers={"X-User-Id": "testuser", "X-Organization-Id": "org-acme"},
        ) as client:
            response = client.post("/api/search", json={"query": "test query"})
    finally:
        app.dependency_overrides.clear()

    assert response.status_code == 200
    data = response.json()
    assert len(data["results"]) == 1
    query_text = str(session.statements[-1]).lower()
    assert "ts_rank_cd" in query_text
    assert "<=>" not in query_text


@patch("api.search.generate_embeddings", new_callable=AsyncMock)
def test_search_uses_primary_config_session_and_readonly_search_session(
    mock_generate_embeddings,
):
    provider = LLMProvider(
        id=4,
        user_id="admin",
        organization_id="org-acme",
        name="Local Gemma4",
        provider_type="ollama",
        base_url="http://ollama:11434/v1",
        model_identifier="gemma4",
        embedding_model="embeddinggemma",
        api_key=None,
        is_active=True,
    )
    mock_generate_embeddings.return_value = [[0.1] * 1536]
    config_session = CapturingMockSession(providers=[provider])
    search_session = CapturingMockSession()

    async def override_config_db():
        yield config_session

    async def override_search_db():
        yield search_session

    app.dependency_overrides[get_db] = override_config_db
    app.dependency_overrides[get_readonly_db] = override_search_db
    try:
        with TestClient(
            app,
            headers={"X-User-Id": "testuser", "X-Organization-Id": "org-acme"},
        ) as client:
            response = client.post("/api/search", json={"query": "test query"})
    finally:
        app.dependency_overrides.clear()

    assert response.status_code == 200
    assert config_session.statements
    assert search_session.statements
    assert any(
        "llm_providers" in str(stmt).lower() for stmt in config_session.statements
    )
    assert all(
        "combined_search" not in str(stmt).lower() for stmt in config_session.statements
    )
    assert "combined_search" in str(search_session.statements[-1]).lower()


@patch("api.search.generate_embeddings", new_callable=AsyncMock)
def test_search_pads_local_embedding_dimension_for_vector_search(
    mock_generate_embeddings,
):
    mock_generate_embeddings.return_value = [[0.1] * 768]
    session = CapturingMockSession()

    async def override_scoped_db():
        yield session

    app.dependency_overrides[get_db] = override_scoped_db
    app.dependency_overrides[get_readonly_db] = override_scoped_db
    try:
        with TestClient(
            app,
            headers={"X-User-Id": "testuser", "X-Organization-Id": "org-acme"},
        ) as client:
            response = client.post("/api/search", json={"query": "test query"})
    finally:
        app.dependency_overrides.clear()

    assert response.status_code == 200
    query_text = str(session.statements[-1]).lower()
    assert "ts_rank_cd" in query_text
    assert "<=>" in query_text


def test_thread_group_key_behavior():
    from sqlalchemy.dialects import postgresql

    from api.search import thread_group_key

    key_expr = thread_group_key()
    compiled_sql = str(
        key_expr.compile(
            dialect=postgresql.dialect(), compile_kwargs={"literal_binds": True}
        )
    ).lower()

    assert (
        "coalesce(nullif(btrim(btrim(email_records.thread_id), '<>'), ''), nullif(btrim(btrim(email_records.message_id), '<>'), ''))"
        in compiled_sql
    )
