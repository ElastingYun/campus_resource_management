from datetime import UTC, datetime, time, timedelta

import pytest

from app.modules.m1_reservation.errors import M1Error
from app.modules.m1_reservation.settings import M1Settings
from app.modules.m1_reservation.timeslots import (
    check_booking_window,
    make_slot,
    within_opening_hours,
)
from tests.m1.conftest import SH, local

DEFAULTS = M1Settings()


def test_naive_input_is_business_local_time():
    slot = make_slot(datetime(2026, 11, 2, 10, 0), 2, SH, DEFAULTS)
    assert slot.start_at == datetime(2026, 11, 2, 2, 0, tzinfo=UTC)
    assert slot.end_at - slot.start_at == timedelta(hours=2)


def test_aware_input_is_converted_not_reinterpreted():
    slot = make_slot(datetime(2026, 11, 2, 2, 0, tzinfo=UTC), 1, SH, DEFAULTS)
    assert slot.start_at.astimezone(SH) == local(2, 10)


@pytest.mark.parametrize("minute,second", [(30, 0), (0, 1)])
def test_non_whole_hour_start_is_rejected(minute, second):
    with pytest.raises(M1Error) as err:
        make_slot(datetime(2026, 11, 2, 9, minute, second), 1, SH, DEFAULTS)
    assert err.value.code == "not_whole_hour"


@pytest.mark.parametrize("hours", [0, -1, 5])
def test_duration_outside_one_to_max_hours_is_rejected(hours):
    with pytest.raises(M1Error) as err:
        make_slot(local(2, 9), hours, SH, DEFAULTS)
    assert err.value.code == "invalid_duration"


def test_max_hours_setting_is_honoured():
    assert make_slot(local(2, 9), 4, SH, DEFAULTS).hours == 4
    with pytest.raises(M1Error):
        make_slot(local(2, 9), 3, SH, M1Settings(max_hours=2))


def test_booking_window_requires_future_start_within_horizon():
    now = local(2, 9)
    with pytest.raises(M1Error) as err:
        check_booking_window(make_slot(local(2, 9), 1, SH, DEFAULTS), now, DEFAULTS)
    assert err.value.code == "start_not_in_future"
    check_booking_window(make_slot(local(9, 9), 1, SH, DEFAULTS), now, DEFAULTS)  # exactly 7 days
    with pytest.raises(M1Error) as err:
        check_booking_window(make_slot(local(9, 10), 1, SH, DEFAULTS), now, DEFAULTS)
    assert err.value.code == "beyond_booking_horizon"


@pytest.mark.parametrize(
    "start_hour,hours,expected",
    [(8, 2, True), (20, 2, True), (7, 2, False), (21, 2, False), (23, 1, False)],
)
def test_opening_hours_boundaries(start_hour, hours, expected):
    slot = make_slot(local(2, start_hour), hours, SH, DEFAULTS)
    assert within_opening_hours(slot, time(8), time(22), SH) is expected
