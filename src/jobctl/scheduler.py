"""Built-in configurable scheduler daemon (`jobctl daemon`) for Docker `-d` background runs."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, time as dt_time, timedelta
import logging
import os
import signal
import time
from typing import Callable
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

from jobctl.config import AppConfig
from jobctl.notifiers.telegram import load_dotenv_into_environ, send_telegram_report
from jobctl.pipeline import run_pipeline

WEEKDAY_MAP: dict[str, int] = {
    "mon": 0,
    "monday": 0,
    "tue": 1,
    "tues": 1,
    "tuesday": 1,
    "wed": 2,
    "wednesday": 2,
    "thu": 3,
    "thur": 3,
    "thurs": 3,
    "thursday": 3,
    "fri": 4,
    "friday": 4,
    "sat": 5,
    "saturday": 5,
    "sun": 6,
    "sunday": 6,
}

WEEKDAY_NAMES: tuple[str, ...] = ("Mon", "Tue", "Wed", "Thu", "Fri", "Sat", "Sun")


@dataclass(slots=True)
class ScheduleConfig:
    run_time: dt_time
    weekdays: frozenset[int]
    tz_name: str
    run_on_startup: bool = False

    @property
    def timezone(self) -> ZoneInfo:
        try:
            return ZoneInfo(self.tz_name)
        except ZoneInfoNotFoundError:
            return ZoneInfo("UTC")

    @property
    def days_label(self) -> str:
        if len(self.weekdays) == 7:
            return "Every day (daily)"
        ordered = sorted(self.weekdays)
        return ", ".join(WEEKDAY_NAMES[d] for d in ordered)


def parse_schedule_time(time_str: str) -> dt_time:
    """
    Parse a 24-hour `HH:MM` (or `HH:MM:SS`) string into `datetime.time`.
    Raises ValueError on invalid format.
    """
    cleaned = (time_str or "").strip()
    if not cleaned:
        raise ValueError("Schedule time cannot be empty (expected HH:MM, e.g. '11:00')")

    parts = cleaned.split(":")
    if len(parts) not in (2, 3):
        raise ValueError(f"Invalid schedule time '{time_str}'. Expected 24-hour HH:MM (e.g. '11:00').")

    try:
        hour = int(parts[0])
        minute = int(parts[1])
        second = int(parts[2]) if len(parts) == 3 else 0
        return dt_time(hour=hour, minute=minute, second=second)
    except ValueError as exc:
        raise ValueError(
            f"Invalid schedule time '{time_str}'. Expected 24-hour HH:MM (00:00 to 23:59)."
        ) from exc


def parse_schedule_days(days_str: str) -> frozenset[int]:
    """
    Parse a days specification into a set of weekday integers (0=Monday .. 6=Sunday).
    Accepts:
      - "daily", "all", "everyday", "*" -> all 7 days
      - "weekdays" -> Mon..Fri (0..4)
      - "weekends" -> Sat, Sun (5, 6)
      - Comma-separated day names: "sun,mon,tue,wed,thu" or "mon,wed,fri"
    """
    cleaned = (days_str or "").strip().lower()
    if not cleaned or cleaned in ("*", "daily", "all", "everyday", "every"):
        return frozenset(range(7))
    if cleaned == "weekdays":
        return frozenset({0, 1, 2, 3, 4})
    if cleaned == "weekends":
        return frozenset({5, 6})

    result: set[int] = set()
    for token in cleaned.split(","):
        tok = token.strip()
        if not tok:
            continue
        if tok not in WEEKDAY_MAP:
            valid = "daily, weekdays, or comma-separated mon,tue,wed,thu,fri,sat,sun"
            raise ValueError(f"Unknown schedule day '{tok}'. Valid options: {valid}")
        result.add(WEEKDAY_MAP[tok])

    if not result:
        raise ValueError(f"No valid days found in '{days_str}'.")
    return frozenset(result)


def load_schedule_from_env(
    time_override: str | None = None,
    days_override: str | None = None,
    tz_override: str | None = None,
    run_on_startup_override: bool | None = None,
) -> ScheduleConfig:
    """Build ScheduleConfig from environment variables with optional CLI overrides."""
    load_dotenv_into_environ()

    raw_time = time_override or os.environ.get("JOBCTL_SCHEDULE_TIME", "11:00")
    raw_days = days_override or os.environ.get("JOBCTL_SCHEDULE_DAYS", "daily")
    tz_name = (tz_override or os.environ.get("TZ", "Asia/Dhaka")).strip() or "Asia/Dhaka"

    if run_on_startup_override is not None:
        run_on_startup = run_on_startup_override
    else:
        raw_startup = os.environ.get("JOBCTL_RUN_ON_STARTUP", "false").strip().lower()
        run_on_startup = raw_startup in ("1", "true", "yes", "on")

    return ScheduleConfig(
        run_time=parse_schedule_time(raw_time),
        weekdays=parse_schedule_days(raw_days),
        tz_name=tz_name,
        run_on_startup=run_on_startup,
    )


def compute_next_run(now: datetime, schedule: ScheduleConfig) -> datetime:
    """
    Calculate the next scheduled execution datetime strictly after `now`
    in the schedule's configured timezone.
    """
    tz = schedule.timezone
    local_now = now.astimezone(tz) if now.tzinfo is not None else now.replace(tzinfo=tz)

    for day_offset in range(0, 8):
        candidate_date = (local_now + timedelta(days=day_offset)).date()
        if candidate_date.weekday() not in schedule.weekdays:
            continue
        candidate_dt = datetime.combine(candidate_date, schedule.run_time, tzinfo=tz)
        if candidate_dt > local_now:
            return candidate_dt

    # Fallback (should never happen since weekdays is non-empty and we scan 8 days)
    fallback_date = (local_now + timedelta(days=1)).date()
    return datetime.combine(fallback_date, schedule.run_time, tzinfo=tz)


def run_daemon(
    config_loader: Callable[[], AppConfig],
    schedule: ScheduleConfig,
    selected_sources: list[str] | None = None,
    max_runs: int | None = None,
) -> int:
    """
    Run the continuous background scheduler loop.
    Executes the jobctl pipeline + Telegram notification at the configured time/days.
    """
    logger = logging.getLogger("jobctl")
    stop_requested = False

    def _handle_signal(signum: int, _frame: object) -> None:
        nonlocal stop_requested
        stop_requested = True
        logger.info(f"Received signal {signum}; shutting down jobctl daemon gracefully...")

    signal.signal(signal.SIGTERM, _handle_signal)
    signal.signal(signal.SIGINT, _handle_signal)

    tz = schedule.timezone
    time_str = schedule.run_time.strftime("%H:%M")
    logger.info(
        f"=== jobctl daemon started | Schedule: {schedule.days_label} at {time_str} ({schedule.tz_name}) ==="
    )

    runs_completed = 0

    def _execute_cycle() -> None:
        nonlocal runs_completed
        cycle_now = datetime.now(tz)
        logger.info(f"Starting scheduled jobctl run at {cycle_now.strftime('%Y-%m-%d %H:%M:%S %Z')}...")
        try:
            cfg = config_loader()
            result = run_pipeline(
                cfg,
                selected_sources=selected_sources,
                now=cycle_now,
            )
            date_dir = result.run_paths.date_dir if result.run_paths else None
            skipped_seen = max(0, len(result.matched_jobs) - len(result.exported_jobs))
            send_telegram_report(
                jobs=result.exported_jobs,
                config=cfg,
                run_date_dir=date_dir,
                now=cycle_now,
                skipped_seen_count=skipped_seen,
            )
        except Exception as exc:
            logger.error(f"Scheduled run encountered an error: {exc}")
        runs_completed += 1

    if schedule.run_on_startup and not stop_requested:
        logger.info("JOBCTL_RUN_ON_STARTUP=true -> running initial search immediately...")
        _execute_cycle()
        if max_runs is not None and runs_completed >= max_runs:
            return 0

    while not stop_requested:
        now = datetime.now(tz)
        next_dt = compute_next_run(now, schedule)
        wait_seconds = max(0.0, (next_dt - now).total_seconds())
        hours = int(wait_seconds // 3600)
        minutes = int((wait_seconds % 3600) // 60)

        logger.info(
            f"Next scheduled run: {next_dt.strftime('%Y-%m-%d %H:%M:%S %Z')} "
            f"(in {hours}h {minutes}m)"
        )

        while not stop_requested:
            remaining = (next_dt - datetime.now(tz)).total_seconds()
            if remaining <= 0:
                break
            time.sleep(min(remaining, 5.0))

        if stop_requested:
            break

        _execute_cycle()
        if max_runs is not None and runs_completed >= max_runs:
            break
        # Brief pause so we don't re-trigger within the same second
        time.sleep(1.5)

    logger.info("jobctl daemon stopped.")
    return 0
