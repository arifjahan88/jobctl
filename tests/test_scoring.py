"""Unit tests for weighted job scoring, URL deduplication, and full filter_and_score_jobs."""

from __future__ import annotations

from datetime import datetime, timezone
import unittest

from jobctl.config import FilterConfig, ProfileConfig, ScoringConfig
from jobctl.matching.scoring import deduplicate_jobs, filter_and_score_jobs, score_job
from jobctl.models import Job


def test_score_job_computes_expected_breakdown(
    sample_mid_job: Job,
    mid_profile: ProfileConfig,
    default_scoring: ScoringConfig,
) -> None:
    scored = score_job(sample_mid_job, mid_profile, default_scoring)
    assert scored.match_score >= 85
    assert "postgresql" in scored.matched_skills
    assert "docker" in scored.matched_skills
    assert "kubernetes" in scored.matched_skills
    assert scored.score_breakdown.skills_pct == 100
    assert scored.score_breakdown.job_type_pct == 100


def test_deduplicate_jobs_by_url_and_title_company(sample_mid_job: Job) -> None:
    dup_same_url = Job(
        **{
            **sample_mid_job.to_dict(),
            "title": "Backend Engineer II (Remote)",
            "url": "https://boards.greenhouse.io/supabase/jobs/12345/",
        }
    )
    dup_same_title_company = Job(
        **{
            **sample_mid_job.to_dict(),
            "url": "https://www.linkedin.com/jobs/view/99999999",
        }
    )
    unique = deduplicate_jobs([sample_mid_job, dup_same_url, dup_same_title_company])
    assert len(unique) == 1


def test_filter_and_score_jobs_pipeline(
    sample_mid_job: Job,
    mid_profile: ProfileConfig,
    strict_two_day_filters: FilterConfig,
    default_scoring: ScoringConfig,
    ref_now: datetime,
) -> None:
    stale_job = Job(
        **{
            **sample_mid_job.to_dict(),
            "title": "DevOps Engineer",
            "url": "https://boards.greenhouse.io/supabase/jobs/99999",
            "posted_date": "2026-11-10T10:00:00Z",
        }
    )
    rejections: dict[str, int] = {}
    matches = filter_and_score_jobs(
        [sample_mid_job, stale_job],
        mid_profile,
        strict_two_day_filters,
        default_scoring,
        rejection_log=rejections,
        now=ref_now,
    )
    assert len(matches) == 1
    assert matches[0].title == "Backend Software Engineer II"
    assert any("older than 2 days" in k for k in rejections)


class TestScoring(unittest.TestCase):
    def test_all(self) -> None:
        now = datetime(2026, 11, 22, 10, 0, 0, tzinfo=timezone.utc)
        prof = ProfileConfig(level="mid")
        filt = FilterConfig(max_posting_age_days=2, require_posted_date=True)
        scor = ScoringConfig()
        job = Job(
            title="Backend Software Engineer II",
            company="Supabase",
            location="Remote / Worldwide",
            job_type="full-time",
            work_mode="remote",
            description=(
                "2-4 years experience building scalable services with TypeScript, Node.js, "
                "NestJS, PostgreSQL, Docker, Kubernetes, and GitHub Actions CI/CD on AWS."
            ),
            url="https://boards.greenhouse.io/supabase/jobs/12345",
            source="Greenhouse (supabase)",
            posted_date="2026-11-21T14:30:00Z",
        )
        test_score_job_computes_expected_breakdown(job, prof, scor)
        test_deduplicate_jobs_by_url_and_title_company(job)
        test_filter_and_score_jobs_pipeline(job, prof, filt, scor, now)
