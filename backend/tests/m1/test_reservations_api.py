from sqlalchemy import text

from app.modules.m1_reservation.identity import PERM_RESERVE
from tests.m1.conftest import auth, local

URL = "/api/v1/m1/reservations"


def book(client, seat_id, start, hours=2, headers=None, key=None):
    h = dict(headers or auth())
    if key:
        h["Idempotency-Key"] = key
    return client.post(
        URL, json={"seat_id": seat_id, "start_at": start.isoformat(), "hours": hours}, headers=h
    )


def test_booking_succeeds_and_appears_in_history_and_search(client, clock, seeded):
    seat = seeded["seats"]["LIB-101-01"]
    resp = book(client, seat, local(2, 10))
    assert resp.status_code == 201
    body = resp.json()
    assert body["status"] == "booked"
    assert body["seat_code"] == "LIB-101-01"
    assert body["start_at"] == "2026-11-02T10:00:00+08:00"
    assert body["end_at"] == "2026-11-02T12:00:00+08:00"

    history = client.get(f"{URL}/me", headers=auth()).json()["items"]
    assert [r["id"] for r in history] == [body["id"]]

    search = client.get(
        "/api/v1/m1/seats/availability",
        params={
            "start_at": local(2, 11).isoformat(),
            "hours": 1,
            "room_id": seeded["rooms"]["LIB-101"],
        },
        headers=auth("stu-002"),
    ).json()["seats"]
    assert next(s for s in search if s["seat_id"] == seat)["reasons"] == [{"code": "reserved"}]


def test_overlapping_booking_of_same_seat_is_rejected_but_adjacent_is_allowed(
    client, clock, seeded
):
    seat = seeded["seats"]["LIB-101-01"]
    assert book(client, seat, local(2, 10), 2).status_code == 201
    for start, hours in [(local(2, 11), 1), (local(2, 9), 2), (local(2, 9), 4), (local(2, 10), 2)]:
        resp = book(client, seat, start, hours, headers=auth("stu-002"))
        assert resp.status_code == 409, (start, hours)
        assert resp.json()["error"]["code"] == "seat_conflict"
    assert book(client, seat, local(2, 12), 2, headers=auth("stu-002")).status_code == 201
    assert book(client, seat, local(2, 8), 2, headers=auth("stu-003")).status_code == 201


def test_same_user_cannot_hold_two_overlapping_seats(client, clock, seeded):
    seats = seeded["seats"]
    assert book(client, seats["LIB-101-01"], local(2, 10)).status_code == 201
    resp = book(client, seats["A-201-01"], local(2, 11), 1)
    assert resp.status_code == 409
    assert resp.json()["error"]["code"] == "user_overlap"


def test_rule_violations_are_rejected_without_writing(client, clock, seeded, engine):
    seats = seeded["seats"]
    cases = [
        (book(client, seats["LIB-101-01"], local(2, 10, 30)), 422, "not_whole_hour"),
        (book(client, seats["LIB-101-01"], local(2, 10), 5), 422, "invalid_duration"),
        (book(client, seats["LIB-101-01"], local(2, 7), 1), 422, "start_not_in_future"),
        (book(client, seats["LIB-101-01"], local(10, 10), 1), 422, "beyond_booking_horizon"),
        (book(client, seats["LIB-101-01"], local(2, 21), 2), 422, "outside_opening_hours"),
        (
            book(client, seats["CS-305-01"], local(2, 10), headers=auth(department="math")),
            403,
            "department_restricted",
        ),
        (book(client, 999999, local(2, 10)), 404, "seat_not_found"),
    ]
    for resp, status, code in cases:
        assert (resp.status_code, resp.json()["error"]["code"]) == (status, code)
    with engine.connect() as conn:
        assert conn.execute(text("SELECT count(*) FROM m1_reservations")).scalar_one() == 0


def test_department_member_may_book_department_room(client, clock, seeded):
    resp = book(client, seeded["seats"]["CS-305-01"], local(2, 10), headers=auth(department="cs"))
    assert resp.status_code == 201


def test_max_hours_setting_change_takes_effect(client, clock, seeded, engine):
    with engine.begin() as conn:
        conn.execute(
            text(
                "INSERT INTO m1_settings (key, value, updated_by) VALUES ('max_hours', 2, 'admin')"
            )
        )
    resp = book(client, seeded["seats"]["LIB-101-01"], local(2, 10), 3)
    assert resp.status_code == 422
    assert resp.json()["error"]["details"] == {"max_hours": 2}


