import os
from dataclasses import replace
from datetime import time
from uuid import uuid4

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient
from sqlalchemy import create_engine, insert, text, update
from sqlalchemy.orm import Session
from sqlalchemy.pool import StaticPool

from app.config import Settings
from app.database import build_engine
from app.modules.resources import create_resources_router
from app.modules.resources.catalog import RoomOptionsActor
from app.modules.resources.contracts import ResourceActor
from app.modules.resources.tables import metadata, rooms

BIG_ROOM = 9007199254740993
ENDPOINT = "/api/v1/resources/room-options"


@pytest.fixture(params=["sqlite", pytest.param("postgres", marks=pytest.mark.integration)])
def catalog_api(request):
    schema = None
    if request.param == "postgres":
        if os.environ.get("CAMPUS_TEST_POSTGRES") != "1":
            pytest.skip("Requires an explicitly configured isolated PostgreSQL test database")
        engine = build_engine(Settings(_env_file=None))
        schema = "b_catalog_test_" + uuid4().hex
        with engine.begin() as connection:
            connection.execute(text(f'CREATE SCHEMA "{schema}"'))
        scoped = engine.execution_options(schema_translate_map={None: schema})
    else:
        engine = scoped = create_engine(
            "sqlite://", connect_args={"check_same_thread": False}, poolclass=StaticPool
        )
    try:
        metadata.create_all(scoped)  # Private test schema only; never application startup.
        with scoped.begin() as connection:
            for identifier, code, scope, department, enabled in (
                (1, "CAMPUS", "campus", None, True),
                (2, "OWN", "department", "D1", True),
                (3, "OTHER", "department", "D2", True),
                (4, "CLOSED", "campus", None, False),
                (5, "CLOSED-OWN", "department", "D1", False),
                (6, "CAMPUS-D2", "campus", "D2", True),
                (BIG_ROOM, "LITERAL%_", "campus", None, True),
            ):
                connection.execute(
                    insert(rooms).values(
                        id=identifier,
                        code=code,
                        name=code + " 示例教室",
                        location="合成区域",
                        access_scope=scope,
                        department_id=department,
                        enabled=enabled,
                        open_time=time(8),
                        close_time=time(22),
                    )
                )
        state = {"actor": RoomOptionsActor("synthetic-student", True, "D1")}

        def session():
            with Session(scoped) as value:
                yield value

        application = FastAPI()
        application.include_router(
            create_resources_router(
                actor_dependency=lambda: ResourceActor("synthetic-student"),
                room_options_actor_dependency=lambda: state["actor"],
                session_dependency=session,
            )
        )
        with TestClient(application) as client:
            yield client, state, scoped
    finally:
        if schema:
            with engine.begin() as connection:
                connection.execute(text(f'DROP SCHEMA IF EXISTS "{schema}" CASCADE'))
        engine.dispose()


def test_only_enabled_campus_and_own_department_are_visible(catalog_api):
    client, _, _ = catalog_api
    response = client.get(ENDPOINT)
    assert response.status_code == 200
    data = response.json()
    assert [room["id"] for room in data["items"]] == ["1", "2", "6", str(BIG_ROOM)]
    assert data["total"] == 4
    assert all(set(room) == {"id", "code", "name", "location"} for room in data["items"])
    assert "availability" not in response.text and "department_id" not in response.text


def test_filter_precedes_count_and_pagination(catalog_api):
    client, _, _ = catalog_api
    pages = [client.get(ENDPOINT, params={"limit": 1, "offset": i}).json() for i in range(5)]
    assert [page["total"] for page in pages] == [4] * 5
    assert [page["items"][0]["id"] for page in pages[:4]] == ["1", "2", "6", str(BIG_ROOM)]
    assert pages[4] == {"items": [], "total": 4, "limit": 1, "offset": 4}


