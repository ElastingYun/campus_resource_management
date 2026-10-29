"""Real account-management races at credential verification and commit boundaries."""

from concurrent.futures import ThreadPoolExecutor
from dataclasses import replace
from threading import Event

import pytest

from app.common.auth.domain import ServiceError


def manager(case):
    # Explicit test-only management policy, not a production grant.
    case.auth.access_policy = lambda *_: True
    return replace(case.principals["first"], permissions=frozenset({"auth.manage", "m2.submit"}))


def access(case, actor, *, enabled):
    return case.auth.change_access(
        actor,
        case.ids["student"],
        role_names=["applicant"],
        room_ids=[],
        all_rooms=False,
        enabled=enabled,
        request_id="synthetic-access-change",
    )


@pytest.mark.parametrize("change", ["disable", "credentials", "invalid_credentials"])
def test_changed_account_cannot_issue_session_from_stale_password_check(case, change):
    actor = manager(case)
    checked, resume = Event(), Event()
    original = case.auth.hasher

    class PausedVerification:
        def verify(self, *args):
            result = original.verify(*args)  # Actual Argon2, not a fake successful verifier.
            checked.set()
            if not resume.wait(10):
                raise RuntimeError("Credential race fixture was not released")
            return result

    case.auth.hasher = PausedVerification()

    def login():
        try:
            result = case.auth.login(
                "student",
                "synthetic-password-123",
                client_key="synthetic-race-client",
                request_id="synthetic-racing-login",
            )
            return "ISSUED", result["access_token"]
        except ServiceError as error:
            return error.code, None

    with ThreadPoolExecutor(max_workers=1) as pool:
        pending = pool.submit(login)
        try:
            assert checked.wait(5), "Real password verification did not reach the boundary"
            if change == "disable":
                access(case, actor, enabled=False)
            else:
                # Controlled credential maintenance fixture; no public reset API is introduced.
                replacement = (
                    original.hash("synthetic-replacement-password")
                    if change == "credentials"
                    else "synthetic-invalid-散列"
                )
                with case.db.transaction() as conn:
                    conn.execute(
                        "UPDATE c_users SET password_hash=%s WHERE id=%s",
                        (replacement, case.ids["student"]),
                    )
        finally:
            resume.set()
        outcome, token = pending.result(timeout=5)
    if change == "disable":
        access(case, actor, enabled=True)
    resurrected = False
    if token is not None:
        try:
            case.auth.authenticate(token)
        except ServiceError:
            pass
        else:
            resurrected = True
    # Do not include session tokens in assertion output, even for synthetic accounts.
    assert outcome == "INVALID_CREDENTIALS", (
        f"stale_outcome={outcome}; session_reactivated={resurrected}"
    )
    assert resurrected is False
    with case.db.transaction() as conn:
        assert conn.execute("SELECT count(*) AS n FROM c_sessions").fetchone()["n"] == 0
        event = conn.execute(
            "SELECT result FROM c_audit_events WHERE request_id='synthetic-racing-login'"
        ).fetchone()
        assert event["result"] == "INVALID_CREDENTIALS"
        assert all(
            row["attempts"] == 1
            for row in conn.execute("SELECT attempts FROM c_login_buckets").fetchall()
        )


def test_disable_concurrent_with_session_commit_revokes_the_issued_session(case, monkeypatch):
    actor = manager(case)
    recorded, resume, disabling = Event(), Event(), Event()
    original = case.audit.record

    def pause_login_audit(conn, **fields):
        original(conn, **fields)
        if fields["action"] == "auth.login" and fields["result"] == "SUCCESS":
            recorded.set()
            if not resume.wait(10):
                raise RuntimeError("Session commit fixture was not released")

    monkeypatch.setattr(case.audit, "record", pause_login_audit)

    def disable():
        disabling.set()
        access(case, actor, enabled=False)

    with ThreadPoolExecutor(max_workers=2) as pool:
        login = pool.submit(
            case.auth.login,
            "student",
            "synthetic-password-123",
            client_key="synthetic-commit-client",
            request_id="synthetic-commit-login",
        )
        try:
            assert recorded.wait(5)
            changed = pool.submit(disable)
            assert disabling.wait(5)
        finally:
            resume.set()
        session = login.result(timeout=5)
        changed.result(timeout=5)
    access(case, actor, enabled=True)
    with pytest.raises(ServiceError) as error:
        case.auth.authenticate(session["access_token"])
    assert error.value.code == "INVALID_SESSION"
    with case.db.transaction() as conn:
        assert conn.execute("SELECT revoked FROM c_sessions").fetchone()["revoked"] is True
