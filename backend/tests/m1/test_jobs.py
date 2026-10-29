import os
import subprocess
import sys
from datetime import timedelta
from pathlib import Path

from sqlalchemy import text
from sqlalchemy.orm import sessionmaker

from app.modules.m1_reservation import checkin, jobs, reservations
from app.modules.m1_reservation.errors import M1Error
from app.modules.m1_reservation.identity import PERM_RESERVE, CurrentUser
from tests.m1.conftest import SH, auth, local, run_together
from tests.m1.test_checkin import SECRET, _check_in, _code
from tests.m1.test_reservations_api import book


def run(engine, now):
    with sessionmaker(engine)() as session:
        return jobs.run_due(session, now)


def outbox(engine):
    with engine.connect() as conn:
        return conn.execute(
            text("SELECT reservation_id, kind FROM m1_notification_outbox ORDER BY id")
        ).all()


def status_of(client, rid, user="stu-001"):
    return client.get(f"/api/v1/m1/reservations/{rid}", headers=auth(user)).json()


def violation_count(engine):
    with engine.connect() as conn:
        return conn.execute(text("SELECT count(*) FROM m1_violations")).scalar_one()


def test_pre_start_reminder_fires_once_from_fifteen_minutes_before(client, clock, seeded, engine):
    rid = book(client, seeded["seats"]["LIB-101-01"], local(2, 10)).json()["id"]
    assert run(engine, local(2, 9, 44)).pre_start_reminders == 0
    assert run(engine, local(2, 9, 45)).pre_start_reminders == 1
    assert run(engine, local(2, 9, 50)).pre_start_reminders == 0
    assert outbox(engine) == [(rid, "reminder_before_start")]


def test_late_reminder_only_for_reservations_not_checked_in(client, clock, seeded, engine):
    absent = book(client, seeded["seats"]["LIB-101-01"], local(2, 10)).json()["id"]
    present = book(
        client, seeded["seats"]["LIB-101-02"], local(2, 10), headers=auth("stu-002")
    ).json()["id"]
    clock.set(local(2, 10, 1))
    assert (
        _check_in(
            client, present, _code(client, seeded["rooms"]["LIB-101"]), headers=auth("stu-002")
        ).status_code
        == 200
    )
    assert run(engine, local(2, 10, 9)).late_reminders == 0
    assert run(engine, local(2, 10, 10)).late_reminders == 1
    assert run(engine, local(2, 10, 12)).late_reminders == 0
    assert (absent, "reminder_not_checked_in") in outbox(engine)
    assert all(rid != present for rid, kind in outbox(engine) if kind == "reminder_not_checked_in")


def test_no_show_at_fifteen_minutes_cancels_records_one_violation_and_notifies(
    client, clock, seeded, engine
):
    rid = book(client, seeded["seats"]["LIB-101-01"], local(2, 10)).json()["id"]
    assert run(engine, local(2, 10, 15) - timedelta(seconds=1)).no_shows == 0
    assert status_of(client, rid)["status"] == "booked"

    report = run(engine, local(2, 10, 15))
    assert (report.no_shows, report.violations) == (1, 1)
    body = status_of(client, rid)
    assert (body["status"], body["cancel_reason"]) == ("no_show", "no_show")
    assert (rid, "no_show_cancelled") in outbox(engine)

    assert run(engine, local(2, 10, 20)).no_shows == 0
    assert violation_count(engine) == 1
    mine = client.get("/api/v1/m1/violations/me", headers=auth()).json()
    assert [(v["reservation_id"], v["reason"]) for v in mine] == [(rid, "no_show")]
    assert client.get("/api/v1/m1/violations/me", headers=auth("stu-002")).json() == []
    with engine.connect() as conn:
        last = conn.execute(
            text("SELECT action, actor_id FROM m1_seat_state_events ORDER BY id DESC LIMIT 1")
        ).one()
    assert tuple(last) == ("no_show_released", jobs.JOB_ACTOR)


def test_no_show_releases_the_rest_of_the_slot(client, clock, seeded, engine):
    seat = seeded["seats"]["LIB-101-01"]
    book(client, seat, local(2, 10), 2)
    clock.set(local(2, 10, 15))
    blocked = book(client, seat, local(2, 11), 1, headers=auth("stu-002"))
    assert blocked.status_code == 409
    run(engine, local(2, 10, 15))
    assert book(client, seat, local(2, 11), 1, headers=auth("stu-002")).status_code == 201


