"""Unit tests for SQLite job history persistence and dated search_results/<YYYY-MM-DD>/ exporters."""

from __future__ import annotations

from datetime import datetime, timezone
from pathlib import Path
import tempfile
import unittest

from jobctl.exporters import (
    prepare_run_paths,
    write_jobs_to_csv,
    write_jobs_to_docx,
    write_jobs_to_json,
    write_jobs_to_markdown,
)
from jobctl.models import Job, ScoreBreakdown, ScoredJob
from jobctl.storage import HistoryStore


def _make_scored(job: Job, score: int = 88) -> ScoredJob:
    return ScoredJob(
        job=job,
        match_score=score,
        match_summary="Matches 6/21 target skills: typescript, node.js, postgresql, docker, kubernetes, aws.",
        matched_skills=["typescript", "node.js", "postgresql", "docker", "kubernetes", "aws"],
        score_breakdown=ScoreBreakdown(skills_pct=100, title_pct=80, job_type_pct=100),
    )


def test_history_store_marks_first_seen_as_new_and_second_as_seen(
    tmp_path: Path,
    sample_mid_job: Job,
) -> None:
    db_file = tmp_path / "jobctl.db"
    store = HistoryStore(db_file)

    first = _make_scored(sample_mid_job)
    store.record_jobs([first])
    assert first.is_new is True
    assert first.times_seen == 1

    second = _make_scored(sample_mid_job)
    store.record_jobs([second])
    assert second.is_new is False
    assert second.times_seen == 2
    assert store.count() == 1

    # clear_older_than should remove old rows and keep fresh rows
    old_now = datetime(2026, 11, 10, 12, 0, tzinfo=timezone.utc)
    fresh_now = datetime(2026, 11, 22, 12, 0, tzinfo=timezone.utc)
    old_job = Job(
        title="Old DevOps Engineer",
        company="LegacyCloud",
        location="Remote",
        job_type="full-time",
        work_mode="remote",
        description="Docker and Kubernetes",
        url="https://example.com/old-job",
        source="Remotive",
        posted_date="2026-11-10",
    )
    store.record_jobs([_make_scored(old_job)], now=old_now)
    assert store.count() == 2
    removed_old = store.clear_older_than(days=5, now=fresh_now)
    assert removed_old == 1
    assert store.count() == 1

    # clear() removes everything
    deleted_all = store.clear()
    assert deleted_all == 1
    assert store.count() == 0


def test_exporters_write_into_search_results_dated_folder(
    tmp_path: Path,
    sample_mid_job: Job,
) -> None:
    fixed_now = datetime(2026, 11, 22, 11, 15, 30, tzinfo=timezone.utc)
    paths = prepare_run_paths(tmp_path / "search_results", now=fixed_now)

    assert paths.date_dir.name == "2026-11-22"
    assert paths.date_dir.exists()

    scored = [_make_scored(sample_mid_job)]
    docx_file = write_jobs_to_docx(scored, paths.file_for("docx"), now=fixed_now)
    csv_file = write_jobs_to_csv(scored, paths.file_for("csv"))
    json_file = write_jobs_to_json(scored, paths.file_for("json"), now=fixed_now)
    md_file = write_jobs_to_markdown(scored, paths.file_for("md"), now=fixed_now)

    assert docx_file.exists() and docx_file.stat().st_size > 0
    assert csv_file.exists() and "Backend Software Engineer II" in csv_file.read_text(encoding="utf-8")
    assert json_file.exists() and '"generated_by": "jobctl"' in json_file.read_text(encoding="utf-8")
    assert md_file.exists() and "# jobctl — Matched Engineering Jobs" in md_file.read_text(encoding="utf-8")

    # Verify clearer message when matches were skipped due to only_new=true
    skipped_md = write_jobs_to_markdown(
        [], tmp_path / "skipped.md", now=fixed_now, skipped_seen_count=5
    )
    skipped_text = skipped_md.read_text(encoding="utf-8")
    assert "5 matching job(s) were already seen" in skipped_text
    assert "jobctl history --clear" in skipped_text


class TestHistoryAndExporters(unittest.TestCase):
    def test_all(self) -> None:
        job = Job(
            title="Backend Software Engineer II",
            company="Supabase",
            location="Remote / Worldwide",
            job_type="full-time",
            work_mode="remote",
            description="2-4 years experience with TypeScript and PostgreSQL.",
            url="https://boards.greenhouse.io/supabase/jobs/12345",
            source="Greenhouse (supabase)",
            posted_date="2026-11-21T14:30:00Z",
        )
        with tempfile.TemporaryDirectory() as td:
            tp = Path(td)
            test_history_store_marks_first_seen_as_new_and_second_as_seen(tp, job)
            test_exporters_write_into_search_results_dated_folder(tp, job)
