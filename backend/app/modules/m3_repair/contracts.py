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

    def __post_init__(self) -> None:
        if not self.subject_id or len(self.subject_id) > 64:
            raise ValueError("A stable subject ID is required")
        if type(self.can_create) is not bool or type(self.can_read_own) is not bool:
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


def get_ticket_actor() -> TicketActor:
    raise TicketError(503, "identity_unconfigured", "报修身份尚未接入")


def get_room_policy() -> RoomPolicy:
    raise TicketError(503, "room_policy_unconfigured", "教室校验尚未接入")


def get_ticket_audit() -> TicketAudit:
    raise TicketError(503, "audit_unconfigured", "报修审计尚未接入")
