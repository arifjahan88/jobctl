"""Command-line interface (`jobctl`) with run, daemon, notify-test, sources, history, and init subcommands."""

from __future__ import annotations

import argparse
from pathlib import Path
import shutil
import sys

from jobctl import __version__
from jobctl.config import KNOWN_SOURCES, load_config
from jobctl.log import setup_logger
from jobctl.notifiers import (
    load_telegram_config_from_env,
    send_telegram_report,
    send_telegram_test_message,
)
from jobctl.pipeline import SOURCE_ORDER, run_pipeline
from jobctl.scheduler import load_schedule_from_env, run_daemon
from jobctl.sources import get_registered_sources
from jobctl.storage import HistoryStore


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="jobctl",
        description="jobctl — Control-plane CLI to aggregate, filter, and score remote engineering jobs.",
    )
    parser.add_argument(
        "--version",
        action="version",
        version=f"jobctl {__version__}",
    )

    subparsers = parser.add_subparsers(dest="command")

    # jobctl run
    run_p = subparsers.add_parser(
        "run",
        help="Fetch, filter (previous 2 days), score, and export matched jobs into search_results/<YYYY-MM-DD>/",
    )
    run_p.add_argument("-c", "--config", type=str, default=None, help="Path to jobctl.toml")
    run_p.add_argument(
        "-s",
        "--sources",
        type=str,
        default=None,
        help="Comma-separated list of sources to query (e.g. greenhouse,ashby,remotive)",
    )
    run_p.add_argument("--min-score", type=int, default=None, help="Override scoring.min_score")
    run_p.add_argument(
        "--days",
        type=int,
        default=None,
        help="Override filters.max_posting_age_days (default: 2 for previous two dates)",
    )
    run_p.add_argument(
        "-f",
        "--format",
        type=str,
        default=None,
        help="Comma-separated output formats (docx,csv,json,md)",
    )
    run_p.add_argument(
        "--results-dir",
        type=str,
        default=None,
        help="Override base results directory (default: search_results)",
    )
    run_p.add_argument(
        "--all",
        action="store_true",
        help="Include previously seen jobs in exported reports",
    )
    run_p.add_argument(
        "--notify",
        action="store_true",
        help="Force sending formatted Telegram job links after the run",
    )
    run_p.add_argument(
        "--no-notify",
        action="store_true",
        help="Disable Telegram notification for this run",
    )
    run_p.add_argument(
        "--dry-run",
        action="store_true",
        help="Run fetch and scoring without writing files or updating SQLite history",
    )
    run_p.add_argument("-v", "--verbose", action="store_true", help="Enable verbose debug logging")

    # jobctl daemon
    daemon_p = subparsers.add_parser(
        "daemon",
        help="Run continuously in background (Docker -d) on a configurable daily/weekday schedule and notify Telegram",
    )
    daemon_p.add_argument("-c", "--config", type=str, default=None, help="Path to jobctl.toml")
    daemon_p.add_argument(
        "-s",
        "--sources",
        type=str,
        default=None,
        help="Optional comma-separated list of sources to query",
    )
    daemon_p.add_argument(
        "--time",
        type=str,
        default=None,
        help="24-hour schedule time HH:MM (overrides JOBCTL_SCHEDULE_TIME, default: 11:00)",
    )
    daemon_p.add_argument(
        "--schedule-days",
        type=str,
        default=None,
        help="Days to run: 'daily', 'weekdays', or 'sun,mon,tue,wed,thu' (overrides JOBCTL_SCHEDULE_DAYS)",
    )
    daemon_p.add_argument(
        "--tz",
        type=str,
        default=None,
        help="IANA timezone name (overrides TZ env var, default: Asia/Dhaka)",
    )
    daemon_p.add_argument(
        "--run-on-startup",
        action="store_true",
        default=None,
        help="Execute one search immediately when the daemon starts before waiting for the scheduled time",
    )
    daemon_p.add_argument("-v", "--verbose", action="store_true", help="Enable verbose debug logging")

    # jobctl notify-test
    sub_notify = subparsers.add_parser(
        "notify-test",
        help="Send a test message to your Telegram chat using TELEGRAM_BOT_TOKEN and TELEGRAM_CHAT_ID",
    )
    sub_notify.add_argument(
        "--env-file",
        type=str,
        default=".env",
        help="Optional path to .env file (default: .env)",
    )

    # jobctl sources
    src_p = subparsers.add_parser("sources", help="List available job portal adapters and their status")
    src_p.add_argument("-c", "--config", type=str, default=None, help="Path to jobctl.toml")

    # jobctl history
    hist_p = subparsers.add_parser("history", help="Inspect or clear matched jobs stored in SQLite")
    hist_p.add_argument("-c", "--config", type=str, default=None, help="Path to jobctl.toml")
    hist_p.add_argument("-n", "--limit", type=int, default=20, help="Number of recent jobs to display")
    hist_p.add_argument(
        "--urls",
        action="store_true",
        help="Show direct apply URLs under each tracked job",
    )
    hist_p.add_argument(
        "--clear",
        action="store_true",
        help="Delete all tracked jobs from SQLite history",
    )
    hist_p.add_argument(
        "--older-than",
        type=int,
        default=None,
        metavar="DAYS",
        help="Delete tracked jobs last seen more than DAYS days ago",
    )
    hist_p.add_argument(
        "--path",
        action="store_true",
        help="Print the resolved path of the SQLite history database and exit",
    )

    # jobctl init
    init_p = subparsers.add_parser("init", help="Create jobctl.toml from jobctl.example.toml")
    init_p.add_argument(
        "-o",
        "--output",
        type=str,
        default="jobctl.toml",
        help="Target path for generated configuration file",
    )
    init_p.add_argument("--force", action="store_true", help="Overwrite existing jobctl.toml")

    return parser


