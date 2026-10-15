from datetime import datetime, timedelta, timezone

from app.main import (
    attendance_date_for,
    compute_late_minutes,
    compute_overtime,
    compute_work_hours,
    half_day,
)

IST = timezone(timedelta(hours=5, minutes=30))


def local_time(year, month, day, hour, minute, second=0):
    return datetime(year, month, day, hour, minute, second, tzinfo=IST)


def test_late_arrival_grace_boundary():
    # Shift starts at 09:30; exactly ten minutes late is still within grace.
    assert compute_late_minutes(local_time(2026, 10, 15, 9, 40), "09:30") == 0
    # One second beyond the grace period returns elapsed whole minutes.
    assert compute_late_minutes(local_time(2026, 10, 15, 9, 40, 1), "09:30") == 10


def test_late_minutes_are_floored():
    assert compute_late_minutes(local_time(2026, 10, 15, 10, 15, 59), "09:30") == 45


def test_overtime_requires_at_least_thirty_minutes():
    assert compute_overtime(
        local_time(2026, 10, 15, 17, 29, 59), "17:00", "2026-10-15", "09:30"
    ) == 0
    assert compute_overtime(
        local_time(2026, 10, 15, 17, 30), "17:00", "2026-10-15", "09:30"
    ) == 30


def test_overtime_minutes_are_floored():
    assert compute_overtime(
        local_time(2026, 10, 15, 17, 45, 59), "17:00", "2026-10-15", "09:30"
    ) == 45


def test_overnight_overtime():
    # Shift runs from 22:00 on Oct 15 to 06:00 on Oct 16.
    assert compute_overtime(
        local_time(2026, 10, 16, 6, 30), "06:00", "2026-10-15", "22:00"
    ) == 30


def test_work_hours_use_half_up_rounding():
    # 3618 seconds = 1.005 hours, which must round half-up to 1.01.
    start = local_time(2026, 10, 15, 9, 0)
    end = start + timedelta(seconds=3618)
    assert compute_work_hours(start, end) == 1.01


def test_half_day_boundary():
    assert half_day(4.49) is True
    assert half_day(4.50) is False
    assert half_day(None) is False


def test_early_morning_overnight_punch_belongs_to_previous_day():
    employee = {"shift_start": "22:00", "shift_end": "06:00"}
    assert attendance_date_for(
        local_time(2026, 10, 16, 5, 59), employee
    ) == "2026-10-15"
