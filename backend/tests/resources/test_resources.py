import json
from dataclasses import FrozenInstanceError, replace
from datetime import time
from uuid import uuid4

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
def resource_api(audit_store):
    engine = create_engine(
        "sqlite://", connect_args={"check_same_thread": False}, poolclass=StaticPool
    )

    @event.listens_for(engine, "connect")
    def foreign_keys(connection, _):
        connection.execute("PRAGMA foreign_keys=ON")

    metadata.create_all(engine)  # Isolated unit fixture, never application initialization.
    store = audit_store(engine)
    state = {
        "actor": ResourceActor("test-admin", True, True, True, None),
        "events": [],
        "audit_store": store,
    }

    def actor():
        return state["actor"]

    def session():
        with Session(engine) as value:
            yield value

    def audit(value, mutation):
        store.write(value, mutation)
        state["events"].append(mutation)
        if state.get("audit_constraint_failure"):
            row = value.execute(select(store.table)).mappings().first()
            value.execute(insert(store.table).values(**dict(row)))  # Real duplicate primary key.
        if state.get("audit_failure"):
            raise RuntimeError("synthetic-private-audit-error")

    application = FastAPI()

    @application.middleware("http")
    async def trusted_context(request, call_next):
        request.state.request_id = state.get("request_id", str(uuid4()))
        return await call_next(request)

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
                request_id_dependency=lambda: str(uuid4()),  # Explicit trusted test seam.
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


def test_create_audit_uses_trusted_context_and_persisted_whitelist(resource_api):
    client, state, _ = resource_api
    trusted_id = str(uuid4())
    state["request_id"] = trusted_id
    response = client.post(
        "/api/v1/resources/rooms",
        json={"code": "  AUDIT  ", "name": "  示例  ", "location": "  一层  "},
        headers={"X-Request-ID": str(uuid4()), "Authorization": "Bearer synthetic-private-token"},
    )
    assert response.status_code == 201
    mutation = state["events"][-1]
    assert mutation.request_id == trusted_id
    assert mutation.actor_id == state["actor"].subject
    assert mutation.resource_id == mutation.room_id == int(response.json()["id"])
    assert mutation.before is None
    assert json.loads(mutation.after) == {
        "code": "AUDIT",
        "name": "示例",
        "location": "一层",
        "access_scope": "campus",
        "department_id": None,
        "open_time": "08:00:00",
        "close_time": "22:00:00",
        "enabled": True,
    }
    assert "synthetic-private-token" not in repr(mutation)
    assert state["audit_store"].read()[0]["after"] == mutation.after
    with pytest.raises(FrozenInstanceError):
        mutation.room_id = 999


def test_update_audit_contains_only_actual_changed_fields(resource_api):
    client, state, _ = resource_api
    room = new_room(client)
    response = client.patch(
        f"/api/v1/resources/rooms/{room['id']}",
        json={"code": room["code"], "name": "  审计修改  ", "expected_revision": room["revision"]},
    )
    assert response.status_code == 200
    mutation = state["events"][-1]
    assert json.loads(mutation.before) == {"name": room["name"]}
    assert json.loads(mutation.after) == {"name": response.json()["name"]}
    assert mutation.room_id == int(room["id"])
    assert "revision" not in mutation.after and "updated_at" not in mutation.after


def test_seat_audit_has_its_parent_room_not_the_seat_identifier(resource_api):
    client, state, _ = resource_api
    new_room(client)
    room = new_room(client, "SECOND")
    response = client.post(
        f"/api/v1/resources/rooms/{room['id']}/seats", json={"code": "01", "outlet_type": "fixed"}
    )
    assert response.status_code == 201
    seat = response.json()
    mutation = state["events"][-1]
    assert mutation.resource_id == int(seat["id"])
    assert mutation.room_id == int(room["id"]) != mutation.resource_id
    assert mutation.before is None
    assert json.loads(mutation.after) == {"code": "01", "outlet_type": "fixed", "enabled": True}
    edited = client.patch(
        f"/api/v1/resources/seats/{seat['id']}",
        json={"outlet_type": "rail", "expected_revision": seat["revision"]},
    )
    assert edited.status_code == 200
    mutation = state["events"][-1]
    assert mutation.room_id == int(room["id"])
    assert json.loads(mutation.before) == {"outlet_type": "fixed"}
    assert json.loads(mutation.after) == {"outlet_type": "rail"}


def test_noop_update_does_not_invent_a_field_change(resource_api):
    client, state, _ = resource_api
    room = new_room(client)
    response = client.patch(
        f"/api/v1/resources/rooms/{room['id']}",
        json={"name": room["name"], "expected_revision": room["revision"]},
    )
    assert response.status_code == 200
    assert state["events"][-1].before == state["events"][-1].after == "{}"


@pytest.mark.parametrize("request_id", [None, "", "not-a-uuid", "x" * 129, 42])
def test_untrusted_or_missing_context_refuses_writes_but_not_reads(resource_api, request_id):
    client, state, _ = resource_api
    room = new_room(client)
    committed = state["audit_store"].read()
    state["request_id"] = request_id
    assert client.get("/api/v1/resources/rooms").status_code == 200
    response = client.patch(
        f"/api/v1/resources/rooms/{room['id']}",
        json={"name": "不得写入", "expected_revision": room["revision"]},
        headers={"X-Request-ID": str(uuid4())},
    )
    assert response.status_code == 503
    assert response.json()["detail"]["code"] == "audit_context_unconfigured"
    assert client.get(f"/api/v1/resources/rooms/{room['id']}").json()["name"] == room["name"]
    assert state["audit_store"].read() == committed


