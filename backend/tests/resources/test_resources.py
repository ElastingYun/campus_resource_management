from dataclasses import replace
from datetime import time

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient
from sqlalchemy import create_engine, event, insert, select
from sqlalchemy.orm import Session
from sqlalchemy.pool import StaticPool

from app.modules.resources import create_resources_router
from app.modules.resources.contracts import NewRoomSettings, ResourceActor
from app.modules.resources.tables import metadata, rooms, seats


@pytest.fixture
def resource_api():
    engine = create_engine(
        "sqlite://", connect_args={"check_same_thread": False}, poolclass=StaticPool
    )

    @event.listens_for(engine, "connect")
    def foreign_keys(connection, _):
        connection.execute("PRAGMA foreign_keys=ON")

    metadata.create_all(engine)  # Isolated unit fixture, never application initialization.
    state = {"actor": ResourceActor("test-admin", True, True, True, None), "events": []}

    def actor():
        return state["actor"]

    def session():
        with Session(engine) as value:
            yield value

    def audit(value, mutation):
        state["events"].append(mutation)
        if state.get("audit_failure"):
            raise RuntimeError("synthetic-private-audit-error")

    application = FastAPI()
    application.include_router(
        create_resources_router(
            actor_dependency=actor,
            session_dependency=session,
            audit_sink=audit,
            new_room_settings=NewRoomSettings(time(8), time(22), "campus", True),
        )
    )
    with TestClient(application) as client:
        yield client, state, engine
    engine.dispose()


def new_room(client, code="ROOM-A"):
    response = client.post(
        "/api/v1/resources/rooms",
        json={
            "code": code,
            "name": "教学楼 A101",
            "location": "一层",
        },
    )
    assert response.status_code == 201, response.text
    return response.json()


def test_create_query_edit_persist_and_audit(resource_api):
    client, state, _ = resource_api
    room = new_room(client)
    assert room["id"] == "1"
    assert room["access_scope"] == "campus"
    assert "availability" not in room
    response = client.post(
        f"/api/v1/resources/rooms/{room['id']}/seats",
        json={
            "code": "01",
            "outlet_type": "fixed",
        },
    )
    assert response.status_code == 201
    seat = response.json()
    assert seat["room_id"] == room["id"]
    updated = client.patch(
        f"/api/v1/resources/rooms/{room['id']}",
        json={
            "name": "新名称",
            "expected_revision": room["revision"],
        },
    )
    assert updated.status_code == 200
    assert updated.json()["id"] == room["id"]
    assert updated.json()["revision"] != room["revision"]
    updated_seat = client.patch(
        f"/api/v1/resources/seats/{seat['id']}",
        json={
            "outlet_type": "rail",
            "expected_revision": seat["revision"],
        },
    )
    assert updated_seat.status_code == 200
    assert client.get(f"/api/v1/resources/seats/{seat['id']}").json()["outlet_type"] == "rail"
    page = client.get("/api/v1/resources/rooms?q=新名称&limit=1&offset=0").json()
    assert page["total"] == 1 and page["items"][0]["name"] == "新名称"
    filtered = client.get(f"/api/v1/resources/rooms/{room['id']}/seats?outlet_type=fixed").json()
    assert filtered["total"] == 0
    assert [item.action for item in state["events"]] == [
        "room.create",
        "seat.create",
        "room.update",
        "seat.update",
    ]


@pytest.mark.parametrize(
    "payload",
    [
        {"code": " ", "name": "A", "location": "L"},
        {"code": "A" * 33, "name": "A", "location": "L"},
        {"code": "A", "name": "N" * 101, "location": "L"},
        {"code": "A", "name": "N", "location": "L" * 201},
        {"code": 12, "name": "A", "location": "L"},
        {"code": "A", "name": None, "location": "L"},
        {"code": "A", "name": "A", "location": "L", "enabled": False},
        {"code": "A", "name": "A", "location": "L", "access_scope": "department"},
    ],
)
def test_invalid_creates_do_not_write(resource_api, payload):
    client, _, _ = resource_api
    assert client.post("/api/v1/resources/rooms", json=payload).status_code == 422
    assert client.get("/api/v1/resources/rooms").json()["total"] == 0


def test_duplicate_codes_parent_reference_and_pagination(resource_api):
    client, _, _ = resource_api
    first = new_room(client, "ROOM-A")
    second = new_room(client, "ROOM-B")
    assert (
        client.post(
            "/api/v1/resources/rooms",
            json={
                "code": " ROOM-A ",
                "name": "duplicate",
                "location": "L",
            },
        ).status_code
        == 409
    )
    assert (
        client.get("/api/v1/resources/rooms?limit=1&offset=1").json()["items"][0]["id"]
        == second["id"]
    )
    for room in (first, second):
        assert (
            client.post(
                f"/api/v1/resources/rooms/{room['id']}/seats",
                json={
                    "code": "01",
                    "outlet_type": "none",
                },
            ).status_code
            == 201
        )
    assert (
        client.post(
            f"/api/v1/resources/rooms/{first['id']}/seats",
            json={
                "code": "01",
                "outlet_type": "rail",
            },
        ).status_code
        == 409
    )
    assert (
        client.post(
            "/api/v1/resources/rooms/999/seats",
            json={
                "code": "01",
                "outlet_type": "none",
            },
        ).status_code
        == 404
    )
    assert client.get("/api/v1/resources/rooms?q=%25").json()["total"] == 0


