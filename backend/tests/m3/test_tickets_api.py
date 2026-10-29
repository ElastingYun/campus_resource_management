"""Observable E-02 API behavior with trusted test adapters and isolated storage."""

from uuid import UUID

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient
from sqlalchemy import create_engine, func, select
from sqlalchemy.orm import Session
from sqlalchemy.pool import StaticPool

from app.modules.m3_repair.contracts import TicketActor, TicketError
from app.modules.m3_repair.router import create_router
from app.modules.m3_repair.tables import tickets


class StubRoomPolicy:
    def __init__(self):
        self.enabled = True
        self.calls = 0

    def require_reportable(self, room_id: int, actor: TicketActor) -> None:
        self.calls += 1
        if not self.enabled:
            raise TicketError(503, "room_unavailable", "无法核实教室")
        if room_id != 1:
            raise TicketError(404, "room_not_found", "教室不存在或不可报修")


@pytest.fixture
def ticket_client():
    engine = create_engine(
        "sqlite://",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )
    tickets.create(engine)  # Isolated test database only; production uses Alembic.
    holder = {"actor": TicketActor("user-1", can_create=True, can_read_own=True)}
    rooms = StubRoomPolicy()
    app = FastAPI()
    app.state.engine = engine
    app.include_router(
        create_router(
            actor_dependency=lambda: holder["actor"],
            room_policy_dependency=lambda: rooms,
        )
    )
    with TestClient(app) as client:
        yield client, holder, rooms, engine
    engine.dispose()


def create(
    client: TestClient,
    *,
    key: str = "report-1",
    room: str = "1",
    description: str = "合成灯具故障",
):
    return client.post(
        "/api/v1/m3/tickets",
        headers={"Idempotency-Key": key},
        json={"room_id": room, "description": description},
    )


def ticket_count(engine) -> int:
    with Session(engine) as session:
        return session.scalar(select(func.count()).select_from(tickets))


def test_create_then_read_only_own_ticket(ticket_client):
    client, holder, _, engine = ticket_client
    created = create(client)
    assert created.status_code == 201
    assert created.headers["cache-control"] == "no-store"
    item = created.json()
    UUID(item["id"])
    assert item["room_id"] == "1"
    assert item["status"] == "REPORTED"
    assert item["description"] == "合成灯具故障"
    assert client.get(f"/api/v1/m3/tickets/{item['id']}").json() == item
    own = client.get("/api/v1/m3/tickets?limit=1&offset=0")
    assert own.status_code == 200
    assert own.headers["cache-control"] == "no-store"
    assert own.json() == {"items": [item], "limit": 1, "offset": 0}
    assert ticket_count(engine) == 1

    holder["actor"] = TicketActor("user-2", can_create=True, can_read_own=True)
    assert client.get("/api/v1/m3/tickets").json()["items"] == []
    hidden = client.get(f"/api/v1/m3/tickets/{item['id']}")
    assert hidden.status_code == 404
    assert item["description"] not in hidden.text


def test_idempotent_replay_and_conflicting_payload(ticket_client):
    client, holder, rooms, engine = ticket_client
    first = create(client)
    assert first.status_code == 201
    rooms.enabled = False  # A replay reads the stored result; it is not a new report.
    replay = create(client)
    assert replay.status_code == 200
    assert replay.json() == first.json()
    assert rooms.calls == 1
    conflict = create(client, description="另一种故障")
    assert conflict.status_code == 409
    assert conflict.json()["detail"]["code"] == "idempotency_key_reused"
    assert ticket_count(engine) == 1

    rooms.enabled = True
    holder["actor"] = TicketActor("user-2", can_create=True, can_read_own=True)
    second_user = create(client)
    assert second_user.status_code == 201
    assert second_user.json()["id"] != first.json()["id"]
    assert ticket_count(engine) == 2


def test_invalid_room_input_and_unavailable_room_do_not_write(ticket_client):
    client, _, rooms, engine = ticket_client
    for room in ("0", "01", "9223372036854775808", "not-a-number"):
        assert create(client, room=room).status_code == 422
    assert create(client, room="2").status_code == 404
    rooms.enabled = False
    unavailable = create(client)
    assert unavailable.status_code == 503
    assert ticket_count(engine) == 0


def test_permissions_and_input_rejections_do_not_write(ticket_client):
    client, holder, _, engine = ticket_client
    holder["actor"] = TicketActor("user-1", can_read_own=True)
    assert create(client).status_code == 403
    holder["actor"] = TicketActor("user-1", can_create=True)
    assert client.get("/api/v1/m3/tickets").status_code == 403
    valid_id = "00000000-0000-0000-0000-000000000000"
    assert client.get(f"/api/v1/m3/tickets/{valid_id}").status_code == 403
    assert create(client, description=" ").status_code == 422
    assert create(client, description="bad\ntext").status_code == 422
    assert (
        client.post(
            "/api/v1/m3/tickets",
            json={"room_id": "1", "description": "x"},
        ).status_code
        == 422
    )
    assert (
        client.post(
            "/api/v1/m3/tickets",
            headers={"Idempotency-Key": "extra"},
            json={"room_id": "1", "description": "x", "reporter_id": "other"},
        ).status_code
        == 422
    )
    assert ticket_count(engine) == 0


def test_default_identity_port_is_closed():
    engine = create_engine(
        "sqlite://", connect_args={"check_same_thread": False}, poolclass=StaticPool
    )
    tickets.create(engine)
    app = FastAPI()
    app.state.engine = engine
    app.include_router(create_router())
    with TestClient(app) as client:
        response = client.post(
            "/api/v1/m3/tickets",
            headers={"Idempotency-Key": "x"},
            json={"room_id": "1", "description": "合成故障"},
        )
        assert response.status_code == 503
        assert response.json()["detail"]["code"] == "identity_unconfigured"
    assert ticket_count(engine) == 0
    engine.dispose()


def test_default_room_port_is_closed():
    engine = create_engine(
        "sqlite://", connect_args={"check_same_thread": False}, poolclass=StaticPool
    )
    tickets.create(engine)
    app = FastAPI()
    app.state.engine = engine
    app.include_router(
        create_router(
            actor_dependency=lambda: TicketActor("user-1", can_create=True, can_read_own=True)
        )
    )
    with TestClient(app) as client:
        response = client.post(
            "/api/v1/m3/tickets",
            headers={"Idempotency-Key": "x"},
            json={"room_id": "1", "description": "合成故障"},
        )
        assert response.status_code == 503
        assert response.json()["detail"]["code"] == "room_policy_unconfigured"
    assert ticket_count(engine) == 0
    engine.dispose()