def test_host_can_explicitly_inject_its_trusted_context_dependency(resource_api):
    _, state, engine = resource_api
    trusted_id = str(uuid4())

    def session():
        with Session(engine) as value:
            yield value

    for dependency, expected in (({}, 503), ({"request_id_dependency": lambda: trusted_id}, 201)):
        application = FastAPI()
        application.include_router(
            create_resources_router(
                actor_dependency=lambda: state["actor"],
                session_dependency=session,
                new_room_settings=NewRoomSettings(time(8), time(22), "campus", True),
                audit_sink=state["audit_store"].write,
                **dependency,
            )
        )
        with TestClient(application) as client:
            response = client.post(
                "/api/v1/resources/rooms",
                json={"code": "INJECT", "name": "N", "location": "L"},
                headers={"X-Request-ID": str(uuid4())},
            )
            assert response.status_code == expected
    assert state["audit_store"].read()[-1]["request_id"] == trusted_id


@pytest.mark.parametrize("operation", ["room.create", "seat.create", "room.update", "seat.update"])
def test_each_resource_and_audit_write_roll_back_together(resource_api, operation):
    client, state, engine = resource_api
    room = new_room(client)
    seat = client.post(
        f"/api/v1/resources/rooms/{room['id']}/seats", json={"code": "01", "outlet_type": "fixed"}
    ).json()

    def persisted():
        with Session(engine) as session:
            return [list(session.execute(select(table)).all()) for table in (rooms, seats)]

    before = persisted()
    committed = state["audit_store"].read()
    state["audit_failure"] = True  # The sink inserts its row, then raises before commit.
    requests = {
        "room.create": (
            "POST",
            "/api/v1/resources/rooms",
            {"code": "FAIL", "name": "N", "location": "L"},
        ),
        "seat.create": (
            "POST",
            f"/api/v1/resources/rooms/{room['id']}/seats",
            {"code": "02", "outlet_type": "rail"},
        ),
        "room.update": (
            "PATCH",
            f"/api/v1/resources/rooms/{room['id']}",
            {"name": "FAIL", "expected_revision": room["revision"]},
        ),
        "seat.update": (
            "PATCH",
            f"/api/v1/resources/seats/{seat['id']}",
            {"outlet_type": "rail", "expected_revision": seat["revision"]},
        ),
    }
    method, endpoint, payload = requests[operation]
    response = client.request(method, endpoint, json=payload)
    assert response.status_code == 503
    assert "synthetic-private" not in response.text
    assert persisted() == before
    assert state["audit_store"].read() == committed


def test_denied_stale_and_duplicate_writes_do_not_emit_success_audits(resource_api):
    client, state, _ = resource_api
    room = new_room(client)
    endpoint = f"/api/v1/resources/rooms/{room['id']}"
    edited = client.patch(endpoint, json={"name": "first", "expected_revision": room["revision"]})
    assert edited.status_code == 200
    committed = state["audit_store"].read()
    assert (
        client.patch(
            endpoint, json={"name": "stale", "expected_revision": room["revision"]}
        ).status_code
        == 409
    )
    assert (
        client.post(
            "/api/v1/resources/rooms", json={"code": room["code"], "name": "N", "location": "L"}
        ).status_code
        == 409
    )
    state["actor"] = ResourceActor("outside-scope", True, True, False, frozenset())
    assert (
        client.patch(
            endpoint, json={"name": "denied", "expected_revision": edited.json()["revision"]}
        ).status_code
        == 404
    )
    assert state["audit_store"].read() == committed


def test_audit_keeps_bigint_identifiers_lossless(resource_api):
    client, state, engine = resource_api
    new_room(client)
    identifier = 9007199254740993
    with engine.begin() as connection:
        source = dict(connection.execute(select(rooms)).mappings().one())
        connection.execute(
            insert(rooms).values(**{**source, "id": identifier, "code": "BIG-AUDIT"})
        )
    current = client.get(f"/api/v1/resources/rooms/{identifier}").json()
    response = client.patch(
        f"/api/v1/resources/rooms/{identifier}",
        json={"name": "大整数", "expected_revision": current["revision"]},
    )
    assert response.status_code == 200
    assert state["events"][-1].resource_id == state["events"][-1].room_id == identifier
    record = state["audit_store"].read()[-1]
    assert record["resource_id"] == record["room_id"] == "9007199254740993"


def test_audit_constraint_error_is_not_reported_as_duplicate_resource(resource_api):
    client, state, _ = resource_api
    room = new_room(client)
    committed = state["audit_store"].read()
    state["audit_constraint_failure"] = True
    endpoint = f"/api/v1/resources/rooms/{room['id']}"
    response = client.patch(
        endpoint, json={"name": "不得保留", "expected_revision": room["revision"]}
    )
    assert response.status_code == 503
    assert response.json()["detail"]["code"] == "audit_unavailable"
    assert client.get(endpoint).json() == room
    assert state["audit_store"].read() == committed
