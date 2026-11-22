"""Concurrent fetch → deduplicate → filter → score → history → dated export pipeline."""

from __future__ import annotations

from concurrent.futures import ThreadPoolExecutor, as_completed
from dataclasses import dataclass, field
from datetime import datetime
import logging
from pathlib import Path
import time

from jobctl.config import AppConfig
from jobctl.exporters import (
    RunPaths,
    prepare_run_paths,
    write_jobs_to_csv,
    write_jobs_to_docx,
    write_jobs_to_json,
    write_jobs_to_markdown,
)
from jobctl.log import attach_file_handler
from jobctl.matching import deduplicate_jobs, filter_and_score_jobs
from jobctl.models import Job, ScoredJob, SourceStat
from jobctl.sources import get_registered_sources
from jobctl.storage import HistoryStore

# Deterministic source execution order
SOURCE_ORDER: tuple[str, ...] = (
    "linkedin",
    "wellfound",
    "ashby",
    "greenhouse",
    "lever",
    "remotive",
    "remoteok",
    "weworkremotely",
    "hackernews",
    "smartrecruiters",
    "recruitee",
    "workable",
    "bdjobs",
    "adzuna",
)


@dataclass(slots=True)
class PipelineResult:
    raw_jobs: list[Job] = field(default_factory=list)
    unique_jobs: list[Job] = field(default_factory=list)
    matched_jobs: list[ScoredJob] = field(default_factory=list)
    exported_jobs: list[ScoredJob] = field(default_factory=list)
    near_misses: list[ScoredJob] = field(default_factory=list)
    rejection_log: dict[str, int] = field(default_factory=dict)
    source_stats: list[SourceStat] = field(default_factory=list)
    written_files: list[Path] = field(default_factory=list)
    run_paths: RunPaths | None = None


def fetch_all_sources(
    config: AppConfig,
    selected_sources: list[str] | None = None,
) -> tuple[list[Job], list[SourceStat]]:
    """Query all enabled sources concurrently and return combined raw jobs + per-source telemetry."""
    registry = get_registered_sources()
    active_names: list[str] = []

    for name in SOURCE_ORDER:
        if selected_sources and name not in selected_sources:
            continue
        opts = config.sources.get(name)
        if not opts or not opts.enabled:
            continue
        if name == "adzuna" and not (opts.app_id and opts.app_key):
            continue
        if name in registry:
            active_names.append(name)

    results_by_name: dict[str, list[Job]] = {}
    stats_by_name: dict[str, SourceStat] = {}

    def _run_one(src_name: str) -> tuple[str, list[Job], SourceStat]:
        source = registry[src_name]
        opts = config.sources[src_name]
        t0 = time.perf_counter()
        try:
            jobs = source.fetch(
                config.profile,
                opts,
                max_posting_age_days=config.filters.max_posting_age_days,
            )
            elapsed_ms = round((time.perf_counter() - t0) * 1000)
            return src_name, jobs, SourceStat(name=src_name, retrieved=len(jobs), duration_ms=elapsed_ms)
        except Exception as exc:
            elapsed_ms = round((time.perf_counter() - t0) * 1000)
            return (
                src_name,
                [],
                SourceStat(name=src_name, retrieved=0, duration_ms=elapsed_ms, error=str(exc)),
            )

    if active_names:
        with ThreadPoolExecutor(max_workers=len(active_names)) as pool:
            futures = {pool.submit(_run_one, name): name for name in active_names}
            for future in as_completed(futures):
                src_name, jobs, stat = future.result()
                results_by_name[src_name] = jobs
                stats_by_name[src_name] = stat

    all_jobs: list[Job] = []
    ordered_stats: list[SourceStat] = []
    for name in active_names:
        all_jobs.extend(results_by_name.get(name, []))
        ordered_stats.append(stats_by_name[name])

    return all_jobs, ordered_stats


