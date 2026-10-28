"""Time-driven M1 rules, run independently of request traffic.

    python -m app.modules.m1_reservation.jobs            # one pass
    python -m app.modules.m1_reservation.jobs --loop 60  # every 60 seconds

Each pass is safe to repeat and designed to run in parallel: rows are claimed with
FOR UPDATE SKIP LOCKED, and violations/notifications have unique keys. A pass
that runs late does not send reminders whose moment has passed: once the
no-show deadline is reached only the no-show rule applies.
"""

import argparse
import time
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone

from sqlalchemy import select
from sqlalchemy.dialects.postgresql import insert
from sqlalchemy.orm import Session

from app.config import load_config
from app.db import make_engine, make_sessionmaker
from app.modules.m1_reservation import events
from app.modules.m1_reservation.models import NotificationOutbox, Reservation, Violation
from app.modules.m1_reservation.settings import M1Settings, load_settings

JOB_ACTOR = "system:m1-jobs"


@dataclass
class JobReport:
    no_shows: int = 0
    violations: int = 0
    late_reminders: int = 0
    pre_start_reminders: int = 0


def _enqueue(session: Session, reservation: Reservation, kind: str, now: datetime) -> bool:
    payload = {
        "kind": kind,
        "reservation_id": reservation.id,
        "room_id": reservation.room_id,
        "seat_id": reservation.seat_id,
        "start_at": reservation.start_at.isoformat(),
        "end_at": reservation.end_at.isoformat(),
    }
    stmt = (
        insert(NotificationOutbox)
        .values(reservation_id=reservation.id, user_id=reservation.user_id, kind=kind, payload=payload, created_at=now)
        .on_conflict_do_nothing(index_elements=["reservation_id", "kind"])
        .returning(NotificationOutbox.id)
    )
    return session.execute(stmt).scalar_one_or_none() is not None


def _claim_booked(session: Session, *conditions) -> list[Reservation]:
    query = (
        select(Reservation)
        .where(Reservation.status == "booked", *conditions)
        .order_by(Reservation.start_at, Reservation.id)
        .with_for_update(skip_locked=True)
    )
    return list(session.scalars(query))


def _no_shows(session: Session, now: datetime, settings: M1Settings, report: JobReport) -> None:
    deadline = now - timedelta(minutes=settings.no_show_minutes)
    for reservation in _claim_booked(session, Reservation.start_at <= deadline):
        reservation.status = "no_show"
        reservation.cancelled_at = now
        reservation.cancel_reason = "no_show"
        reservation.updated_at = now
        inserted = session.execute(
            insert(Violation)
            .values(reservation_id=reservation.id, user_id=reservation.user_id, reason="no_show", occurred_at=now)
            .on_conflict_do_nothing(index_elements=["reservation_id"])
            .returning(Violation.id)
        ).scalar_one_or_none()
        report.violations += inserted is not None
        _enqueue(session, reservation, "no_show_cancelled", now)
        events.record_reservation(session, reservation, "no_show_released", JOB_ACTOR, now)
        report.no_shows += 1


def _late_reminders(session: Session, now: datetime, settings: M1Settings, report: JobReport) -> None:
    for reservation in _claim_booked(
        session,
        Reservation.start_at <= now - timedelta(minutes=settings.late_remind_minutes),
        Reservation.start_at > now - timedelta(minutes=settings.no_show_minutes),
    ):
        report.late_reminders += _enqueue(session, reservation, "reminder_not_checked_in", now)


def _pre_start_reminders(session: Session, now: datetime, settings: M1Settings, report: JobReport) -> None:
    for reservation in _claim_booked(
        session,
        Reservation.start_at <= now + timedelta(minutes=settings.remind_before_minutes),
        Reservation.start_at > now,
    ):
        report.pre_start_reminders += _enqueue(session, reservation, "reminder_before_start", now)


def run_due(session: Session, now: datetime) -> JobReport:
    settings = load_settings(session)
    report = JobReport()
    for step in (_no_shows, _late_reminders, _pre_start_reminders):
        step(session, now, settings, report)
        session.commit()
    return report


def main(argv: list[str] | None = None) -> None:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--loop", type=int, metavar="SECONDS", help="repeat forever with this interval")
    args = parser.parse_args(argv)

    engine = make_engine(load_config().database_url)
    factory = make_sessionmaker(engine)
    while True:
        with factory() as session:
            report = run_due(session, datetime.now(timezone.utc))
        print(f"m1 jobs: {report}", flush=True)
        if not args.loop:
            break
        time.sleep(args.loop)


if __name__ == "__main__":
    main()
