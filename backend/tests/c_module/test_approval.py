from concurrent.futures import ThreadPoolExecutor
from dataclasses import replace
from datetime import timedelta
from threading import Barrier
from uuid import UUID

import pytest
from fastapi.testclient import TestClient

from app.common.auth.domain import ServiceError
from app.modules.m2_approval.domain import Step, Workflow

from .conftest import submit
from .test_identity import login


def decide(case, application, reviewer="first", decision="APPROVE", key="decision-1", **updates):
    payload = {
        "decision": decision,
        "comment": "合成审批意见",
        "expected_version": application["version"],
    }
    payload.update(updates)
    return case.approval.decide(
        case.principals[reviewer],
        UUID(application["id"]),
        **payload,
        key=key,
        request_id=key,
    )


def test_two_level_approval_is_not_occupancy_confirmation(case):
    application = submit(case)
    intermediate = decide(case, application)
    assert intermediate["step_index"] == 1 and intermediate["review_status"] == "REVIEWING"
    assert intermediate["integration_status"] == "NONE"
    final = decide(case, intermediate, reviewer="second", key="second")
    assert final["review_status"] == "PASSED" and final["integration_status"] == "APPLY_PENDING"
    assert final["effective"] is False
    with case.db.transaction() as conn:
        operations = conn.execute("SELECT * FROM c_m1_operations").fetchall()
        assert len(operations) == 1 and operations[0]["kind"] == "APPLY"
        assert operations[0]["payload"]["source_id"] == application["id"]
    history = case.approval.history(case.principals["student"], UUID(application["id"]))
    assert [row["step_index"] for row in history] == [0, 1]


def test_idempotent_submit_and_decide_replay_original_result(case):
    application = submit(case)
    assert submit(case) == application
    with pytest.raises(ServiceError) as error:
        submit(case, purpose="不同内容")
    assert error.value.code == "IDEMPOTENCY_CONFLICT"
    result = decide(case, application)
    assert decide(case, application) == result
    with case.db.transaction() as conn:
        assert conn.execute("SELECT count(*) AS n FROM c_applications").fetchone()["n"] == 1
        assert conn.execute("SELECT count(*) AS n FROM c_decisions").fetchone()["n"] == 1


def test_concurrent_submit_is_one_application(case):
    barrier = Barrier(2)

    def attempt():
        barrier.wait()
        return submit(case)

    with ThreadPoolExecutor(max_workers=2) as pool:
        results = list(pool.map(lambda _: attempt(), range(2)))
    assert results[0] == results[1]
    with case.db.transaction() as conn:
        assert conn.execute("SELECT count(*) AS n FROM c_applications").fetchone()["n"] == 1


def test_idempotent_replay_still_checks_current_resource_scope(case):
    application = submit(case)
    decide(case, application)
    case.principals["first"] = replace(case.principals["first"], room_ids=frozenset())
    with pytest.raises(ServiceError) as error:
        decide(case, application)
    assert error.value.code == "OUT_OF_SCOPE"


def test_concurrent_decisions_have_one_winner(case):
    application, barrier = submit(case), Barrier(2)

    def attempt(index):
        barrier.wait()
        try:
            return decide(
                case,
                application,
                key=f"race-{index}",
                decision="APPROVE" if index else "REJECT",
            )["version"]
        except ServiceError as error:
            return error.code

    with ThreadPoolExecutor(max_workers=2) as pool:
        results = list(pool.map(attempt, range(2)))
    assert results.count(2) == 1 and results.count("STALE_VERSION") == 1
    with case.db.transaction() as conn:
        assert conn.execute("SELECT count(*) AS n FROM c_decisions").fetchone()["n"] == 1
        assert (
            conn.execute(
                "SELECT count(*) AS n FROM c_audit_events "
                "WHERE action IN ('m2.approve','m2.reject')"
            ).fetchone()["n"]
            == 1
        )


