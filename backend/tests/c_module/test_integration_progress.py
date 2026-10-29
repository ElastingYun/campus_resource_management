from concurrent.futures import ThreadPoolExecutor
from datetime import timedelta
from threading import Barrier
from uuid import uuid4

import pytest
from fastapi.testclient import TestClient

from app.modules.m2_approval.clients import Outcome, RemoteUnavailable

from .conftest import submit
from .test_identity import login
from .test_worker import M1, passed, worker


def endpoint(application):
    return "/api/v1/m2/applications/" + application["id"] + "/integration"


def test_empty_progress_is_read_only_and_contains_no_internal_fields(case):
    application = submit(case)
    with TestClient(case.app) as client:
        headers = {"Authorization": "Bearer " + login(client)}
        with case.db.transaction() as conn:
            before = conn.execute("SELECT count(*) AS n FROM c_audit_events").fetchone()["n"]
        one = client.get(endpoint(application), headers=headers)
        two = client.get(endpoint(application), headers=headers)
        assert one.status_code == 200 and one.json() == two.json()
        assert one.headers["Cache-Control"] == "no-store"
        assert one.json() == {
            "application_id": application["id"],
            "version": application["version"],
            "generation": 0,
            "integration_status": "NONE",
            "effective": False,
            "operations": [],
        }
        with case.db.transaction() as conn:
            assert (
                conn.execute("SELECT count(*) AS n FROM c_audit_events").fetchone()["n"] == before
            )
            assert conn.execute("SELECT count(*) AS n FROM c_m1_operations").fetchone()["n"] == 0


@pytest.mark.parametrize("conflict", [False, True])
def test_progress_shows_claim_and_confirmed_outcome_without_payload_or_lease(case, conflict):
    class Conflict(M1):
        def execute(self, _):
            return Outcome.CONFLICT

    application = passed(case)
    runner = worker(case, Conflict() if conflict else M1())
    initial = case.approval.integration_progress(case.principals["student"], application["id"])
    assert initial["operations"][0]["state"] == "PENDING"
    assert initial["operations"][0]["attempts"] == 0
    runner._claim()  # Actual persistent lease and attempt, no network success yet.
    claimed = case.approval.integration_progress(case.principals["student"], application["id"])
    assert claimed["operations"][0]["state"] == "RUNNING"
    assert claimed["operations"][0]["attempts"] == 1
    case.clock.now += timedelta(seconds=31)
    assert runner.run_once()
    with TestClient(case.app) as client:
        response = client.get(
            endpoint(application), headers={"Authorization": "Bearer " + login(client)}
        )
    assert response.status_code == 200
    body = response.json()
    assert body["integration_status"] == ("APPLY_CONFLICT" if conflict else "APPLIED")
    assert body["effective"] is (not conflict)
    operation = body["operations"][0]
    assert operation["state"] == ("CONFLICT" if conflict else "DONE")
    assert operation["attempts"] == 2 and operation["error_code"] is None
    assert set(operation) == {"id", "generation", "kind", "state", "attempts", "error_code"}
    for private in ("payload", "lease_token", "lease_until", "source_id"):
        assert private not in response.text


def test_retry_limit_visible_without_application_version_change_and_scoped_audit(case):
    class Unavailable:
        def execute(self, _):
            raise RemoteUnavailable("synthetic-private-network-detail")

        def query(self, _):
            raise RemoteUnavailable("synthetic-private-network-detail")

    application = passed(case)
    runner = worker(case, Unavailable(), max_attempts=1)
    assert runner.run_once()
    with TestClient(case.app) as client:
        headers = {"Authorization": "Bearer " + login(client)}
        unknown = client.get(endpoint(application), headers=headers).json()
        assert unknown["operations"][0]["state"] == "UNKNOWN"
        assert unknown["operations"][0]["error_code"] == "REMOTE_UNCONFIRMED"
        case.clock.now += timedelta(seconds=1)
        assert runner.run_once() and not runner.run_once()
        response = client.get(endpoint(application), headers=headers)
        body = response.json()
        assert body["version"] == unknown["version"]
        assert body["operations"][0]["state"] == "ATTENTION"
        assert body["operations"][0]["attempts"] == 1
        assert body["operations"][0]["error_code"] == "RETRY_LIMIT"
        assert body["integration_status"] == "APPLY_UNKNOWN" and body["effective"] is False
        assert "synthetic-private-network-detail" not in response.text
    visible = case.audit.list_events(case.principals["first"], limit=100, offset=0)
    attention = [event for event in visible if event["action"] == "m1.attention"]
    assert len(attention) == 1 and attention[0]["room_id"] == "R1"
    assert case.audit.list_events(case.principals["outsider"], limit=100, offset=0) == []


@pytest.mark.parametrize("username,status", [("student", 200), ("first", 200), ("outsider", 404)])
def test_integration_progress_visibility(case, username, status):
    application = submit(case)
    with TestClient(case.app) as client:
        headers = {"Authorization": "Bearer " + login(client, username), "X-Dev-Permissions": "*"}
        response = client.get(endpoint(application), headers=headers)
        assert response.status_code == status
        if status == 404:
            assert response.json()["error"]["code"] == "NOT_FOUND"
            assert "operations" not in response.json()


def test_anonymous_and_absent_application_do_not_leak_operations(case):
    with TestClient(case.app) as client:
        path = "/api/v1/m2/applications/" + str(uuid4()) + "/integration"
        assert client.get(path).status_code == 401
        response = client.get(path, headers={"Authorization": "Bearer " + login(client)})
        assert response.status_code == 404 and response.json()["error"]["code"] == "NOT_FOUND"


def test_revocation_and_reads_keep_generation_snapshot_consistent(case):
    application = passed(case)
    gateway = M1()
    assert worker(case, gateway).run_once()
    current = case.approval.get(case.principals["student"], application["id"])
    barrier = Barrier(2)

    def revoke():
        barrier.wait()
        return case.approval.revoke(
            case.principals["first"],
            application["id"],
            expected_version=current["version"],
            key="revoke-progress",
            request_id="revoke-progress",
        )

    def read():
        barrier.wait()
        return [
            case.approval.integration_progress(case.principals["student"], application["id"])
            for _ in range(20)
        ]

    with ThreadPoolExecutor(max_workers=2) as pool:
        changed, snapshots = pool.submit(revoke), pool.submit(read)
        changed.result(timeout=5)
        for snapshot in snapshots.result(timeout=5):
            assert [o["generation"] for o in snapshot["operations"]] == list(
                range(1, snapshot["generation"] + 1)
            )
            assert snapshot["effective"] is (snapshot["generation"] == 1)
    final = case.approval.integration_progress(case.principals["student"], application["id"])
    assert final["generation"] == 2 and final["integration_status"] == "RELEASE_PENDING"
    assert [o["kind"] for o in final["operations"]] == ["APPLY", "RELEASE"]
    assert final["effective"] is False
    assert worker(case, gateway).run_once()
    released = case.approval.integration_progress(case.principals["student"], application["id"])
    assert released["integration_status"] == "RELEASED" and released["effective"] is False
    assert [o["state"] for o in released["operations"]] == ["DONE", "DONE"]
