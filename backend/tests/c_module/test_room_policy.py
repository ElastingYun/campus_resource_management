import json
from datetime import timedelta

import httpx
import pytest
from fastapi.testclient import TestClient
from pydantic import ValidationError

from app.common.auth.domain import ServiceError
from app.modules.m2_approval.clients import HttpResourceGateway
from app.modules.m2_approval.domain import Room
from app.modules.m2_approval.room_policy import room_is_eligible
from app.modules.m2_approval.settings import ComponentConfiguration

from .test_hosted_runtime import hosted
from .test_identity import login
from .test_runtime_settings import EXAMPLE


@pytest.mark.parametrize(
    "scope,department,enabled,expected",
    [
        ("campus", None, True, True),
        ("campus", "D2", True, True),
        ("department", "D1", True, True),
        ("department", "D2", True, False),
        ("campus", None, False, False),
        ("department", "D1", False, False),
    ],
)
def test_owner_approved_room_eligibility(scope, department, enabled, expected):
    assert room_is_eligible(Room("R1", department, enabled, scope), "D1") is expected


@pytest.mark.parametrize(
    "scope,department,enabled",
    [
        (None, "D1", True),
        ("unknown", None, True),
        ("department", None, True),
        ("department", "", True),
        ("department", " D1", True),
        ("department", "D" * 65, True),
        ("campus", 1, True),
        ("campus", None, "true"),
    ],
)
def test_missing_or_invalid_scope_metadata_cannot_be_inferred(scope, department, enabled):
    with pytest.raises(ValueError):
        room_is_eligible(Room("R1", department, enabled, scope), "D1")


def test_policy_activation_is_explicit_and_cannot_allow_cross_department():
    data = json.loads(EXAMPLE.read_text())
    assert (
        ComponentConfiguration.model_validate_json(json.dumps(data)).submission.room_access_policy
        == "legacy"
    )
    data["submission"]["room_access_policy"] = "campus_or_own_department"
    assert (
        ComponentConfiguration.model_validate_json(json.dumps(data)).submission.room_access_policy
        == "campus_or_own_department"
    )
    data["submission"]["allow_cross_department"] = True
    with pytest.raises(ValidationError):
        ComponentConfiguration.model_validate_json(json.dumps(data))


@pytest.mark.parametrize("scope,department", [("campus", None), ("department", "D1")])
def test_http_adapter_consumes_b_v2_nullable_department(scope, department):
    with httpx.Client(
        base_url="http://resources.contract.test",
        transport=httpx.MockTransport(
            lambda _: httpx.Response(
                200,
                json={
                    "id": "1",
                    "department_id": department,
                    "enabled": True,
                    "access_scope": scope,
                },
            )
        ),
    ) as client:
        gateway = HttpResourceGateway(
            client,
            room_path="/rooms/{room_id}",
            service_token="synthetic",
            timeout_seconds=1,
            require_access_scope=True,
        )
        room = gateway.get_room("1")
        assert room.access_scope == scope and room.department_id == department


@pytest.mark.parametrize("missing", ["access_scope", "department_id"])
def test_http_adapter_distinguishes_explicit_campus_null_from_missing_metadata(missing):
    data = {"id": "1", "department_id": None, "enabled": True, "access_scope": "campus"}
    del data[missing]
    with httpx.Client(
        base_url="http://resources.contract.test",
        transport=httpx.MockTransport(lambda _: httpx.Response(200, json=data)),
    ) as client:
        gateway = HttpResourceGateway(
            client,
            room_path="/rooms/{room_id}",
            service_token="synthetic",
            timeout_seconds=1,
            require_access_scope=True,
        )
        with pytest.raises(ServiceError) as error:
            gateway.get_room("1")
        assert error.value.code == "RESOURCE_UNAVAILABLE"


@pytest.mark.parametrize(
    "metadata,status,code",
    [
        ({"access_scope": "campus", "department_id": None}, 201, None),
        ({"access_scope": "department", "department_id": "D1"}, 201, None),
        ({"access_scope": "department", "department_id": "D2"}, 403, "DEPARTMENT_DENIED"),
        ({"access_scope": "department", "department_id": None}, 503, "RESOURCE_UNAVAILABLE"),
    ],
)
def test_submission_rechecks_owner_approved_metadata(
    case, tmp_path, monkeypatch, metadata, status, code
):
    application, _ = hosted(case.db, tmp_path, monkeypatch, room_policy="campus_or_own_department")
    component = application.state.c_runtime
    component.resources.client.close()
    component.resources.client = httpx.Client(
        base_url="http://resources.contract.test",
        transport=httpx.MockTransport(
            lambda _: httpx.Response(200, json={"id": "R1", "enabled": True, **metadata})
        ),
    )
    with TestClient(application) as client:
        response = client.post(
            "/api/v1/m2/applications",
            headers={
                "Authorization": "Bearer " + login(client),
                "Idempotency-Key": "approved-room-policy",
            },
            json={
                "room_id": "R1",
                "starts_at": (case.clock() + timedelta(hours=2)).isoformat(),
                "ends_at": (case.clock() + timedelta(hours=3)).isoformat(),
                "purpose": "合成策略验收",
            },
        )
        assert response.status_code == status
        if code:
            assert response.json()["error"]["code"] == code
        else:
            assert response.json()["effective"] is False
    with case.db.transaction() as conn:
        expected = int(status == 201)
        assert conn.execute("SELECT count(*) AS n FROM c_applications").fetchone()["n"] == expected
        assert conn.execute("SELECT count(*) AS n FROM c_receipts").fetchone()["n"] == expected
        assert conn.execute("SELECT count(*) AS n FROM c_m1_operations").fetchone()["n"] == 0


def test_new_key_revalidates_changed_eligibility_while_same_key_recovers_original(
    case, tmp_path, monkeypatch
):
    application, _ = hosted(case.db, tmp_path, monkeypatch, room_policy="campus_or_own_department")
    component = application.state.c_runtime
    data = {"id": "R1", "enabled": True, "access_scope": "campus", "department_id": None}
    calls = []

    def resource(request):
        calls.append(request.url.path)
        return httpx.Response(200, json=data)

    component.resources.client.close()
    component.resources.client = httpx.Client(
        base_url="http://resources.contract.test", transport=httpx.MockTransport(resource)
    )
    payload = {
        "room_id": "R1",
        "starts_at": (case.clock() + timedelta(hours=2)).isoformat(),
        "ends_at": (case.clock() + timedelta(hours=3)).isoformat(),
        "purpose": "合成资格变化",
    }
    with TestClient(application) as client:
        headers = {
            "Authorization": "Bearer " + login(client),
            "Idempotency-Key": "first-policy-key",
        }
        first = client.post("/api/v1/m2/applications", headers=headers, json=payload)
        assert first.status_code == 201 and len(calls) == 1
        data.update(access_scope="department", department_id="D2")
        replay = client.post("/api/v1/m2/applications", headers=headers, json=payload)
        assert replay.status_code == 201 and replay.json() == first.json() and len(calls) == 1
        response = client.post(
            "/api/v1/m2/applications",
            headers=headers | {"Idempotency-Key": "new-policy-key"},
            json=payload,
        )
        assert response.status_code == 403 and len(calls) == 2
    with case.db.transaction() as conn:
        assert conn.execute("SELECT count(*) AS n FROM c_applications").fetchone()["n"] == 1
