import threading

import pytest
from sqlalchemy import text
from sqlalchemy.orm import sessionmaker

from app.modules.m1_reservation import reservations, restrictions
from app.modules.m1_reservation.errors import M1Error
from app.modules.m1_reservation.identity import PERM_RESERVE, CurrentUser
from tests.m1.conftest import SH, auth, local
from tests.m1.test_jobs import run, status_of, violation_count
from tests.m1.test_reservations_api import book

M2 = auth("svc-m2", perms=(restrictions.PERMISSIONS["m2_approval"],))
M3 = auth("svc-m3", perms=(restrictions.PERMISSIONS["m3_repair"],))
BASE = "/api/v1/m1/restrictions"


def apply(client, source_type, source_id, room_id, start, end=None, seat_id=None, headers=None):
    body = {"room_id": room_id, "start_at": start.isoformat()}
    if end is not None:
        body["end_at"] = end.isoformat()
    if seat_id is not None:
        body["seat_id"] = seat_id
    who = headers or (M2 if source_type == "m2_approval" else M3)
    return client.put(f"{BASE}/{source_type}/{source_id}", json=body, headers=who)


def release(client, source_type, source_id, reason=None, headers=None):
    if reason is None:
        reason = "accepted" if source_type == "m3_repair" else "done"
    who = headers or (M2 if source_type == "m2_approval" else M3)
    return client.post(f"{BASE}/{source_type}/{source_id}/release", json={"reason": reason}, headers=who)


def seats_at(client, room_id, start, hours=1):
    resp = client.get(
        "/api/v1/m1/seats/availability",
        params={"start_at": start.isoformat(), "hours": hours, "room_id": room_id},
        headers=auth("stu-look"),
    )
    return resp.json()["seats"]


def test_m2_approval_blocks_the_whole_room_only_within_its_window(client, clock, seeded):
    lib, a201 = seeded["rooms"]["LIB-101"], seeded["rooms"]["A-201"]
    resp = apply(client, "m2_approval", "APR-1", lib, local(2, 10), local(2, 12))
    assert resp.status_code == 201
    assert resp.json()["affected_reservation_ids"] == []

    inside = seats_at(client, lib, local(2, 11))
    assert all(s["reasons"] == [{"code": "m2_approval", "source_type": "m2_approval", "source_id": "APR-1"}] for s in inside)
    assert all(s["available"] for s in seats_at(client, lib, local(2, 12)))
    assert all(s["available"] for s in seats_at(client, a201, local(2, 11)))

    refused = book(client, seeded["seats"]["LIB-101-01"], local(2, 11), 1)
    assert refused.status_code == 409 and refused.json()["error"]["code"] == "seat_restricted"


def test_releasing_an_approval_restores_booking(client, clock, seeded):
    lib = seeded["rooms"]["LIB-101"]
    apply(client, "m2_approval", "APR-1", lib, local(2, 10), local(2, 12))
    assert release(client, "m2_approval", "APR-1", "rejected").json()["status"] == "released"
    assert all(s["available"] for s in seats_at(client, lib, local(2, 11)))
    assert book(client, seeded["seats"]["LIB-101-01"], local(2, 11), 1).status_code == 201


def test_open_ended_repair_blocks_until_acceptance(client, clock, seeded):
    lib = seeded["rooms"]["LIB-101"]
    assert apply(client, "m3_repair", "WO-1", lib, local(2, 7)).status_code == 201
    assert not any(s["available"] for s in seats_at(client, lib, local(6, 20)))
    assert all(s["available"] for s in seats_at(client, seeded["rooms"]["A-201"], local(6, 20)))
    for seat_code in ("LIB-101-01", "LIB-101-03"):
        response = book(client, seeded["seats"][seat_code], local(2, 11), 1)
        assert response.status_code == 409
        assert response.json()["error"]["code"] == "seat_restricted"
    release(client, "m3_repair", "WO-1", "accepted")
    assert all(s["available"] for s in seats_at(client, lib, local(6, 20)))


def test_releasing_one_source_keeps_blocks_from_the_others(client, clock, seeded):
    lib = seeded["rooms"]["LIB-101"]
    apply(client, "m3_repair", "WO-1", lib, local(2, 8))
    apply(client, "m3_repair", "WO-2", lib, local(2, 8))
    apply(client, "m2_approval", "APR-1", lib, local(2, 10), local(2, 12))

    release(client, "m3_repair", "WO-1", "accepted")
    reasons = seats_at(client, lib, local(2, 11))[0]["reasons"]
    assert [r["source_id"] for r in reasons] == ["WO-2", "APR-1"]
    release(client, "m2_approval", "APR-1", "revoked")
    assert [r["source_id"] for r in seats_at(client, lib, local(2, 11))[0]["reasons"]] == ["WO-2"]
    release(client, "m3_repair", "WO-2", "accepted")
    assert all(s["available"] for s in seats_at(client, lib, local(2, 11)))