def run_pipeline(
    config: AppConfig,
    selected_sources: list[str] | None = None,
    dry_run: bool = False,
    include_seen: bool = False,
    now: datetime | None = None,
) -> PipelineResult:
    """Execute the complete jobctl pipeline and export files to `search_results/<YYYY-MM-DD>/`."""
    logger = logging.getLogger("jobctl")
    current = now or datetime.now()

    run_paths: RunPaths | None = None
    file_handler: logging.FileHandler | None = None
    if not dry_run:
        run_paths = prepare_run_paths(config.output.results_dir, now=current)
        file_handler = attach_file_handler(run_paths.log_file)

    try:
        modes_str = ", ".join(m.title() for m in config.profile.work_modes)
        logger.info(
            f"=== jobctl v2.0.0 — Searching for '{config.profile.role_title}' "
            f"[{config.profile.preset.label}, {modes_str}, {config.profile.location}, "
            f"Last {config.filters.max_posting_age_days} Days] ===\n"
        )

        raw_jobs, source_stats = fetch_all_sources(config, selected_sources=selected_sources)
        for stat in source_stats:
            if stat.error:
                logger.info(
                    f"  [!] {stat.name:<12} -> error ({stat.error}) [{stat.duration_ms} ms]"
                )
            else:
                logger.info(
                    f"  [+] {stat.name:<12} -> {stat.retrieved:>3} listing(s) retrieved "
                    f"[{stat.duration_ms} ms]"
                )

        unique_jobs = deduplicate_jobs(raw_jobs)
        logger.info(f"\nTotal raw listings (last {config.filters.max_posting_age_days} days): {len(raw_jobs)}")
        logger.info(f"Unique listings after dedup:       {len(unique_jobs)}")

        rejection_log: dict[str, int] = {}
        near_misses: list[ScoredJob] = []
        matched_jobs = filter_and_score_jobs(
            unique_jobs,
            config.profile,
            config.filters,
            config.scoring,
            rejection_log=rejection_log,
            near_misses=near_misses,
        )

        exported_jobs = list(matched_jobs)
        if not dry_run and config.output.history_db:
            store = HistoryStore(config.output.history_db)
            store.record_jobs(matched_jobs, now=current)
            if config.output.only_new and not include_seen:
                exported_jobs = [j for j in matched_jobs if j.is_new]

        logger.info(f"Matches passing filters/score:     {len(matched_jobs)}")
        if not dry_run and config.output.only_new and not include_seen:
            logger.info(f"New matches to export this run:    {len(exported_jobs)}\n")
        else:
            logger.info("")

        for job in exported_jobs:
            tag = "NEW" if job.is_new else f"SEENx{job.times_seen}"
            date_tag = job.posted_date[:10] if job.posted_date else "N/A"
            logger.info(
                f"  [{job.match_score:>3}] ({tag}) {job.title} @ {job.company} "
                f"[{job.source}] ({date_tag} · {job.work_mode}, {job.job_type})"
            )

        if len(matched_jobs) < len(unique_jobs) and rejection_log:
            logger.info("\nWhy the rest were excluded:")
            for reason, count in sorted(rejection_log.items(), key=lambda x: -x[1]):
                logger.info(f"  {count:>3}  {reason}")

        if near_misses:
            near_misses.sort(key=lambda j: j.match_score, reverse=True)
            logger.info(
                f"\nClosest near-misses (passed hard filters, scored below {config.scoring.min_score}):"
            )
            for job in near_misses[:5]:
                b = job.score_breakdown
                logger.info(
                    f"  [{job.match_score:>3}] {job.title} @ {job.company} [{job.source}] "
                    f"— skills {b.skills_pct}%, title {b.title_pct}%, job_type {b.job_type_pct}%"
                )

        written_files: list[Path] = []
        if not dry_run and run_paths is not None:
            for fmt in config.output.formats:
                fmt_key = fmt.strip().lower()
                if fmt_key == "docx":
                    written_files.append(
                        write_jobs_to_docx(exported_jobs, run_paths.file_for("docx"), now=current)
                    )
                elif fmt_key == "csv":
                    written_files.append(
                        write_jobs_to_csv(exported_jobs, run_paths.file_for("csv"))
                    )
                elif fmt_key in ("json",):
                    written_files.append(
                        write_jobs_to_json(exported_jobs, run_paths.file_for("json"), now=current)
                    )
                elif fmt_key in ("md", "markdown"):
                    skipped_seen = max(0, len(matched_jobs) - len(exported_jobs))
                    written_files.append(
                        write_jobs_to_markdown(
                            exported_jobs,
                            run_paths.file_for("md"),
                            now=current,
                            skipped_seen_count=skipped_seen,
                        )
                    )
            written_files.append(run_paths.log_file.resolve())

            logger.info(f"\nResults saved inside dated folder: {run_paths.date_dir.resolve()}")
            for path in written_files:
                logger.info(f"  -> {path.name}")

        return PipelineResult(
            raw_jobs=raw_jobs,
            unique_jobs=unique_jobs,
            matched_jobs=matched_jobs,
            exported_jobs=exported_jobs,
            near_misses=near_misses,
            rejection_log=rejection_log,
            source_stats=source_stats,
            written_files=written_files,
            run_paths=run_paths,
        )
    finally:
        if file_handler is not None:
            logger.removeHandler(file_handler)
            file_handler.close()
