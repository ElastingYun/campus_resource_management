from concurrent.futures import ThreadPoolExecutor
from dataclasses import replace
from datetime import timedelta
from threading import Barrier

import pytest

from app.common.auth.domain import ServiceError
from app.modules.m2_approval.clients import Outcome, RemoteUnavailable
from app.modules.m2_approval.worker import OperationWorker, RetrySettings

from .conftest import submit
from .test_approval import decide


class M1:
    """Contract fixture, not the real M1 implementation."""

    def __init__(self):
        self.results, self.generations, self.sources = {}, {}, {"another-source"}
        self.execute_count = 0

    def execute(self, payload):
        self.execute_count += 1
        operation_id, source = payload["operation_id"], payload["source_id"]
        if operation_id in self.results:
            return self.results[operation_id]
        generation = payload["generation"]
        if payload["kind"] == "RELEASE":
            self.generations[source] = max(self.generations.get(source, 0), generation)
            self.sources.discard(source)
            result = Outcome.RELEASED
        elif generation < self.generations.get(source, 0):
            result = Outcome.CONFLICT
        else:
            self.generations[source] = generation
            self.sources.add(source)
            result = Outcome.APPLIED
        self.results[operation_id] = result
        return result

    def query(self, operation_id):
        return self.results.get(operation_id, Outcome.NOT_FOUND)


def passed(case):
    return decide(case, decide(case, submit(case)), reviewer="second", key="second")


def worker(case, gateway, *, max_attempts=3):
    return OperationWorker(
        case.db,
        case.audit,
        gateway,
        RetrySettings(timedelta(seconds=30), timedelta(seconds=1), max_attempts),
        case.clock,
    )


def test_confirmed_apply_and_source_scoped_release(case):
    application, gateway = passed(case), M1()
    runner = worker(case, gateway)
    assert runner.run_once() and not runner.run_once()
    current = case.approval.get(case.principals["student"], application["id"])
    assert current["effective"] and current["integration_status"] == "APPLIED"
    revoked = case.approval.revoke(
        case.principals["first"],
        application["id"],
        expected_version=current["version"],
        key="revoke",
        request_id="revoke",
    )
    assert not revoked["effective"] and revoked["integration_status"] == "RELEASE_PENDING"
    assert runner.run_once()
    final = case.approval.get(case.principals["student"], application["id"])
    assert final["revoked"] and final["integration_status"] == "RELEASED"
    assert gateway.sources == {"another-source"}
    assert (
        case.approval.revoke(
            case.principals["first"],
            application["id"],
            expected_version=current["version"],
            key="revoke",
            request_id="retry",
        )
        == revoked
    )


def test_lost_response_queries_same_operation_after_restart(case):
    class LoseOnce(M1):
        def execute(self, payload):
            result = super().execute(payload)
            if self.execute_count == 1:
                raise RemoteUnavailable("response lost after commit")
            return result

    application, gateway = passed(case), LoseOnce()
    assert worker(case, gateway).run_once()
    unknown = case.approval.get(case.principals["student"], application["id"])
    assert unknown["integration_status"] == "APPLY_UNKNOWN" and not unknown["effective"]
    case.clock.now += timedelta(seconds=1)
    assert worker(case, gateway).run_once()
    assert case.approval.get(case.principals["student"], application["id"])["effective"]
    assert gateway.execute_count == 1 and len(gateway.results) == 1


def test_expired_claim_is_recovered_and_old_worker_is_fenced(case):
    application, gateway = passed(case), M1()
    old_worker = worker(case, gateway)
    old_claim = old_worker._claim()
    case.clock.now += timedelta(seconds=31)
    assert worker(case, gateway).run_once()
    current = case.approval.get(case.principals["student"], application["id"])
    assert current["effective"]
    old_worker._claim = lambda: old_claim
    assert old_worker.run_once()
    assert (
        case.approval.get(case.principals["student"], application["id"])["version"]
        == current["version"]
    )


def test_release_before_late_apply_does_not_revive_application(case):
    application, gateway = passed(case), M1()
    old_worker = worker(case, gateway)
    claim = old_worker._claim()
    case.approval.revoke(
        case.principals["first"],
        application["id"],
        expected_version=application["version"],
        key="revoke",
        request_id="revoke",
    )
    assert worker(case, gateway).run_once()  # Old apply is leased; release runs first.
    old_worker._claim = lambda: claim
    assert old_worker.run_once()
    final = case.approval.get(case.principals["student"], application["id"])
    assert final["revoked"] and not final["effective"] and final["integration_status"] == "RELEASED"
    assert application["id"] not in gateway.sources and "another-source" in gateway.sources


def test_retry_limit_preserves_unknown_and_requires_attention(case):
    class Unavailable:
        def execute(self, payload):
            raise RemoteUnavailable()

        def query(self, operation_id):
            raise RemoteUnavailable()

    application = passed(case)
    runner = worker(case, Unavailable(), max_attempts=2)
    assert runner.run_once()
    case.clock.now += timedelta(seconds=1)
    assert runner.run_once()
    case.clock.now += timedelta(seconds=1)
    assert runner.run_once() and not runner.run_once()
    with case.db.transaction() as conn:
        operation = conn.execute("SELECT * FROM c_m1_operations").fetchone()
        assert operation["state"] == "ATTENTION" and operation["attempts"] == 2
    assert (
        case.approval.get(case.principals["student"], application["id"])["integration_status"]
        == "APPLY_UNKNOWN"
    )


def test_definite_apply_conflict_does_not_activate(case):
    class Conflict(M1):
        def execute(self, payload):
            return Outcome.CONFLICT

    application = passed(case)
    assert worker(case, Conflict()).run_once()
    final = case.approval.get(case.principals["student"], application["id"])
    assert final["review_status"] == "PASSED" and final["integration_status"] == "APPLY_CONFLICT"
    assert final["effective"] is False


def test_revocation_disabled_by_snapshot_creates_no_release(case):
    case.approval.workflow_for = lambda *_: replace(case.workflow, allow_revocation=False)
    application = passed(case)
    with pytest.raises(ServiceError) as error:
        case.approval.revoke(
            case.principals["first"],
            application["id"],
            expected_version=application["version"],
            key="revoke",
            request_id="revoke",
        )
    assert error.value.code == "REVOCATION_DISABLED"
    with case.db.transaction() as conn:
        assert (
            conn.execute(
                "SELECT count(*) AS n FROM c_m1_operations WHERE kind='RELEASE'"
            ).fetchone()["n"]
            == 0
        )


def test_revoke_replay_does_not_bypass_new_scope(case):
    application = passed(case)
    principal = case.principals["first"]
    case.approval.revoke(
        principal,
        application["id"],
        expected_version=application["version"],
        key="revoke",
        request_id="revoke",
    )
    principal = replace(principal, room_ids=frozenset())
    with pytest.raises(ServiceError) as error:
        case.approval.revoke(
            principal,
            application["id"],
            expected_version=application["version"],
            key="revoke",
            request_id="retry",
        )
    assert error.value.code == "OUT_OF_SCOPE"


def test_concurrent_workers_claim_one_operation_once(case):
    application, gateway, barrier = passed(case), M1(), Barrier(2)

    def attempt(_):
        barrier.wait()
        return worker(case, gateway).run_once()

    with ThreadPoolExecutor(max_workers=2) as pool:
        results = list(pool.map(attempt, range(2)))
    assert sorted(results) == [False, True]
    assert gateway.execute_count == 1
    assert case.approval.get(case.principals["student"], application["id"])["effective"]