@pytest.mark.parametrize("source_type", ["m2_approval", "m3_repair"])
def test_seat_level_restriction_is_rejected(client, clock, seeded, source_type):
    lib, seat = seeded["rooms"]["LIB-101"], seeded["seats"]["LIB-101-03"]
    end = local(2, 12) if source_type == "m2_approval" else None
    response = apply(client, source_type, "SCOPE-1", lib, local(2, 8), end, seat_id=seat)
    assert response.status_code == 422
    assert response.json()["error"]["code"] == "room_scope_required"
    assert all(s["available"] for s in seats_at(client, lib, local(2, 11)))


def test_repair_cannot_expire_without_acceptance(client, clock, seeded):
    lib = seeded["rooms"]["LIB-101"]
    response = apply(client, "m3_repair", "WO-TIMED", lib, local(2, 8), local(2, 12))
    assert response.status_code == 422
    assert response.json()["error"]["code"] == "repair_end_forbidden"
    assert client.get(f"{BASE}/m3_repair/WO-TIMED", headers=M3).status_code == 404


@pytest.mark.parametrize("reason", ["done", "completed", "cancelled"])
def test_repair_requires_acceptance_before_release(client, clock, seeded, engine, reason):
    lib = seeded["rooms"]["LIB-101"]
    assert apply(client, "m3_repair", "WO-1", lib, local(2, 8)).status_code == 201
    response = release(client, "m3_repair", "WO-1", reason)
    assert response.status_code == 422
    assert response.json()["error"]["code"] == "repair_acceptance_required"
    assert client.get(f"{BASE}/m3_repair/WO-1", headers=M3).json()["status"] == "active"
    assert not any(s["available"] for s in seats_at(client, lib, local(6, 20)))
    with engine.connect() as connection:
        count = connection.execute(text(
            "SELECT count(*) FROM m1_seat_state_events WHERE action = 'restriction_released'"
        )).scalar_one()
    assert count == 0
    assert release(client, "m3_repair", "WO-1", "accepted").status_code == 200
    assert all(s["available"] for s in seats_at(client, lib, local(6, 20)))


def test_apply_is_idempotent_and_detects_conflicting_reuse(client, clock, seeded):
    lib = seeded["rooms"]["LIB-101"]
    first = apply(client, "m2_approval", "APR-1", lib, local(2, 10), local(2, 12))
    again = apply(client, "m2_approval", "APR-1", lib, local(2, 10), local(2, 12))
    assert (first.status_code, again.status_code) == (201, 200)
    changed = apply(client, "m2_approval", "APR-1", lib, local(2, 10), local(2, 13))
    assert changed.status_code == 409 and changed.json()["error"]["code"] == "restriction_conflict"
    release(client, "m2_approval", "APR-1")
    revived = apply(client, "m2_approval", "APR-1", lib, local(2, 10), local(2, 12))
    assert revived.status_code == 409 and revived.json()["error"]["code"] == "restriction_released"


def test_release_is_idempotent_and_unknown_sources_are_404(client, clock, seeded, engine):
    apply(client, "m3_repair", "WO-1", seeded["rooms"]["LIB-101"], local(2, 8))
    assert release(client, "m3_repair", "WO-1").status_code == 200
    assert release(client, "m3_repair", "WO-1").status_code == 200
    assert release(client, "m3_repair", "WO-404").status_code == 404
    with engine.connect() as conn:
        n = conn.execute(text("SELECT count(*) FROM m1_seat_state_events WHERE action = 'restriction_released'")).scalar_one()
    assert n == 1


def test_callers_may_only_touch_their_own_source_type(client, clock, seeded):
    lib = seeded["rooms"]["LIB-101"]
    apply(client, "m3_repair", "WO-1", lib, local(2, 8))
    assert release(client, "m3_repair", "WO-1", headers=M2).status_code == 403
    assert apply(client, "m3_repair", "WO-2", lib, local(2, 8), headers=M2).status_code == 403
    assert apply(client, "m2_approval", "APR-1", lib, local(2, 10), local(2, 12), headers=auth()).status_code == 403
    assert client.get(f"{BASE}/m3_repair/WO-1", headers=M3).json()["status"] == "active"
    assert client.get(f"{BASE}/m3_repair/WO-1", headers=M2).status_code == 403


def test_invalid_restrictions_are_rejected(client, clock, seeded):
    lib, other_seat = seeded["rooms"]["LIB-101"], seeded["seats"]["A-201-01"]
    cases = [
        (apply(client, "m2_approval", "APR-1", lib, local(2, 10)), 422, "end_required"),
        (apply(client, "m2_approval", "APR-2", lib, local(2, 10), local(2, 10)), 422, "invalid_interval"),
        (apply(client, "m3_repair", "WO-1", lib, local(2, 8), seat_id=other_seat), 422, "room_scope_required"),
        (apply(client, "m3_repair", "WO-2", 999999, local(2, 8)), 404, "room_not_found"),
        (apply(client, "m3_repair", "bad id!", lib, local(2, 8)), 422, "invalid_source_id"),
    ]
    for resp, status, code in cases:
        assert (resp.status_code, resp.json()["error"]["code"]) == (status, code)