def test_cross_scope_read_is_hidden(case):
    application = submit(case)
    with TestClient(case.app) as client:
        token = login(client, "outsider")
        headers = {"Authorization": "Bearer " + token}
        assert (
            client.get("/api/v1/m2/applications/" + application["id"], headers=headers).status_code
            == 404
        )
        assert client.get("/api/v1/m2/applications", headers=headers).json() == []
        assert client.get("/api/v1/m2/review-tasks", headers=headers).json() == []
    with case.db.transaction() as conn:
        assert (
            conn.execute(
                "SELECT count(*) AS n FROM c_audit_events WHERE result='NOT_FOUND'"
            ).fetchone()["n"]
            == 1
        )


def test_skipping_steps_and_self_review_are_denied(case):
    application = submit(case)
    with pytest.raises(ServiceError) as error:
        decide(case, application, reviewer="second")
    assert error.value.status == 403
    self_reviewer = replace(
        case.principals["student"],
        room_ids=frozenset({"R1"}),
        permissions=frozenset({"m2.submit", "m2.review", "review.first"}),
    )
    with pytest.raises(ServiceError) as error:
        case.approval.decide(
            self_reviewer,
            application["id"],
            decision="APPROVE",
            comment="",
            expected_version=1,
            key="self",
            request_id="self",
        )
    assert error.value.code == "WRONG_REVIEWER"


def test_rejection_requires_reason_and_closes_review(case):
    application = submit(case)
    with pytest.raises(ServiceError) as error:
        decide(case, application, decision="REJECT", comment="")
    assert error.value.code == "REASON_REQUIRED"
    rejected = decide(case, application, decision="REJECT")
    assert rejected["review_status"] == "REJECTED"
    with pytest.raises(ServiceError) as error:
        decide(case, rejected, key="late")
    assert error.value.code == "INVALID_STATE"
    with case.db.transaction() as conn:
        assert conn.execute("SELECT count(*) AS n FROM c_m1_operations").fetchone()["n"] == 0


@pytest.mark.parametrize("inclusive", [True, False])
def test_deadline_equality_and_repeat_scan(case, inclusive):
    case.approval.workflow_for = lambda *_: replace(case.workflow, deadline_inclusive=inclusive)
    application = submit(case)
    case.clock.now += timedelta(minutes=10)
    assert case.approval.expire_due() == (1 if inclusive else 0)
    if not inclusive:
        case.clock.now += timedelta(microseconds=1)
        assert case.approval.expire_due() == 1
    assert case.approval.expire_due() == 0
    row = case.approval.get(case.principals["student"], application["id"])
    assert row["review_status"] == "TIMED_OUT" and row["version"] == 2
    with pytest.raises(ServiceError) as error:
        decide(case, row)
    assert error.value.code == "INVALID_STATE"


def test_approval_at_deadline_cannot_win_timeout(case):
    application, barrier = submit(case), Barrier(2)
    case.clock.now += timedelta(minutes=10)

    def review():
        barrier.wait()
        try:
            decide(case, application)
        except ServiceError as error:
            return error.code
        return "UNEXPECTED_SUCCESS"

    def timeout():
        barrier.wait()
        return case.approval.expire_due()

    with ThreadPoolExecutor(max_workers=2) as pool:
        one, two = pool.submit(review), pool.submit(timeout)
        assert one.result() in ("REVIEW_EXPIRED", "STALE_VERSION")
        assert two.result() == 1
    with case.db.transaction() as conn:
        assert conn.execute("SELECT count(*) AS n FROM c_decisions").fetchone()["n"] == 0


def test_flow_configuration_does_not_change_inflight_snapshot(case):
    application = submit(case)
    case.approval.workflow_for = lambda *_: Workflow(
        "replacement",
        (Step("new.permission", timedelta(days=1)),),
        True,
        False,
        False,
        False,
    )
    intermediate = decide(case, application)
    assert intermediate["step_index"] == 1
    assert decide(case, intermediate, reviewer="second", key="second")["review_status"] == "PASSED"


