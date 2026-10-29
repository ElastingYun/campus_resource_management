"""Trusted integration ports supplied by the host after C/B contracts are approved."""

from dataclasses import dataclass
from datetime import datetime
from typing import Protocol

from fastapi import HTTPException
from sqlalchemy.orm import Session


class TicketError(HTTPException):
    def __init__(self, status: int, code: str, message: str):
        super().__init__(status_code=status, detail={"code": code, "message": message})


@dataclass(frozen=True)
class TicketActor:
    """Built from a trusted session, never from client-supplied identity fields."""

    subject_id: str
    can_create: bool = False
    can_read_own: bool = False
    can_assign: bool = False
    can_start_repair: bool = False

    def __post_init__(self) -> None:
        if not self.subject_id or len(self.subject_id) > 64:
            raise ValueError("A stable subject ID is required")
        if any(
            type(capability) is not bool
            for capability in (
                self.can_create,
                self.can_read_own,
                self.can_assign,
                self.can_start_repair,
            )
        ):
            raise ValueError("Ticket capabilities must be explicit booleans")


class RoomPolicy(Protocol):
    def require_reportable(self, room_id: int, actor: TicketActor) -> None:
        """Raise TicketError if the room is absent, disabled, or outside actor's scope."""
        ...


class TicketAudit(Protocol):
    def record_created(
        self,
        session: Session,
        *,
        actor: TicketActor,
        ticket_id: str,
        room_id: str,
        request_id: str,
        now: datetime,
    ) -> None:
        """Record m3.ticket.create SUCCESS, None -> REPORTED in this transaction.

        The adapter must not commit, roll back, close the session, or include
        the fault description in its audit entry.
        """
        ...


class AssignmentPolicy(Protocol):
    def require_assignable(self, room_id: int, actor: TicketActor, assignee_id: str) -> None:
        """Check trusted room scope and assignee eligibility; fail closed if unknown."""
        ...


class AssignmentAudit(Protocol):
    def record_assigned(
        self,
        session: Session,
        *,
        actor: TicketActor,
        ticket_id: str,
        room_id: str,
        assignee_id: str,
        operation_id: str,
        before_status: str,
        after_status: str,
        now: datetime,
    ) -> None:
        """Write success audit in the supplied transaction, without commit/rollback."""
        ...


class RestrictionConfirmation(Protocol):
    def require_active(self, ticket_id: str, room_id: int) -> None:
        """Confirm M1 has an active whole-room restriction for this ticket and room.

        An unknown result must fail closed; this port never treats a ticket
        status or B's static enabled flag as proof of an M1 restriction.
        """
        ...


class WorkStartAudit(Protocol):
    def record_started(
        self,
        session: Session,
        *,
        actor: TicketActor,
        ticket_id: str,
        room_id: str,
        operation_id: str,
        before_status: str,
        after_status: str,
        now: datetime,
    ) -> None:
        """Write success audit in the supplied transaction without committing."""
        ...


def get_ticket_actor() -> TicketActor:
    raise TicketError(503, "identity_unconfigured", "报修身份尚未接入")


def get_room_policy() -> RoomPolicy:
    raise TicketError(503, "room_policy_unconfigured", "教室校验尚未接入")


def get_ticket_audit() -> TicketAudit:
    raise TicketError(503, "audit_unconfigured", "报修审计尚未接入")


def get_assignment_policy() -> AssignmentPolicy:
    raise TicketError(503, "assignment_policy_unconfigured", "派单资格尚未接入")


def get_assignment_audit() -> AssignmentAudit:
    raise TicketError(503, "audit_unconfigured", "派单审计尚未接入")


def get_restriction_confirmation() -> RestrictionConfirmation:
    raise TicketError(503, "restriction_confirmation_unconfigured", "维修下架确认尚未接入")


def get_work_start_audit() -> WorkStartAudit:
    raise TicketError(503, "audit_unconfigured", "开工审计尚未接入")