def test_existing_reservations_are_reported_not_cancelled(client, clock, seeded):
    lib = seeded["rooms"]["LIB-101"]
    inside = book(client, seeded["seats"]["LIB-101-01"], local(2, 10), 2).json()["id"]
    book(client, seeded["seats"]["LIB-101-02"], local(2, 8), 2, headers=auth("stu-002"))  # ends before
    resp = apply(client, "m2_approval", "APR-1", lib, local(2, 11), local(2, 13))
    assert resp.json()["affected_reservation_ids"] == [inside]
    assert status_of(client, inside)["status"] == "booked"


def test_every_source_is_traceable_in_the_state_trail(client, clock, seeded, engine):
    lib = seeded["rooms"]["LIB-101"]
    rid = book(client, seeded["seats"]["LIB-101-01"], local(2, 14), 1).json()["id"]
    apply(client, "m2_approval", "APR-1", lib, local(2, 10), local(2, 12))
    apply(client, "m3_repair", "WO-1", lib, local(2, 8))
    release(client, "m3_repair", "WO-1", "accepted")
    with engine.connect() as conn:
        trail = conn.execute(
            text("SELECT source_type, source_id, action, actor_id FROM m1_seat_state_events ORDER BY id")
        ).all()
    assert [tuple(t) for t in trail] == [
        ("m1_reservation", str(rid), "reserved", "stu-001"),
        ("m2_approval", "APR-1", "restriction_applied", "svc-m2"),
        ("m3_repair", "WO-1", "restriction_applied", "svc-m3"),
        ("m3_repair", "WO-1", "restriction_released", "svc-m3"),
    ]


def test_no_violation_when_the_room_was_under_repair(client, clock, seeded, engine):
    lib = seeded["rooms"]["LIB-101"]
    rid = book(client, seeded["seats"]["LIB-101-01"], local(2, 10)).json()["id"]
    clock.set(local(2, 9))
    apply(client, "m3_repair", "WO-1", lib, local(2, 9))
    clock.set(local(2, 10, 5))
    release(client, "m3_repair", "WO-1", "accepted")  # lifted after the slot began: still counts
    report = run(engine, local(2, 10, 15))
    assert (report.no_shows, report.restricted_cancellations) == (0, 1)
    body = status_of(client, rid)
    assert (body["status"], body["cancel_reason"]) == ("cancelled", "restricted")
    assert violation_count(engine) == 0


def test_restriction_lifted_before_the_slot_does_not_excuse_a_no_show(client, clock, seeded, engine):
    lib = seeded["rooms"]["LIB-101"]
    rid = book(client, seeded["seats"]["LIB-101-01"], local(2, 10)).json()["id"]
    apply(client, "m3_repair", "WO-1", lib, local(2, 7, 30))
    clock.set(local(2, 9))
    release(client, "m3_repair", "WO-1", "accepted")
    run(engine, local(2, 10, 15))
    assert status_of(client, rid)["status"] == "no_show"
    assert violation_count(engine) == 1


def test_booking_racing_a_restriction_is_refused_or_reported(engine, seeded):
    factory = sessionmaker(engine, expire_on_commit=False)
    svc = CurrentUser("svc-m2", None, frozenset({restrictions.PERMISSIONS["m2_approval"]}))
    lib = seeded["rooms"]["LIB-101"]
    for i in range(7):  # each round races in its own window: 08-10, 10-12, ... 20-22
        start, end = local(3, 8 + 2 * i), local(3, 10 + 2 * i)
        student = CurrentUser(f"stu-r{i}", None, frozenset({PERM_RESERVE}))
        barrier = threading.Barrier(2)
        out = {}

        def do_book(i=i, student=student, start=start):
            with factory() as s:
                barrier.wait()
                try:
                    r, _ = reservations.create(
                        s, student, seat_id=seeded["seats"][f"LIB-101-{i + 1:02d}"], start_at=start,
                        hours=2, idempotency_key=None, now=local(2, 7), tz=SH,
                    )
                    out["booked"] = r.id
                except M1Error as err:
                    out["booked"] = err.code

        def do_apply(i=i, start=start, end=end):
            with factory() as s:
                barrier.wait()
                _, _, affected = restrictions.apply(
                    s, svc, "m2_approval", f"APR-R{i}", room_id=lib, seat_id=None, start_at=start,
                    end_at=end, note="", now=local(2, 7), tz=SH,
                )
                out["affected"] = affected

        threads = [threading.Thread(target=do_book), threading.Thread(target=do_apply)]
        [t.start() for t in threads]
        [t.join() for t in threads]
        if isinstance(out["booked"], int):
            assert out["booked"] in out["affected"]
        else:
            assert out["booked"] == "seat_restricted"