def test_audit_failure_rolls_back_decision_and_operation(case, monkeypatch):
    application = decide(case, submit(case))
    original = case.audit.record

    def fail_on_approval(conn, **kwargs):
        if kwargs["action"] == "m2.approve":
            raise ServiceError(503, "AUDIT_TEST_FAILURE", "故障注入")
        return original(conn, **kwargs)

    monkeypatch.setattr(case.audit, "record", fail_on_approval)
    with pytest.raises(ServiceError):
        decide(case, application, reviewer="second", key="second")
    row = case.approval.get(case.principals["student"], application["id"])
    assert row["review_status"] == "REVIEWING" and row["version"] == 2
    with case.db.transaction() as conn:
        assert conn.execute("SELECT count(*) AS n FROM c_decisions").fetchone()["n"] == 1
        assert conn.execute("SELECT count(*) AS n FROM c_m1_operations").fetchone()["n"] == 0


@pytest.mark.parametrize("room,status", [("R0", 409), ("R2", 403), ("missing", 404)])
def test_submission_obeys_resource_and_host_qualification(case, room, status):
    with pytest.raises(ServiceError) as error:
        submit(case, room_id=room)
    assert error.value.status == status


def test_api_rejects_forged_fields_and_enforces_version(case):
    with TestClient(case.app) as client:
        token = login(client)
        payload = {
            "room_id": "R1",
            "starts_at": (case.clock() + timedelta(hours=2)).isoformat(),
            "ends_at": (case.clock() + timedelta(hours=3)).isoformat(),
            "purpose": "合成申请",
        }
        headers = {"Authorization": "Bearer " + token, "Idempotency-Key": "api"}
        response = client.post(
            "/api/v1/m2/applications",
            json={**payload, "applicant_id": "forged"},
            headers=headers,
        )
        assert response.status_code == 422
        response = client.post("/api/v1/m2/applications", json=payload, headers=headers)
        assert response.status_code == 201 and response.json()["applicant_id"] == str(
            case.ids["student"]
        )
        assert (
            client.post(
                "/api/v1/m2/applications",
                json=payload,
                headers={"Authorization": "Bearer " + token},
            ).status_code
            == 422
        )
        reviewer = login(client, "first")
        headers["Authorization"] = "Bearer " + reviewer
        path = "/api/v1/m2/applications/" + response.json()["id"] + "/decisions"
        assert (
            client.post(
                path,
                json={"decision": "APPROVE", "expected_version": True},
                headers=headers,
            ).status_code
            == 422
        )
        assert (
            client.post(
                path,
                json={"decision": "APPROVE", "expected_version": 99},
                headers=headers,
            ).status_code
            == 409
        )


@pytest.mark.parametrize(
    "flag",
    [
        "allow_self_review",
        "deadline_inclusive",
        "require_rejection_reason",
        "allow_revocation",
    ],
)
def test_string_flags_cannot_silently_enable_workflow_privileges(flag):
    workflow = Workflow(
        "explicit",
        (Step("review.permission", timedelta(minutes=1)),),
        False,
        True,
        True,
        False,
    )
    with pytest.raises(TypeError, match="booleans"):
        replace(workflow, **{flag: "false"})


def test_action_query_uses_current_node_scope_and_permissions(case):
    application = submit(case)
    with TestClient(case.app) as client:
        token = login(client, "first")
        headers = {"Authorization": "Bearer " + token}
        path = f"/api/v1/m2/applications/{application['id']}/actions"
        response = client.get(path, headers=headers)
        assert response.status_code == 200
        assert response.json()["allowed_actions"] == ["APPROVE", "REJECT", "REVOKE"]
        with case.db.transaction() as conn:
            conn.execute(
                "UPDATE c_roles SET permissions=%s WHERE name='first'",
                (["m2.review", "m2.read_all", "m2.revoke"],),
            )
        assert client.get(path, headers=headers).json()["allowed_actions"] == ["REVOKE"]
        owner = login(client, "student")
        assert (
            client.get(path, headers={"Authorization": "Bearer " + owner}).json()["allowed_actions"]
            == []
        )
        outsider = login(client, "outsider")
        assert client.get(path, headers={"Authorization": "Bearer " + outsider}).status_code == 404
