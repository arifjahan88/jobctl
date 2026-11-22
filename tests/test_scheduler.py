"""Unit tests for the built-in configurable daily/weekday scheduler (`src/jobctl/scheduler.py`)."""

from __future__ import annotations

from datetime import datetime, time as dt_time
import unittest
from zoneinfo import ZoneInfo

from jobctl.scheduler import (
    ScheduleConfig,
    compute_next_run,
    parse_schedule_days,
    parse_schedule_time,
)


def test_parse_schedule_time_valid_and_invalid() -> None:
    assert parse_schedule_time("11:00") == dt_time(11, 0, 0)
    assert parse_schedule_time("09:30:15") == dt_time(9, 30, 15)

    try:
        parse_schedule_time("25:00")
        raise AssertionError("Expected ValueError for hour 25")
    except ValueError:
        pass


def test_parse_schedule_days_variants() -> None:
    assert parse_schedule_days("daily") == frozenset(range(7))
    assert parse_schedule_days("*") == frozenset(range(7))
    assert parse_schedule_days("weekdays") == frozenset({0, 1, 2, 3, 4})
    assert parse_schedule_days("weekends") == frozenset({5, 6})
    assert parse_schedule_days("sun,mon,wed") == frozenset({6, 0, 2})


def test_compute_next_run_before_and_after_target_time() -> None:
    tz = ZoneInfo("Asia/Dhaka")
    sched_daily = ScheduleConfig(
        run_time=dt_time(11, 0),
        weekdays=frozenset(range(7)),
        tz_name="Asia/Dhaka",
    )

    # Sunday 2026-11-22 10:15 -> should schedule for today 2026-11-22 11:00
    morning = datetime(2026, 11, 22, 10, 15, tzinfo=tz)
    next_morning = compute_next_run(morning, sched_daily)
    assert next_morning == datetime(2026, 11, 22, 11, 0, tzinfo=tz)

    # Sunday 2026-11-22 12:05 -> should schedule for tomorrow 2026-11-23 11:00
    afternoon = datetime(2026, 11, 22, 12, 5, tzinfo=tz)
    next_afternoon = compute_next_run(afternoon, sched_daily)
    assert next_afternoon == datetime(2026, 11, 23, 11, 0, tzinfo=tz)


def test_compute_next_run_respects_custom_weekdays() -> None:
    tz = ZoneInfo("Asia/Dhaka")
    # Only Wednesday (2) and Friday (4)
    sched_wed_fri = ScheduleConfig(
        run_time=dt_time(11, 0),
        weekdays=parse_schedule_days("wed,fri"),
        tz_name="Asia/Dhaka",
    )

    # Sunday 2026-11-22 12:00 -> next Wednesday is 2026-11-25 11:00
    sun_noon = datetime(2026, 11, 22, 12, 0, tzinfo=tz)
    next_run = compute_next_run(sun_noon, sched_wed_fri)
    assert next_run == datetime(2026, 11, 25, 11, 0, tzinfo=tz)


class TestScheduler(unittest.TestCase):
    def test_all(self) -> None:
        test_parse_schedule_time_valid_and_invalid()
        test_parse_schedule_days_variants()
        test_compute_next_run_before_and_after_target_time()
        test_compute_next_run_respects_custom_weekdays()
