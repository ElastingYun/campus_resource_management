"""Actual C result events for future notification delivery, not sent messages."""

from concurrent.futures import ThreadPoolExecutor
from datetime import timedelta
from threading import Event

import psycopg
import pytest

from app.modules.m2_approval.clients import Outcome, RemoteUnavailable

from .test_worker import M1, passed, worker


def events(case):
    with case.db.transaction() as conn:
        return conn.execute(
            "SELECT * FROM c_business_events WHERE type LIKE 'application.occupancy_%' "
            "ORDER BY occurred_at,id"
        ).fetchall()


def assert_result_event(case, application, event_type, operation_kind):
    rows = events(case)
    matching = [row for row in rows if row["type"] == event_type]
    assert len(matching) == 1
    event = matching[0]
    with case.db.transaction() as conn:
        operation = conn.execute(
            "SELECT * FROM c_m1_operations WHERE application_id=%s AND kind=%s",
            (application["id"], operation_kind),
        ).fetchone()
    assert str(event["application_id"]) == application["id"]
    assert event["occurred_at"] == case.clock()
    assert event["payload"] == {
        "application_id": application["id"],
        "version": application["version"],
        "review_status": application["review_status"],
        "integration_status": application["integration_status"],
        "operation_id": str(operation["id"]),
        "generation": operation["generation"],
    }


@pytest.mark.parametrize("outcome", [Outcome.APPLIED, Outcome.CONFLICT])
def test_confirmed_outcome_records_one_matching_event_without_changing_approval(case, outcome):
    class Gateway(M1):
        def execute(self, payload):
            return super().execute(payload) if outcome == Outcome.APPLIED else Outcome.CONFLICT

    application = passed(case)
    runner = worker(case, Gateway())
    assert events(case) == []
    assert runner.run_once() and not runner.run_once()
    current = case.approval.get(case.principals["student"], application["id"])
    assert current["review_status"] == "PASSED"
    assert current["effective"] is (outcome == Outcome.APPLIED)
    assert_result_event(
        case,
        current,
        "application.occupancy_confirmed"
        if outcome == Outcome.APPLIED
        else "application.occupancy_conflict",
        "APPLY",
    )
    with case.db.transaction() as conn:
        original = conn.execute(
            "SELECT payload FROM c_business_events WHERE type='application.submitted'"
        ).fetchone()["payload"]
        assert set(original) == {
            "application_id",
            "version",
            "review_status",
            "integration_status",
        }


def test_release_confirmation_records_only_its_source_and_never_duplicates(case):
    application, gateway = passed(case), M1()
    runner = worker(case, gateway)
    assert runner.run_once()
    current = case.approval.get(case.principals["student"], application["id"])
    revoked = case.approval.revoke(
        case.principals["first"],
        current["id"],
        expected_version=current["version"],
        key="event-revoke",
        request_id="event-revoke",
    )
    assert len(events(case)) == 1
    assert revoked["integration_status"] == "RELEASE_PENDING"
    assert runner.run_once() and not runner.run_once()
    final = case.approval.get(case.principals["student"], application["id"])
    assert final["integration_status"] == "RELEASED" and final["effective"] is False
    assert_result_event(case, final, "application.occupancy_released", "RELEASE")
    assert len(events(case)) == 2 and gateway.sources == {"another-source"}


def test_unknown_result_records_no_confirmation_until_same_operation_query(case):
    class LostReply(M1):
        def execute(self, payload):
            super().execute(payload)
            raise RemoteUnavailable("synthetic lost confirmation")

    application, gateway = passed(case), LostReply()
    runner = worker(case, gateway)
    assert runner.run_once()
    assert events(case) == []
    assert (
        case.approval.get(case.principals["student"], application["id"])["integration_status"]
        == "APPLY_UNKNOWN"
    )
    case.clock.now += timedelta(seconds=1)
    assert runner.run_once() and not runner.run_once()
    current = case.approval.get(case.principals["student"], application["id"])
    assert_result_event(case, current, "application.occupancy_confirmed", "APPLY")
    assert gateway.execute_count == 1 and len(events(case)) == 1


def test_late_old_apply_response_cannot_emit_success_after_confirmed_revocation(case):
    applied, resume = Event(), Event()

    class DelayedReply(M1):
        def execute(self, payload):
            result = super().execute(payload)
            if payload["kind"] == "APPLY":
                applied.set()
                if not resume.wait(10):
                    raise RuntimeError("Late result fixture was not released")
            return result

    application, gateway = passed(case), DelayedReply()
    with ThreadPoolExecutor(max_workers=1) as pool:
        pending = pool.submit(worker(case, gateway).run_once)
        try:
            assert applied.wait(5)
            case.approval.revoke(
                case.principals["first"],
                application["id"],
                expected_version=application["version"],
                key="revoke-before-reply",
                request_id="revoke-before-reply",
            )
            assert worker(case, gateway).run_once()
        finally:
            resume.set()
        assert pending.result(timeout=5)
    final = case.approval.get(case.principals["student"], application["id"])
    assert final["integration_status"] == "RELEASED" and final["effective"] is False
    assert_result_event(case, final, "application.occupancy_released", "RELEASE")
    assert len(events(case)) == 1 and gateway.sources == {"another-source"}


def test_real_audit_failure_rolls_back_event_and_state_then_query_recovers(case):
    application, gateway = passed(case), M1()
    with case.db.transaction() as conn:
        conn.execute(
            "ALTER TABLE c_audit_events ADD CONSTRAINT synthetic_apply_failure "
            "CHECK(action <> 'm1.apply')"
        )
    with pytest.raises(psycopg.errors.CheckViolation):
        worker(case, gateway).run_once()
    assert events(case) == []
    current = case.approval.get(case.principals["student"], application["id"])
    assert current["version"] == application["version"]
    assert current["integration_status"] == "APPLY_PENDING" and current["effective"] is False
    with case.db.transaction() as conn:
        operation = conn.execute("SELECT * FROM c_m1_operations").fetchone()
        assert operation["state"] == "RUNNING" and operation["attempts"] == 1
        conn.execute("ALTER TABLE c_audit_events DROP CONSTRAINT synthetic_apply_failure")
    case.clock.now += timedelta(seconds=31)
    assert worker(case, gateway).run_once()
    final = case.approval.get(case.principals["student"], application["id"])
    assert final["effective"] is True
    assert_result_event(case, final, "application.occupancy_confirmed", "APPLY")
    assert gateway.execute_count == 1 and len(events(case)) == 1