def test_idempotent_retry_returns_the_same_reservation(client, clock, seeded, engine):
    seat = seeded["seats"]["LIB-101-01"]
    first = book(client, seat, local(2, 10), key="req-1")
    again = book(client, seat, local(2, 10), key="req-1")
    assert (first.status_code, again.status_code) == (201, 200)
    assert again.json()["id"] == first.json()["id"]
    reused = book(client, seeded["seats"]["LIB-101-02"], local(2, 14), key="req-1")
    assert reused.status_code == 409 and reused.json()["error"]["code"] == "idempotency_key_reused"
    # The same key from a different user is a different request.
    other = book(
        client, seeded["seats"]["LIB-101-03"], local(2, 10), headers=auth("stu-002"), key="req-1"
    )
    assert other.status_code == 201
    with engine.connect() as conn:
        assert conn.execute(text("SELECT count(*) FROM m1_reservations")).scalar_one() == 2


def test_cancel_releases_the_seat_and_records_the_source(client, clock, seeded, engine):
    seat = seeded["seats"]["LIB-101-01"]
    rid = book(client, seat, local(2, 10)).json()["id"]
    resp = client.post(f"{URL}/{rid}/cancel", headers=auth())
    assert resp.status_code == 200
    assert (resp.json()["status"], resp.json()["cancel_reason"]) == ("cancelled", "user_cancelled")
    assert book(client, seat, local(2, 10), headers=auth("stu-002")).status_code == 201
    again = client.post(f"{URL}/{rid}/cancel", headers=auth())
    assert again.status_code == 409 and again.json()["error"]["code"] == "not_cancellable"
    with engine.connect() as conn:
        trail = conn.execute(
            text(
                "SELECT source_type, source_id, action, actor_id "
                "FROM m1_seat_state_events ORDER BY id"
            )
        ).all()
    assert trail[:2] == [
        ("m1_reservation", str(rid), "reserved", "stu-001"),
        ("m1_reservation", str(rid), "cancelled", "stu-001"),
    ]


def test_cancel_is_refused_once_the_slot_has_started(client, clock, seeded):
    rid = book(client, seeded["seats"]["LIB-101-01"], local(2, 10)).json()["id"]
    clock.set(local(2, 10))
    resp = client.post(f"{URL}/{rid}/cancel", headers=auth())
    assert resp.status_code == 409 and resp.json()["error"]["code"] == "cancel_window_closed"


def test_users_cannot_read_or_cancel_each_others_reservations(client, clock, seeded):
    rid = book(client, seeded["seats"]["LIB-101-01"], local(2, 10)).json()["id"]
    intruder = auth("stu-002")
    assert client.get(f"{URL}/{rid}", headers=intruder).status_code == 404
    assert client.post(f"{URL}/{rid}/cancel", headers=intruder).status_code == 404
    assert client.get(f"{URL}/me", headers=intruder).json()["items"] == []
    assert client.get(f"{URL}/{rid}", headers=auth()).json()["status"] == "booked"


def test_history_filters_by_status_and_orders_newest_first(client, clock, seeded):
    seats = seeded["seats"]
    early = book(client, seats["LIB-101-01"], local(2, 9), 1).json()["id"]
    late = book(client, seats["LIB-101-01"], local(3, 9), 1).json()["id"]
    client.post(f"{URL}/{early}/cancel", headers=auth())
    assert [r["id"] for r in client.get(f"{URL}/me", headers=auth()).json()["items"]] == [
        late,
        early,
    ]
    booked = client.get(f"{URL}/me", params={"status": "booked"}, headers=auth()).json()["items"]
    assert [r["id"] for r in booked] == [late]


def test_reservation_response_never_contains_checkin_code(client, clock, seeded):
    body = book(client, seeded["seats"]["LIB-101-01"], local(2, 10)).json()
    assert not any("code" in key and key not in ("seat_code", "room_code") for key in body)


def test_booking_requires_reserve_permission(client, clock, seeded):
    resp = book(
        client, seeded["seats"]["LIB-101-01"], local(2, 10), headers=auth(perms=("m1:ops:view",))
    )
    assert resp.status_code == 403
    assert resp.json()["error"]["details"]["required"] == PERM_RESERVE
