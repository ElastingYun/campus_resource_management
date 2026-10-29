"""Real SQL read boundaries must never splice privilege and scope versions."""

from concurrent.futures import ThreadPoolExecutor
from contextlib import contextmanager
from threading import Event, Lock

import pytest
from fastapi.testclient import TestClient

from .conftest import submit


class PausedPrincipalRead:
    """Forward actual PostgreSQL calls, pausing after the identity SELECT executes."""

    def __init__(self, database, user_id):
        self.database, self.user_id = database, user_id
        self.selected, self.resume = Event(), Event()
        self.lock, self.used = Lock(), False

    @contextmanager
    def transaction(self):
        boundary = self
        with self.database.transaction() as connection:

            class Connection:
                def execute(self, query, params=None, **kwargs):
                    cursor = connection.execute(query, params, **kwargs)
                    pause = False
                    if "FROM c_users" in str(query) and params == (boundary.user_id,):
                        with boundary.lock:
                            if not boundary.used:
                                boundary.used, pause = True, True
                    if pause:
                        boundary.selected.set()
                        if not boundary.resume.wait(10):
                            raise RuntimeError("Principal snapshot fixture was not released")
                    return cursor

            yield Connection()


@pytest.mark.parametrize("scope", ["all_rooms", "room_ids"])
@pytest.mark.parametrize("surface", ["", "/actions", "/integration"])
def test_concurrent_role_scope_change_cannot_create_a_never_granted_reader(
    case, monkeypatch, scope, surface
):
    application = submit(case)
    role_permissions = case.principals["first"].permissions
    target_id = case.auth.provision_user(
        username="snapshot-target",
        password="synthetic-snapshot-password",
        department_id="D1",
        roles={"applicant": frozenset({"m2.submit"})},
        room_ids=frozenset({"R1"}) if scope == "room_ids" else frozenset(),
        all_rooms=scope == "all_rooms",
    )
    case.auth.provision_user(
        username="snapshot-manager",
        password="synthetic-snapshot-password",
        department_id="D1",
        roles={"snapshot-manager": role_permissions | {"auth.manage", "m2.submit"}},
        room_ids=frozenset(),
        all_rooms=True,
    )
    # Explicit synthetic account-management policy, not a production grant.
    case.auth.access_policy = lambda *_: True
    with TestClient(case.app) as client:

        def headers(username):
            response = client.post(
                "/api/v1/auth/sessions",
                json={"username": username, "password": "synthetic-snapshot-password"},
            )
            assert response.status_code == 200
            return {"Authorization": "Bearer " + response.json()["access_token"]}

        target, manager = headers("snapshot-target"), headers("snapshot-manager")
        path = "/api/v1/m2/applications/" + str(application["id"]) + surface
        before = client.get(path, headers=target)
        boundary = PausedPrincipalRead(case.db, target_id)
        monkeypatch.setattr(case.auth, "database", boundary)
        with ThreadPoolExecutor(max_workers=1) as pool:
            pending = pool.submit(client.get, path, headers=target)
            try:
                assert boundary.selected.wait(5), "Identity query did not reach its SQL boundary"
                changed = client.put(
                    f"/api/v1/auth/users/{target_id}/access",
                    headers=manager,
                    json={
                        "role_names": ["first"],
                        "room_ids": ["R2"],
                        "all_rooms": False,
                        "enabled": True,
                    },
                )
                assert changed.status_code == 200
            finally:
                boundary.resume.set()
            racing = pending.result(timeout=5)
        after = client.get(path, headers=target)
        # Neither version grants R1 read: old lacks permission, new lacks scope.
        assert [before.status_code, racing.status_code, after.status_code] == [404, 404, 404]
        current = client.get("/api/v1/auth/me", headers=target)
        assert current.status_code == 200
        assert current.json()["data_scopes"]["room_ids"] == ["R2"]
        assert current.json()["data_scopes"]["all_rooms"] is False
        assert "m2.read_all" in current.json()["permissions"]


def test_identity_snapshot_preserves_empty_roles_and_multi_role_permission_union(case):
    for username, roles, expected in (
        ("no-roles", {}, frozenset()),
        (
            "combined-roles",
            {"snapshot-a": frozenset({"shared", "a"}), "snapshot-b": frozenset({"shared", "b"})},
            frozenset({"shared", "a", "b"}),
        ),
    ):
        user_id = case.auth.provision_user(
            username=username,
            password="synthetic-snapshot-password",
            department_id="D1",
            roles=roles,
            room_ids=frozenset({"R2"}),
        )
        token = case.auth.login(
            username,
            "synthetic-snapshot-password",
            client_key="snapshot-union-client",
            request_id="snapshot-union-login",
        )["access_token"]
        principal = case.auth.authenticate(token)
        assert principal.subject_id == user_id
        assert principal.roles == frozenset(roles)
        assert principal.permissions == expected
        assert principal.room_ids == frozenset({"R2"}) and principal.all_rooms is False