@pytest.mark.parametrize("suffix", ["?limit=0", "?limit=101", "?offset=-1", "/0", "/invalid"])
def test_invalid_query_and_identifiers(resource_api, suffix):
    client, _, _ = resource_api
    assert client.get("/api/v1/resources/rooms" + suffix).status_code == 422


def test_stale_update_and_immutable_fields(resource_api):
    client, _, _ = resource_api
    room = new_room(client)
    endpoint = f"/api/v1/resources/rooms/{room['id']}"
    first = client.patch(endpoint, json={"name": "first", "expected_revision": room["revision"]})
    assert first.status_code == 200
    stale = client.patch(endpoint, json={"name": "lost", "expected_revision": room["revision"]})
    assert stale.status_code == 409 and stale.json()["detail"]["code"] == "stale_revision"
    assert client.get(endpoint).json()["name"] == "first"
    for changes in ({}, {"name": None}, {"enabled": False}, {"id": "99"}, {"open_time": "10:00"}):
        assert (
            client.patch(
                endpoint,
                json={
                    **changes,
                    "expected_revision": first.json()["revision"],
                },
            ).status_code
            == 422
        )


def test_permission_checks_and_room_scope(resource_api):
    client, state, _ = resource_api
    room = new_room(client)
    other = new_room(client, "OTHER")
    state["actor"] = ResourceActor("test-student", True, False, False, None)
    assert (
        client.post(
            "/api/v1/resources/rooms",
            json={
                "code": "C",
                "name": "N",
                "location": "L",
            },
        ).status_code
        == 403
    )
    state["actor"] = ResourceActor("test-scoped", True, True, False, frozenset({int(room["id"])}))
    assert client.get("/api/v1/resources/rooms").json()["total"] == 1
    assert client.get(f"/api/v1/resources/rooms/{other['id']}").status_code == 404
    assert (
        client.patch(
            f"/api/v1/resources/rooms/{other['id']}",
            json={
                "name": "forbidden",
                "expected_revision": other["revision"],
            },
        ).status_code
        == 404
    )
    state["actor"] = ResourceActor("test-denied")
    assert client.get("/api/v1/resources/rooms").status_code == 403


def test_audit_failure_rolls_back_without_leaking_error(resource_api):
    client, state, engine = resource_api
    state["audit_failure"] = True
    response = client.post(
        "/api/v1/resources/rooms",
        json={
            "code": "FAIL",
            "name": "N",
            "location": "L",
        },
    )
    assert response.status_code == 503
    assert "synthetic-private" not in response.text
    with Session(engine) as session:
        assert session.execute(select(rooms)).first() is None


def test_bigint_id_is_lossless_string(resource_api):
    client, _, engine = resource_api
    room = new_room(client)
    identifier = 9007199254740993
    with engine.begin() as connection:
        source = dict(
            connection.execute(select(rooms).where(rooms.c.id == int(room["id"]))).mappings().one()
        )
        connection.execute(insert(rooms).values(**{**source, "id": identifier, "code": "BIG"}))
    response = client.get(f"/api/v1/resources/rooms/{identifier}")
    assert response.json()["id"] == "9007199254740993"


def test_defaults_refuse_identity_and_do_not_trust_headers():
    application = FastAPI()
    application.include_router(create_resources_router())
    with TestClient(application) as client:
        response = client.get(
            "/api/v1/resources/rooms",
            headers={
                "X-Dev-User-Id": "admin",
                "X-Dev-Permissions": "resources:manage",
            },
        )
        assert response.status_code == 503
        assert response.json()["detail"]["code"] == "identity_unconfigured"


def test_missing_creation_policy_and_audit_refuse_writes(resource_api):
    _, state, engine = resource_api

    def session():
        with Session(engine) as value:
            yield value

    for sink, expected in (
        (None, "audit_unconfigured"),
        (lambda *_: None, "creation_unconfigured"),
    ):
        application = FastAPI()
        application.include_router(
            create_resources_router(
                actor_dependency=lambda: state["actor"],
                session_dependency=session,
                audit_sink=sink,
            )
        )
        with TestClient(application) as client:
            response = client.post(
                "/api/v1/resources/rooms",
                json={
                    "code": "DENIED",
                    "name": "N",
                    "location": "L",
                },
            )
            assert response.status_code == 503 and response.json()["detail"]["code"] == expected


def test_creation_settings_require_explicit_valid_policy():
    with pytest.raises(ValueError):
        NewRoomSettings(time(22), time(8), "campus", True)
    with pytest.raises(ValueError):
        NewRoomSettings(time(8), time(22), "department", True)
    config = NewRoomSettings(time(8), time(22), "campus", True)
    assert replace(config, enabled=False).enabled is False


def test_invalid_seat_fields_do_not_write(resource_api):
    client, _, engine = resource_api
    room = new_room(client)
    for data in (
        {"code": " ", "outlet_type": "none"},
        {"code": "01", "outlet_type": "unknown"},
        {"code": "01", "outlet_type": "fixed", "room_id": "999"},
    ):
        assert (
            client.post(f"/api/v1/resources/rooms/{room['id']}/seats", json=data).status_code == 422
        )
    with Session(engine) as session:
        assert session.execute(select(seats)).first() is None
