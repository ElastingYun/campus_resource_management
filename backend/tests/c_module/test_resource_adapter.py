from dataclasses import replace
from datetime import time
from types import SimpleNamespace
from uuid import uuid4

import pytest
from pydantic import ValidationError
from sqlalchemy import create_engine
from sqlalchemy.orm import Session

from app.common.audit.service import AuditService
from app.common.auth.database import Database
from app.common.auth.domain import Principal, ServiceError
from app.common.auth.resource_adapter import (
    NewRoomPolicy,
    ResourceManagementConfiguration,
    ResourcePermissions,
    resource_audit_sink,
    resource_scopes,
)


@pytest.mark.parametrize(
    "identifier",
    ["0", "01", "-1", "+1", "1.0", " 1", "1 ", "R1", "١", "9223372036854775808"],
)
def test_invalid_scope_never_becomes_global(identifier):
    principal = Principal(uuid4(), "synthetic", frozenset(), frozenset(), frozenset({identifier}))
    with pytest.raises(ServiceError) as error:
        resource_scopes(principal)
    assert error.value.status == 403 and error.value.code == "RESOURCE_SCOPE_INVALID"


def test_empty_scopes_and_large_ids_keep_exact_meaning():
    principal = Principal(uuid4(), "synthetic", frozenset(), frozenset(), frozenset())
    assert resource_scopes(principal) == frozenset()
    principal = replace(principal, room_ids=frozenset({"9007199254740993", "9223372036854775807"}))
    assert resource_scopes(principal) == frozenset({9007199254740993, 9223372036854775807})
    assert resource_scopes(replace(principal, all_rooms=True)) is None


def test_resource_permissions_and_creation_policy_are_explicit():
    with pytest.raises(ValidationError):
        ResourceManagementConfiguration.model_validate({})
    permissions = ResourcePermissions(
        read="synthetic.read", manage="synthetic.manage", create_rooms="synthetic.create"
    )
    assert ResourceManagementConfiguration(permissions=permissions).new_room is None
    with pytest.raises(ValidationError):
        ResourcePermissions(read="synthetic read", manage="manage", create_rooms="create")
    with pytest.raises(ValidationError):
        NewRoomPolicy(
            open_time=time(8),
            close_time=time(22),
            access_scope="department",
            department_id=None,
            enabled=True,
        )
    with pytest.raises(ValidationError):
        NewRoomPolicy(
            open_time=time(22),
            close_time=time(8),
            access_scope="campus",
            department_id=None,
            enabled=True,
        )
    with pytest.raises(ValidationError):
        NewRoomPolicy(
            open_time=time(8),
            close_time=time(22),
            access_scope="campus",
            department_id=None,
            enabled="false",
        )


@pytest.mark.parametrize(
    "change",
    [
        {"schema_version": 1},
        {"schema_version": True},
        {"action": "room.delete"},
        {"resource_id": True},
        {"room_id": 9223372036854775808},
        {"request_id": "client-controlled"},
        {"actor_id": "untrusted-user"},
        {"before": None},
        {"after": None},
        {"after": '{"password":"synthetic-secret"}'},
        {"after": '{"name":{"nested":"payload"}}'},
    ],
)
def test_invalid_mutation_is_rejected_before_any_audit_write(change):
    mutation = SimpleNamespace(
        schema_version=2,
        action="room.update",
        resource_id=1,
        room_id=1,
        actor_id=str(uuid4()),
        request_id=str(uuid4()),
        before="{}",
        after="{}",
    )
    for name, value in change.items():
        setattr(mutation, name, value)

    class NeverWrite:
        def record_in_session(self, *_args, **_kwargs):
            pytest.fail("Invalid resource metadata reached the persistence boundary")

    with pytest.raises(ValueError):
        resource_audit_sink(NeverWrite(), lambda: None)(None, mutation)


def test_session_audit_requires_an_existing_supported_owner_transaction():
    audit = AuditService(Database("synthetic-unused-dsn"))
    with Session() as session:
        with pytest.raises(ValueError, match="active owner transaction"):
            audit.record_in_session(session)
        assert not session.in_transaction()
    engine = create_engine("sqlite://")
    try:
        with Session(engine) as session:
            with session.begin():
                with pytest.raises(ValueError, match="PostgreSQL driver"):
                    audit.record_in_session(session)
                assert session.in_transaction()
    finally:
        engine.dispose()
