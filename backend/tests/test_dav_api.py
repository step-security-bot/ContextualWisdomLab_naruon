import defusedxml.ElementTree as ET
from contextlib import contextmanager
from urllib.parse import unquote

from fastapi.routing import APIRoute
from fastapi.testclient import TestClient

from api.auth import get_auth_context
from api.dav import _dav_path_owner_user_id
from db.models import ProjectFolder
from db.session import get_db
from main import app

AUTH_HEADERS = {
    "X-User-Id": "user123",
    "X-User-Role": "organization_admin",
    "X-Organization-Id": "org-acme",
}


class MockScalars:
    def __init__(self, items):
        self.items = items

    def all(self):
        return self.items


class MockResult:
    def __init__(self, items):
        self.items = items

    def scalars(self):
        return MockScalars(self.items)


class MockDavSession:
    def __init__(self, folders):
        self.folders = folders
        self.statements = []
        self.params = []

    async def execute(self, stmt):
        self.statements.append(stmt)
        self.params.append(dict(stmt.compile().params))
        return MockResult(self.folders)


@contextmanager
def dav_db_override(session):
    async def override_get_db():
        yield session

    app.dependency_overrides[get_db] = override_get_db
    try:
        yield
    finally:
        app.dependency_overrides.pop(get_db, None)


def project_folder(
    folder_uid: str,
    project_name: str,
    *,
    user_id: str = "user123",
    organization_id: str | None = "org-acme",
    webdav_path: str = "/Projects/Naruon_Roadmap_2026",
) -> ProjectFolder:
    return ProjectFolder(
        folder_uid=folder_uid,
        user_id=user_id,
        organization_id=organization_id,
        project_name=project_name,
        webdav_path=webdav_path,
    )


def test_dav_rejects_missing_auth():
    with TestClient(app) as client:
        response = client.request("PROPFIND", "/dav/user123/projects/")
        assert response.status_code == 401


def test_dav_route_uses_signed_session_dependency():
    for route in app.routes:
        if isinstance(route, APIRoute) and route.path == "/dav/{path:path}":
            dependencies = {dependency.dependency for dependency in route.dependencies}
            assert get_auth_context in dependencies
            return

    raise AssertionError("DAV route is not registered")


def test_dav_options(dev_auth_dependency_overrides):
    with TestClient(app) as client:
        response = client.options("/dav/user123/projects/", headers=AUTH_HEADERS)
        assert response.status_code == 200
        assert "calendar-access" in response.headers.get("DAV", "")


def test_dav_rejects_different_user_path(dev_auth_dependency_overrides):
    with TestClient(app) as client:
        response = client.request(
            "PROPFIND", "/dav/other-user/projects/", headers=AUTH_HEADERS
        )
        assert response.status_code == 403
        assert response.json()["detail"] == "DAV path belongs to a different user"


def test_dav_rejects_path_traversal(dev_auth_dependency_overrides):
    with TestClient(app) as client:
        response = client.request(
            "PROPFIND", "/dav/user123/..%2Fother-user/projects/", headers=AUTH_HEADERS
        )
        assert response.status_code == 403
        assert response.json()["detail"] == "DAV path must include an owner user"


def test_dav_owner_parser_rejects_backslash_traversal():
    owner_user_id = _dav_path_owner_user_id("user123/..\\other-user/projects")

    assert owner_user_id is None


def test_dav_rejects_backslash_traversal(dev_auth_dependency_overrides):
    with TestClient(app) as client:
        response = client.request(
            "PROPFIND", "/dav/user123/..\\other-user/projects/", headers=AUTH_HEADERS
        )

    assert response.status_code == 403
    assert response.json()["detail"] == "DAV path must include an owner user"


def test_dav_owner_parser_rejects_double_encoded_traversal():
    owner_user_id = _dav_path_owner_user_id(
        "user123/%252e%252e%252fother-user/projects"
    )

    assert owner_user_id is None


def test_dav_rejects_double_encoded_traversal(dev_auth_dependency_overrides):
    with TestClient(app) as client:
        response = client.request(
            "PROPFIND",
            "/dav/user123/%252e%252e%252fother-user/projects/",
            headers=AUTH_HEADERS,
        )

    assert response.status_code == 403
    assert response.json()["detail"] == "DAV path must include an owner user"


def test_dav_rejects_ownerless_path(dev_auth_dependency_overrides):
    with TestClient(app) as client:
        response = client.request("PROPFIND", "/dav/", headers=AUTH_HEADERS)
        assert response.status_code == 403
        assert response.json()["detail"] == "DAV path must include an owner user"


def test_dav_rejects_ownerless_options_before_capability_discovery(
    dev_auth_dependency_overrides,
):
    with TestClient(app) as client:
        response = client.options("/dav/", headers=AUTH_HEADERS)
        assert response.status_code == 403
        assert "dav" not in {header.lower() for header in response.headers}
        assert response.json()["detail"] == "DAV path must include an owner user"