def _cmd_init(args: argparse.Namespace) -> int:
    target = Path(args.output)
    if target.exists() and not args.force:
        print(f"Configuration file already exists: {target} (use --force to overwrite)")
        return 1

    example = Path("jobctl.example.toml")
    if example.exists():
        shutil.copyfile(example, target)
    else:
        target.write_text(
            '[profile]\nrole_title = "Software Engineer"\nlevel = "mid"\n\n'
            "[filters]\nmax_posting_age_days = 2\nrequire_posted_date = true\n\n"
            '[output]\nresults_dir = "search_results"\n',
            encoding="utf-8",
        )
    print(f"Created configuration file: {target.resolve()}")
    return 0


def _cmd_sources(args: argparse.Namespace) -> int:
    cfg = load_config(args.config)
    registry = get_registered_sources()
    print(f"{'SOURCE':<16} {'STATUS':<10} {'LIMIT':<7} DESCRIPTION")
    print("-" * 78)
    for name in SOURCE_ORDER:
        opts = cfg.sources.get(name)
        src = registry.get(name)
        enabled = bool(opts and opts.enabled)
        status = "enabled" if enabled else "disabled"
        limit = opts.limit if opts else 0
        desc = src.description if src else ""
        print(f"{name:<16} {status:<10} {limit:<7} {desc}")
    return 0


def _cmd_history(args: argparse.Namespace) -> int:
    cfg = load_config(args.config)
    db_path = Path(cfg.output.history_db)

    if getattr(args, "path", False):
        print(db_path.resolve())
        return 0

    if not db_path.exists():
        print(f"No history database found at {db_path}. Run `jobctl run` first.")
        return 0

    store = HistoryStore(db_path)

    if getattr(args, "clear", False):
        deleted = store.clear()
        print(f"Cleared {deleted} tracked job(s) from {db_path}.")
        return 0

    older_than = getattr(args, "older_than", None)
    if older_than is not None:
        if older_than < 0:
            print("--older-than must be >= 0", file=sys.stderr)
            return 2
        deleted = store.clear_older_than(older_than)
        print(f"Removed {deleted} job(s) older than {older_than} day(s) from {db_path}.")
        return 0

    rows = store.list_recent(limit=args.limit)
    total = store.count()
    print(f"jobctl SQLite History ({db_path}) — {total} total tracked job(s)\n")
    if not rows:
        print("No jobs recorded yet.")
        return 0

    show_urls = getattr(args, "urls", False)
    for row in rows:
        seen_date = str(row["first_seen"])[:10]
        print(
            f"  [{row['score']:>3}] {row['title']} @ {row['company']} "
            f"[{row['source']}] (first seen {seen_date}, seen x{row['times_seen']})"
        )
        if show_urls and row.get("url"):
            print(f"        -> {row['url']}")
    return 0