def test_client_department_roles_and_development_headers_do_not_grant_access(catalog_api):
    client, state, _ = catalog_api
    response = client.get(
        ENDPOINT,
        params={"department_id": "D2", "role": "admin"},
        headers={"X-Dev-User-Id": "admin", "X-Dev-Permissions": "*", "X-Department-Id": "D2"},
    )
    assert [room["id"] for room in response.json()["items"]] == ["1", "2", "6", str(BIG_ROOM)]
    state["actor"] = replace(state["actor"], can_choose=False)
    denied = client.get(ENDPOINT, headers={"X-Dev-Permissions": "*"})
    assert denied.status_code == 403 and denied.json()["detail"]["code"] == "forbidden"
    assert client.get("/api/v1/resources/rooms").status_code == 403
    assert (
        client.post(
            "/api/v1/resources/rooms", json={"code": "NO", "name": "拒绝", "location": "测试"}
        ).status_code
        == 403
    )


def test_missing_department_is_not_global_and_changes_take_effect(catalog_api):
    client, state, _ = catalog_api
    state["actor"] = replace(state["actor"], department_id=None)
    assert [room["id"] for room in client.get(ENDPOINT).json()["items"]] == [
        "1",
        "6",
        str(BIG_ROOM),
    ]
    state["actor"] = replace(state["actor"], department_id="D2")
    assert [room["id"] for room in client.get(ENDPOINT).json()["items"]] == [
        "1",
        "3",
        "6",
        str(BIG_ROOM),
    ]


def test_static_changes_are_rechecked_in_database(catalog_api):
    client, _, scoped = catalog_api
    assert client.get(ENDPOINT).json()["total"] == 4
    with scoped.begin() as connection:
        connection.execute(update(rooms).where(rooms.c.id == 2).values(enabled=False))
        connection.execute(update(rooms).where(rooms.c.id == 3).values(department_id="D1"))
    assert [room["id"] for room in client.get(ENDPOINT).json()["items"]] == [
        "1",
        "3",
        "6",
        str(BIG_ROOM),
    ]


@pytest.mark.parametrize(
    "search,expected", [("own", ["2"]), ("%_", [str(BIG_ROOM)]), ("OTHER", []), ("missing", [])]
)
def test_search_is_literal_and_cannot_expose_other_departments(catalog_api, search, expected):
    client, _, _ = catalog_api
    data = client.get(ENDPOINT, params={"q": search}).json()
    assert [room["id"] for room in data["items"]] == expected
    assert data["total"] == len(expected)


@pytest.mark.parametrize("params", [{"limit": 0}, {"limit": 101}, {"offset": -1}, {"q": "x" * 101}])
def test_invalid_query_is_rejected(catalog_api, params):
    client, _, _ = catalog_api
    assert client.get(ENDPOINT, params=params).status_code == 422


def test_database_failure_is_safe_without_fallback(catalog_api):
    client, _, scoped = catalog_api
    with scoped.begin() as connection:
        metadata.drop_all(connection)  # Remove only the fixture's private tables, FK order safe.
    response = client.get(ENDPOINT)
    assert (
        response.status_code == 503 and response.json()["detail"]["code"] == "resource_unavailable"
    )
    assert "SELECT" not in response.text and "sqlalchemy" not in response.text


def test_catalog_defaults_closed_independently_of_management_actor():
    app = FastAPI()
    app.include_router(
        create_resources_router(
            actor_dependency=lambda: ResourceActor("admin", True, True, True, None)
        )
    )
    with TestClient(app) as client:
        response = client.get(ENDPOINT, headers={"X-Dev-Permissions": "*"})
    assert (
        response.status_code == 503 and response.json()["detail"]["code"] == "identity_unconfigured"
    )


@pytest.mark.parametrize(
    "fields",
    [{"subject": " "}, {"can_choose": "true"}, {"department_id": " "}, {"department_id": True}],
)
def test_invalid_trusted_actor_is_rejected(fields):
    with pytest.raises(ValueError):
        RoomOptionsActor(**({"subject": "synthetic"} | fields))