def test_dav_propfind(dev_auth_dependency_overrides):
    session = MockDavSession(
        [
            project_folder("webdav_folder_roadmap", "Naruon Roadmap 2026"),
            project_folder("webdav_folder_research", "Research Notes"),
        ]
    )
    with TestClient(app) as client:
        with dav_db_override(session):
            response = client.request(
                "PROPFIND",
                "/dav/user123/projects/",
                headers={**AUTH_HEADERS, "Depth": "1"},
            )
        assert response.status_code == 207
        assert "<D:multistatus" in response.text
        root = ET.fromstring(response.text)
        hrefs = [node.text for node in root.findall(".//{DAV:}href")]
        display_names = [node.text for node in root.findall(".//{DAV:}displayname")]
        assert "/api/dav/user123/projects/webdav_folder_roadmap" in hrefs
        assert "/api/dav/user123/projects/webdav_folder_research" in hrefs
        assert "Naruon Roadmap 2026" in display_names
        assert "Research Notes" in display_names
        assert "/Projects/Naruon_Roadmap_2026" not in response.text
        assert session.params[-1]["user_id_1"] == "user123"
        assert session.params[-1]["organization_id_1"] == "org-acme"


def test_dav_propfind_empty_projects_returns_empty_multistatus(
    dev_auth_dependency_overrides,
):
    session = MockDavSession([])
    with TestClient(app) as client:
        with dav_db_override(session):
            response = client.request(
                "PROPFIND",
                "/dav/user123/projects/",
                headers={**AUTH_HEADERS, "Depth": "1"},
            )

    assert response.status_code == 207
    root = ET.fromstring(response.text)
    assert root.findall(".//{DAV:}response") == []
    assert session.params[-1]["user_id_1"] == "user123"
    assert session.params[-1]["organization_id_1"] == "org-acme"


def test_dav_propfind_missing_folder_uid_returns_404(dev_auth_dependency_overrides):
    session = MockDavSession([])
    with TestClient(app) as client:
        with dav_db_override(session):
            response = client.request(
                "PROPFIND",
                "/dav/user123/projects/webdav_folder_missing",
                headers={**AUTH_HEADERS, "Depth": "0"},
            )

    assert response.status_code == 404
    assert response.json()["detail"] == "DAV project folder not found"
    assert session.params[-1]["user_id_1"] == "user123"
    assert session.params[-1]["organization_id_1"] == "org-acme"


def test_dav_propfind_escapes_path_values(dev_auth_dependency_overrides):
    session = MockDavSession(
        [
            project_folder(
                "x&y<z>",
                "Folder & Research <2026>",
                webdav_path="/Projects/Unsafe_Display",
            )
        ]
    )
    with TestClient(app) as client:
        with dav_db_override(session):
            response = client.request(
                "PROPFIND",
                "/dav/user123/projects/x%26y%3Cz%3E",
                headers={**AUTH_HEADERS, "Depth": "0"},
            )
        assert response.status_code == 207
        assert "x&amp;y&lt;z&gt;" in response.text
        assert "x&y<z>" not in response.text
        assert "Folder &amp; Research &lt;2026&gt;" in response.text
        assert "Folder & Research <2026>" not in response.text
        ET.fromstring(response.text)


def test_dav_put(dev_auth_dependency_overrides):
    with TestClient(app) as client:
        response = client.put(
            "/dav/user123/projects/file.ics",
            content=b"BEGIN:VCALENDAR\r\nEND:VCALENDAR",
            headers=AUTH_HEADERS,
        )
        assert response.status_code == 501
        assert "Provider-backed DAV writeback is not implemented" in response.text
        assert "etag" not in {header.lower() for header in response.headers}


def test_dav_log_injection_prevention(dev_auth_dependency_overrides, caplog):
    import asyncio
    import logging

    from fastapi import Request

    from api.auth import AuthContext
    from api.dav import dav_handler

    caplog.set_level(logging.INFO, logger="api.dav")
    malicious_path = "user123/projects/test%1B%5B31minjected%0A%0D"
    malicious_folder_uid = unquote("test%1B%5B31minjected%0A%0D")
    scope = {"type": "http", "method": "PROPFIND", "headers": []}
    session = MockDavSession([project_folder(malicious_folder_uid, "Injected path")])

    async def run_handler():
        req = Request(scope)
        auth_context = AuthContext(
            user_id="user123",
            organization_id="org-acme",
            role="organization_admin",
            group_ids=[],
            workspace_id="workspace-org-acme",
        )
        await dav_handler(
            request=req,
            path=unquote(malicious_path),
            auth_context=auth_context,
            db=session,
        )

    asyncio.run(run_handler())

    dav_messages = [
        record.getMessage()
        for record in caplog.records
        if "DAV Request" in record.getMessage()
    ]

    assert dav_messages
    assert all("\x1b[31m" not in message for message in dav_messages)
    assert all("\n" not in message for message in dav_messages)
    assert any("\\x1b[31minjected\\n\\r" in message for message in dav_messages)