def _cmd_notify_test(args: argparse.Namespace) -> int:
    tg = load_telegram_config_from_env(dotenv_path=args.env_file)
    ok, err = send_telegram_test_message(tg_config=tg)
    if ok:
        print("Telegram test message sent! Check your Telegram chat.")
        return 0
    print(f"Failed to send Telegram test message: {err}", file=sys.stderr)
    return 1


def _parse_selected_sources(raw_sources: str | None) -> tuple[list[str] | None, int]:
    if not raw_sources:
        return None, 0
    selected = [s.strip().lower() for s in raw_sources.split(",") if s.strip()]
    unknown = set(selected) - KNOWN_SOURCES
    if unknown:
        print(f"Unknown source(s): {', '.join(sorted(unknown))}", file=sys.stderr)
        return None, 2
    return selected, 0


def _cmd_run(args: argparse.Namespace) -> int:
    setup_logger(verbose=getattr(args, "verbose", False))
    cfg = load_config(args.config)

    if args.min_score is not None:
        cfg.scoring.min_score = args.min_score
    if args.days is not None:
        cfg.filters.max_posting_age_days = args.days
    if args.format:
        cfg.output.formats = [f.strip().lower() for f in args.format.split(",") if f.strip()]
    if args.results_dir:
        cfg.output.results_dir = args.results_dir

    selected_sources, err_code = _parse_selected_sources(args.sources)
    if err_code != 0:
        return err_code

    result = run_pipeline(
        cfg,
        selected_sources=selected_sources,
        dry_run=args.dry_run,
        include_seen=args.all,
    )

    if not args.dry_run and not getattr(args, "no_notify", False):
        tg = load_telegram_config_from_env()
        if getattr(args, "notify", False):
            tg.enabled = True
        if tg.enabled and tg.is_configured:
            date_dir = result.run_paths.date_dir if result.run_paths else None
            skipped_seen = max(0, len(result.matched_jobs) - len(result.exported_jobs))
            send_telegram_report(
                jobs=result.exported_jobs,
                config=cfg,
                tg_config=tg,
                run_date_dir=date_dir,
                skipped_seen_count=skipped_seen,
            )

    return 0


def _cmd_daemon(args: argparse.Namespace) -> int:
    setup_logger(verbose=getattr(args, "verbose", False))
    selected_sources, err_code = _parse_selected_sources(args.sources)
    if err_code != 0:
        return err_code

    try:
        schedule = load_schedule_from_env(
            time_override=args.time,
            days_override=args.schedule_days,
            tz_override=args.tz,
            run_on_startup_override=args.run_on_startup,
        )
    except ValueError as exc:
        print(f"Invalid schedule configuration: {exc}", file=sys.stderr)
        return 2

    return run_daemon(
        config_loader=lambda: load_config(args.config),
        schedule=schedule,
        selected_sources=selected_sources,
    )


def main(argv: list[str] | None = None) -> int:
    parser = build_parser()
    args_list = list(sys.argv[1:] if argv is None else argv)
    # Default to `run` when invoked with no subcommand
    if not args_list:
        args_list = ["run"]
    args = parser.parse_args(args_list)

    if args.command == "init":
        return _cmd_init(args)
    if args.command == "sources":
        return _cmd_sources(args)
    if args.command == "history":
        return _cmd_history(args)
    if args.command == "notify-test":
        return _cmd_notify_test(args)
    if args.command == "daemon":
        return _cmd_daemon(args)
    if args.command == "run":
        return _cmd_run(args)

    parser.print_help()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
