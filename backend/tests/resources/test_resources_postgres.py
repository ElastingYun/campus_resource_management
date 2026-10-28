"""Real PostgreSQL adapter tests in a disposable, uniquely named private schema.

The application never runs create_all. Only this explicitly enabled integration
fixture creates its own test tables; it does not alter shared rooms/seats tables.
"""

import os
from concurrent.futures import ThreadPoolExecutor
from datetime import time
from uuid import uuid4

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient
from sqlalchemy import text
from sqlalchemy.orm import Session

from app.config import Settings
from app.database import build_engine
from app.modules.resources import create_resources_router
from app.modules.resources.contracts import NewRoomSettings, ResourceActor
from app.modules.resources.tables import metadata

pytestmark = [
    pytest.mark.integration,
    pytest.mark.skipif(
        os.environ.get("CAMPUS_TEST_POSTGRES") != "1",
        reason="Requires an explicitly selected, isolated PostgreSQL test database",
    ),
]


@pytest.fixture
def postgres_resources():
    settings = Settings(_env_file=None)
    assert settings.database_configured
    engine = build_engine(settings)
    schema = "b_resources_test_" + uuid4().hex
    scoped = engine.execution_options(schema_translate_map={None: schema})
    try:
        with engine.begin() as connection:
            connection.execute(text(f'CREATE SCHEMA "{schema}"'))
        metadata.create_all(scoped)

        def session():
            with Session(scoped) as value:
                yield value

        application = FastAPI()
        application.include_router(
            create_resources_router(
                actor_dependency=lambda: ResourceActor("pg-test-admin", True, True, True, None),
                session_dependency=session,
                new_room_settings=NewRoomSettings(time(8), time(22), "campus", True),
                audit_sink=lambda *_: None,  # Test seam only; not proof of C audit integration.
            )
        )
        with TestClient(application) as client:
            yield client
    finally:
        with engine.begin() as connection:
            connection.execute(text(f'DROP SCHEMA IF EXISTS "{schema}" CASCADE'))
        engine.dispose()


def test_postgres_roundtrip_constraints_and_revision(postgres_resources):
    client = postgres_resources
    room = client.post(
        "/api/v1/resources/rooms", json={"code": "PG-A", "name": "PG 示例", "location": "测试区"}
    )
    assert room.status_code == 201
    data = room.json()
    assert data["id"].isdigit()
    endpoint = f"/api/v1/resources/rooms/{data['id']}"
    assert client.get(endpoint).json()["revision"] == data["revision"]
    seat = client.post(endpoint + "/seats", json={"code": "01", "outlet_type": "fixed"})
    assert seat.status_code == 201
    assert client.get(endpoint + "/seats").json()["total"] == 1
    assert (
        client.post(endpoint + "/seats", json={"code": "01", "outlet_type": "rail"}).status_code
        == 409
    )
    updated = client.patch(
        endpoint, json={"name": "PG 修改", "expected_revision": data["revision"]}
    )
    assert updated.status_code == 200
    assert updated.json()["revision"] != data["revision"]
    assert client.get(endpoint).json()["name"] == "PG 修改"


def test_postgres_concurrent_edits_do_not_lose_an_update(postgres_resources):
    client = postgres_resources
    room = client.post(
        "/api/v1/resources/rooms", json={"code": "PG-RACE", "name": "初始", "location": "测试区"}
    ).json()
    endpoint = f"/api/v1/resources/rooms/{room['id']}"

    def edit(name):
        return client.patch(endpoint, json={"name": name, "expected_revision": room["revision"]})

    with ThreadPoolExecutor(max_workers=2) as executor:
        responses = list(executor.map(edit, ["writer-a", "writer-b"]))
    assert sorted(response.status_code for response in responses) == [200, 409]
    winner = next(response.json()["name"] for response in responses if response.status_code == 200)
    assert client.get(endpoint).json()["name"] == winner
