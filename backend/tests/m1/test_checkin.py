from datetime import date, timedelta

from sqlalchemy import text

from app.modules.m1_reservation.checkin import daily_code
from app.modules.m1_reservation.identity import PERM_CHECKIN_CODE_VIEW
from tests.m1.conftest import auth, local
from tests.m1.test_reservations_api import book

SCREEN = auth("room-screen-lib101", perms=(PERM_CHECKIN_CODE_VIEW,))
SECRET = "test-secret-not-for-production"


def _code(client, room_id):
    resp = client.get(f"/api/v1/m1/rooms/{room_id}/checkin-code", headers=SCREEN)
    assert resp.status_code == 200
    return resp.json()["code"]


def _check_in(client, rid, code, headers=None):
    return client.post(f"/api/v1/m1/reservations/{rid}/check-in", json={"code": code}, headers=headers or auth())


def _booked(client, seeded, start=None):
    return book(client, seeded["seats"]["LIB-101-01"], start or local(2, 10)).json()["id"]


def test_daily_code_is_six_digits_and_varies_by_room_and_day():
    today = daily_code(SECRET, 1, date(2026, 11, 2))
    assert len(today) == 6 and today.isdigit()
    assert today == daily_code(SECRET, 1, date(2026, 11, 2))
    assert today != daily_code(SECRET, 2, date(2026, 11, 2))
    assert today != daily_code(SECRET, 1, date(2026, 11, 3))
    assert today != daily_code("another-secret", 1, date(2026, 11, 2))


def test_code_display_requires_permission_and_reports_validity(client, clock, seeded):
    room = seeded["rooms"]["LIB-101"]
    assert client.get(f"/api/v1/m1/rooms/{room}/checkin-code", headers=auth()).status_code == 403
    body = client.get(f"/api/v1/m1/rooms/{room}/checkin-code", headers=SCREEN).json()
    assert body["date"] == "2026-11-02"
    assert body["valid_until"] == "2026-11-03T00:00:00+08:00"
    assert body["code"] == daily_code(SECRET, room, date(2026, 11, 2))


def test_check_in_with_the_rooms_code_succeeds_and_is_recorded(client, clock, seeded, engine):
    rid = _booked(client, seeded)
    clock.set(local(2, 9, 55))
    resp = _check_in(client, rid, _code(client, seeded["rooms"]["LIB-101"]))
    assert resp.status_code == 200
    assert resp.json()["status"] == "checked_in"
    assert resp.json()["checked_in_at"] == "2026-11-02T09:55:00+08:00"
    with engine.connect() as conn:
        actions = conn.execute(text("SELECT action FROM m1_seat_state_events ORDER BY id")).scalars().all()
    assert actions == ["reserved", "checked_in"]


def test_check_in_window_boundaries(client, clock, seeded):
    rid = _booked(client, seeded)
    code = _code(client, seeded["rooms"]["LIB-101"])
    clock.set(local(2, 9, 44))
    early = _check_in(client, rid, code)
    assert early.status_code == 409 and early.json()["error"]["code"] == "checkin_not_open"
    clock.set(local(2, 9, 45))  # opens exactly 15 minutes before start
    assert _check_in(client, rid, code).status_code == 200


def test_check_in_deadline_is_exclusive_at_fifteen_minutes(client, clock, seeded):
    room = seeded["rooms"]["LIB-101"]
    on_time = _booked(client, seeded)
    late = book(client, seeded["seats"]["LIB-101-02"], local(2, 10), headers=auth("stu-002")).json()["id"]
    clock.set(local(2, 10, 15) - timedelta(seconds=1))
    assert _check_in(client, on_time, _code(client, room)).status_code == 200
    clock.set(local(2, 10, 15))
    closed = _check_in(client, late, _code(client, room), headers=auth("stu-002"))
    assert closed.status_code == 409 and closed.json()["error"]["code"] == "checkin_closed"


def test_wrong_other_room_and_stale_codes_are_rejected(client, clock, seeded):
    rid = _booked(client, seeded)
    clock.set(local(2, 10))
    other_room = _code(client, seeded["rooms"]["A-201"])
    yesterday = daily_code(SECRET, seeded["rooms"]["LIB-101"], date(2026, 11, 1))
    for code in ["000000", other_room, yesterday]:
        resp = _check_in(client, rid, code)
        assert resp.status_code == 422 and resp.json()["error"]["code"] == "invalid_checkin_code"
    assert client.get(f"/api/v1/m1/reservations/{rid}", headers=auth()).json()["status"] == "booked"


def test_cannot_check_in_someone_elses_reservation(client, clock, seeded):
    rid = _booked(client, seeded)
    clock.set(local(2, 10))
    resp = _check_in(client, rid, _code(client, seeded["rooms"]["LIB-101"]), headers=auth("stu-002"))
    assert resp.status_code == 404


def test_repeat_and_cancelled_check_ins_are_refused(client, clock, seeded):
    room = seeded["rooms"]["LIB-101"]
    rid = _booked(client, seeded)
    cancelled = book(client, seeded["seats"]["LIB-101-02"], local(2, 12), headers=auth("stu-002")).json()["id"]
    client.post(f"/api/v1/m1/reservations/{cancelled}/cancel", headers=auth("stu-002"))
    clock.set(local(2, 10))
    assert _check_in(client, rid, _code(client, room)).status_code == 200
    again = _check_in(client, rid, _code(client, room))
    assert again.status_code == 409 and again.json()["error"]["code"] == "already_checked_in"
    clock.set(local(2, 12))
    refused = _check_in(client, cancelled, _code(client, room), headers=auth("stu-002"))
    assert refused.status_code == 409 and refused.json()["error"]["code"] == "not_checkinable"


def test_missing_secret_disables_check_in(app, client, clock, seeded):
    rid = _booked(client, seeded)
    app.state.config = app.state.config.__class__(
        database_url=app.state.config.database_url, auth_mode="dev-headers", checkin_code_secret=""
    )
    clock.set(local(2, 10))
    resp = _check_in(client, rid, "123456")
    assert resp.status_code == 503 and resp.json()["error"]["code"] == "checkin_not_configured"
