from app.modules.m1_reservation.identity import PERM_OPS_VIEW, PERM_SETTINGS_MANAGE
from tests.m1.conftest import auth, local
from tests.m1.test_checkin import _check_in, _code
from tests.m1.test_jobs import run
from tests.m1.test_reservations_api import book
from tests.m1.test_restrictions import apply

OPS = auth("ops-01", perms=(PERM_OPS_VIEW,))
ADMIN = auth("admin-01", perms=(PERM_SETTINGS_MANAGE,))


def test_daily_usage_aggregates_by_room_without_personal_data(client, clock, seeded, engine):
    seats, lib = seeded["seats"], seeded["rooms"]["LIB-101"]
    present = book(client, seats["LIB-101-01"], local(2, 10), 2, headers=auth("stu-001")).json()[
        "id"
    ]
    book(client, seats["LIB-101-02"], local(2, 10), 1, headers=auth("stu-002"))  # becomes a no-show
    gone = book(client, seats["LIB-101-03"], local(2, 14), 1, headers=auth("stu-003")).json()["id"]
    client.post(f"/api/v1/m1/reservations/{gone}/cancel", headers=auth("stu-003"))
    book(client, seats["LIB-101-04"], local(3, 10), 1, headers=auth("stu-004"))  # other day
    clock.set(local(2, 10))
    _check_in(client, present, _code(client, lib), headers=auth("stu-001"))
    run(engine, local(2, 10, 15))

    resp = client.get("/api/v1/m1/ops/usage", params={"date": "2026-11-02"}, headers=OPS)
    assert resp.status_code == 200
    room = next(r for r in resp.json()["rooms"] if r["room_code"] == "LIB-101")
    assert room["reservations"] == {"booked": 0, "checked_in": 1, "cancelled": 1, "no_show": 1}
    assert room["seat_count"] == 12
    assert room["capacity_seat_hours"] == 12 * 14
    assert room["checked_in_seat_hours"] == 2
    assert room["utilization"] == round(2 / 168, 4)
    assert "stu-" not in resp.text


def test_ops_views_require_ops_permission(client, clock, seeded):
    assert (
        client.get(
            "/api/v1/m1/ops/usage", params={"date": "2026-11-02"}, headers=auth()
        ).status_code
        == 403
    )
    room = seeded["rooms"]["LIB-101"]
    assert (
        client.get(
            "/api/v1/m1/ops/seat-events", params={"room_id": room}, headers=auth()
        ).status_code
        == 403
    )


def test_seat_trail_shows_sources_and_hides_students(client, clock, seeded):
    lib, seat = seeded["rooms"]["LIB-101"], seeded["seats"]["LIB-101-01"]
    rid = book(client, seat, local(2, 14), 1).json()["id"]
    apply(client, "m3_repair", "WO-1", lib, local(2, 8))
    book(
        client, seeded["seats"]["A-201-01"], local(2, 16), 1, headers=auth("stu-002")
    )  # other room
    trail = client.get(
        "/api/v1/m1/ops/seat-events", params={"room_id": lib, "seat_id": seat}, headers=OPS
    ).json()
    assert [(e["source_type"], e["source_id"], e["action"], e["actor_id"]) for e in trail] == [
        ("m3_repair", "WO-1", "restriction_applied", "svc-m3"),
        ("m1_reservation", str(rid), "reserved", None),
    ]


def test_admin_can_change_settings_and_the_change_applies(client, clock, seeded):
    resp = client.put("/api/v1/m1/settings", json={"max_hours": 2}, headers=ADMIN)
    assert resp.status_code == 200 and resp.json()["max_hours"] == 2
    assert client.get("/api/v1/m1/settings", headers=auth()).json()["max_hours"] == 2
    assert book(client, seeded["seats"]["LIB-101-01"], local(2, 10), 3).status_code == 422
    assert book(client, seeded["seats"]["LIB-101-01"], local(2, 10), 2).status_code == 201


def test_settings_changes_are_validated_and_restricted(client):
    assert (
        client.put("/api/v1/m1/settings", json={"max_hours": 2}, headers=auth()).status_code == 403
    )
    for body in ({"max_hours": 0}, {"late_remind_minutes": 15}, {"no_show_minutes": 5}):
        resp = client.put("/api/v1/m1/settings", json=body, headers=ADMIN)
        assert resp.status_code == 422 and resp.json()["error"]["code"] == "invalid_setting", body
    assert client.put("/api/v1/m1/settings", json={"bogus": 1}, headers=ADMIN).status_code == 422
    assert client.get("/api/v1/m1/settings", headers=auth()).json()["max_hours"] == 4