def test_checked_in_and_cancelled_reservations_are_never_no_shows(client, clock, seeded, engine):
    present = book(client, seeded["seats"]["LIB-101-01"], local(2, 10)).json()["id"]
    cancelled = book(
        client, seeded["seats"]["LIB-101-02"], local(2, 10), headers=auth("stu-002")
    ).json()["id"]
    client.post(f"/api/v1/m1/reservations/{cancelled}/cancel", headers=auth("stu-002"))
    clock.set(local(2, 10, 5))
    _check_in(client, present, _code(client, seeded["rooms"]["LIB-101"]))
    report = run(engine, local(2, 11))
    assert report.no_shows == 0 and violation_count(engine) == 0
    assert status_of(client, present)["status"] == "checked_in"
    assert outbox(engine) == []


def test_late_first_run_skips_reminders_whose_moment_has_passed(client, clock, seeded, engine):
    rid = book(client, seeded["seats"]["LIB-101-01"], local(2, 10)).json()["id"]
    report = run(engine, local(2, 10, 30))
    assert (report.no_shows, report.late_reminders, report.pre_start_reminders) == (1, 0, 0)
    assert outbox(engine) == [(rid, "no_show_cancelled")]


def _race_check_in_with_no_show_job(factory, user, reservation_id, code, start):
    """Check-in at start+14:59 and the job at start+15:00, released together."""

    def check_in():
        with factory() as session:
            try:
                checkin.check_in(
                    session,
                    user,
                    reservation_id,
                    code,
                    now=start + timedelta(minutes=15, seconds=-1),
                    tz=SH,
                    secret=SECRET,
                )
                return "ok"
            except M1Error as err:
                return err.code

    def no_show_job():
        with factory() as session:
            jobs.run_due(session, start + timedelta(minutes=15))

    return run_together(check_in, no_show_job)[0]


def test_check_in_racing_the_no_show_job_never_ends_in_both(engine, seeded):
    """Check-in at 10:14:59 and the job at 10:15 start together; exactly one may win."""
    factory = sessionmaker(engine, expire_on_commit=False)
    user = CurrentUser("stu-race", None, frozenset({PERM_RESERVE}))
    room = seeded["rooms"]["LIB-101"]
    for i in range(6):
        start = local(2 + i, 10)
        with factory() as s:
            reservation, _ = reservations.create(
                s,
                user,
                seat_id=seeded["seats"][f"LIB-101-{i + 1:02d}"],
                start_at=start,
                hours=1,
                idempotency_key=None,
                now=local(2, 7),
                tz=SH,
            )
        code = checkin.daily_code(SECRET, room, start.date())
        outcome = _race_check_in_with_no_show_job(factory, user, reservation.id, code, start)
        with engine.connect() as conn:
            status = conn.execute(
                text("SELECT status FROM m1_reservations WHERE id = :i"), {"i": reservation.id}
            ).scalar_one()
            violations = conn.execute(
                text("SELECT count(*) FROM m1_violations WHERE reservation_id = :i"),
                {"i": reservation.id},
            ).scalar_one()
        assert (status, violations, outcome) in {
            ("checked_in", 0, "ok"),
            ("no_show", 1, "not_checkinable"),
        }


def test_cli_processes_due_reservations_in_the_configured_database(db_settings, engine, seeded):
    """The CLI uses the real clock and D's CAMPUS_DB_* settings, like the deployed job."""
    with engine.begin() as conn:
        rid = conn.execute(
            text(
                "INSERT INTO m1_reservations (user_id, seat_id, room_id, start_at, end_at, status) "
                "VALUES ('stu-cli', :seat, :room, now() - interval '20 minutes', "
                "now() + interval '40 minutes', 'booked') RETURNING id"
            ),
            {"seat": seeded["seats"]["LIB-101-01"], "room": seeded["rooms"]["LIB-101"]},
        ).scalar_one()
    backend = Path(__file__).resolve().parents[2]
    env = {
        **os.environ,
        "PYTHONPATH": str(backend),
        "CAMPUS_DB_HOST": db_settings.db_host,
        "CAMPUS_DB_PORT": str(db_settings.db_port),
        "CAMPUS_DB_NAME": db_settings.db_name,
        "CAMPUS_DB_USER": db_settings.db_user,
        "CAMPUS_DB_PASSWORD": db_settings.db_password.get_secret_value(),
    }
    result = subprocess.run(
        [sys.executable, "-m", "app.modules.m1_reservation.jobs"],
        cwd=backend,
        env=env,
        capture_output=True,
        text=True,
        timeout=60,
    )
    assert result.returncode == 0, result.stderr
    assert "no_shows=1" in result.stdout
    with engine.connect() as conn:
        status = conn.execute(
            text("SELECT status FROM m1_reservations WHERE id = :i"), {"i": rid}
        ).scalar_one()
    assert status == "no_show"
