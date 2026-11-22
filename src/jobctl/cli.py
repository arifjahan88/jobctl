"""Command-line interface (`jobctl`) with run, sources, history, and init subcommands."""

from __future__ import annotations

import argparse
from pathlib import Path
import shutil
import sys

from jobctl import __version__
from jobctl.config import KNOWN_SOURCES, load_config
from jobctl.log import setup_logger
from jobctl.pipeline import SOURCE_ORDER, run_pipeline
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
        help="Comma-separated list of sources to query (e.g. greenhouse,ashby,linkedin)",
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
        "--dry-run",
        action="store_true",
        help="Run fetch and scoring without writing files or updating SQLite history",
    )
    run_p.add_argument("-v", "--verbose", action="store_true", help="Enable verbose debug logging")

    # jobctl sources
    src_p = subparsers.add_parser("sources", help="List available job portal adapters and their status")
    src_p.add_argument("-c", "--config", type=str, default=None, help="Path to jobctl.toml")

    # jobctl history
    hist_p = subparsers.add_parser("history", help="Inspect recently matched jobs stored in SQLite")
    hist_p.add_argument("-c", "--config", type=str, default=None, help="Path to jobctl.toml")
    hist_p.add_argument("-n", "--limit", type=int, default=20, help="Number of recent jobs to display")

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
    print(f"{'SOURCE':<12} {'STATUS':<10} {'LIMIT':<7} DESCRIPTION")
    print("-" * 72)
    for name in SOURCE_ORDER:
        opts = cfg.sources.get(name)
        src = registry.get(name)
        enabled = bool(opts and opts.enabled)
        status = "enabled" if enabled else "disabled"
        limit = opts.limit if opts else 0
        desc = src.description if src else ""
        print(f"{name:<12} {status:<10} {limit:<7} {desc}")
    return 0


def _cmd_history(args: argparse.Namespace) -> int:
    cfg = load_config(args.config)
    db_path = Path(cfg.output.history_db)
    if not db_path.exists():
        print(f"No history database found at {db_path}. Run `jobctl run` first.")
        return 0

    store = HistoryStore(db_path)
    rows = store.list_recent(limit=args.limit)
    total = store.count()
    print(f"jobctl SQLite History ({db_path}) — {total} total tracked job(s)\n")
    if not rows:
        print("No jobs recorded yet.")
        return 0

    for row in rows:
        seen_date = str(row["first_seen"])[:10]
        print(
            f"  [{row['score']:>3}] {row['title']} @ {row['company']} "
            f"[{row['source']}] (first seen {seen_date}, seen x{row['times_seen']})"
        )
    return 0


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

    selected_sources: list[str] | None = None
    if args.sources:
        selected_sources = [s.strip().lower() for s in args.sources.split(",") if s.strip()]
        unknown = set(selected_sources) - KNOWN_SOURCES
        if unknown:
            print(f"Unknown source(s): {', '.join(sorted(unknown))}", file=sys.stderr)
            return 2

    run_pipeline(
        cfg,
        selected_sources=selected_sources,
        dry_run=args.dry_run,
        include_seen=args.all,
    )
    return 0


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
    if args.command == "run":
        return _cmd_run(args)

    parser.print_help()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
