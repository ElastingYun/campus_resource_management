from sqlalchemy import text

from app.modules.m1_reservation.identity import PERM_RESERVE
from tests.m1.conftest import auth, local

URL = "/api/v1/m1/seats/availability"


def _query(client, start, hours=2, headers=None, **params):
    params = {"start_at": start.isoformat(), "hours": hours, **params}
    return client.get(URL, params=params, headers=headers or auth())


def _insert_reservation(engine, seat_id, room_id, start, end, status="booked", user="stu-x"):
    # Test arrangement only: reservations are created through the API once that exists.
    with engine.begin() as conn:
        conn.execute(
            text(
                "INSERT INTO m1_reservations (user_id, seat_id, room_id, start_at, end_at, status) "
                "VALUES (:u, :s, :r, :a, :b, :st)"
            ),
            {"u": user, "s": seat_id, "r": room_id, "a": start, "b": end, "st": status},
        )


def _by_code(resp):
    return {s["seat_code"]: s for s in resp.json()["seats"]}


def test_lists_every_seat_of_a_room_as_available_when_nothing_blocks(client, clock, seeded):
    resp = _query(client, local(2, 10), room_id=seeded["rooms"]["LIB-101"])
    assert resp.status_code == 200
    body = resp.json()
    assert body["start_at"] == "2026-11-02T10:00:00+08:00"
    assert body["end_at"] == "2026-11-02T12:00:00+08:00"
    assert len(body["seats"]) == 12
    assert all(s["available"] and s["reasons"] == [] for s in body["seats"])


def test_outlet_filters(client, clock, seeded):
    room = seeded["rooms"]["LIB-101"]
    with_outlet = _query(client, local(2, 10), room_id=room, has_outlet="true").json()["seats"]
    assert {s["outlet_type"] for s in with_outlet} == {"fixed", "rail"}
    assert len(with_outlet) == 6
    rail = _query(client, local(2, 10), room_id=room, outlet_type="rail").json()["seats"]
    assert [s["seat_code"] for s in rail] == ["LIB-101-05", "LIB-101-06"]


def test_overlapping_active_reservation_blocks_but_adjacent_and_cancelled_do_not(
    client, clock, seeded, engine
):
    room, seats = seeded["rooms"]["LIB-101"], seeded["seats"]
    _insert_reservation(engine, seats["LIB-101-01"], room, local(2, 11), local(2, 13))
    _insert_reservation(
        engine, seats["LIB-101-02"], room, local(2, 8), local(2, 10)
    )  # ends at start
    _insert_reservation(engine, seats["LIB-101-03"], room, local(2, 10), local(2, 12), "cancelled")
    _insert_reservation(engine, seats["LIB-101-04"], room, local(2, 9), local(2, 13), "checked_in")

    result = _by_code(_query(client, local(2, 10), room_id=room))
    assert result["LIB-101-01"]["reasons"] == [{"code": "reserved"}]
    assert result["LIB-101-02"]["available"] is True
    assert result["LIB-101-03"]["available"] is True
    assert result["LIB-101-04"]["reasons"] == [{"code": "reserved"}]


def test_only_available_hides_blocked_seats(client, clock, seeded, engine):
    room, seats = seeded["rooms"]["LIB-101"], seeded["seats"]
    _insert_reservation(engine, seats["LIB-101-01"], room, local(2, 10), local(2, 11))
    codes = _by_code(_query(client, local(2, 10), room_id=room, only_available="true"))
    assert "LIB-101-01" not in codes and len(codes) == 11


def test_department_room_is_restricted_to_its_department(client, clock, seeded):
    room = seeded["rooms"]["CS-305"]
    outsider = _query(client, local(2, 10), room_id=room, headers=auth(department="math"))
    assert all(
        s["reasons"] == [{"code": "department_restricted"}] for s in outsider.json()["seats"]
    )
    member = _query(client, local(2, 10), room_id=room, headers=auth(department="cs"))
    assert all(s["available"] for s in member.json()["seats"])


def test_slot_outside_opening_hours_is_unavailable(client, clock, seeded):
    seats = _query(client, local(2, 21), room_id=seeded["rooms"]["LIB-101"]).json()["seats"]
    assert all(s["reasons"] == [{"code": "outside_opening_hours"}] for s in seats)


def test_disabled_seat_is_unavailable(client, clock, seeded, engine):
    with engine.begin() as conn:
        conn.execute(text("UPDATE seats SET enabled = false WHERE code = 'LIB-101-07'"))
    result = _by_code(_query(client, local(2, 10), room_id=seeded["rooms"]["LIB-101"]))
    assert result["LIB-101-07"]["reasons"] == [{"code": "seat_disabled"}]


def test_invalid_slots_are_rejected_with_codes(client, clock, seeded):
    assert _query(client, local(2, 10, 30)).json()["error"]["code"] == "not_whole_hour"
    assert _query(client, local(2, 10), hours=5).json()["error"]["code"] == "invalid_duration"
    past = _query(client, local(2, 7))
    assert past.status_code == 422 and past.json()["error"]["code"] == "start_not_in_future"


def test_requires_identity_and_permission(client, clock, seeded):
    anonymous = client.get(URL, params={"start_at": local(2, 10).isoformat(), "hours": 1})
    assert anonymous.status_code == 401
    no_perm = _query(client, local(2, 10), headers=auth(perms=("m1:ops:view",)))
    assert no_perm.status_code == 403
    assert no_perm.json()["error"]["details"] == {"required": PERM_RESERVE}


def test_auth_disabled_mode_rejects_even_with_headers(app, client, clock, seeded):
    app.state.config = app.state.config.__class__(
        database_url=app.state.config.database_url, auth_mode="disabled"
    )
    assert _query(client, local(2, 10)).status_code == 401


def test_settings_are_readable_by_any_authenticated_user(client):
    resp = client.get("/api/v1/m1/settings", headers=auth(perms=()))
    assert resp.status_code == 200
    assert resp.json()["max_hours"] == 4
