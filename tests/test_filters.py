"""Unit tests for strict 2-day posting freshness and level-aware hard filters."""

from __future__ import annotations

from datetime import datetime, timezone
import unittest

from jobctl.config import FilterConfig, ProfileConfig
from jobctl.matching.filters import is_posting_within_previous_days, passes_hard_filters
from jobctl.models import Job


def test_strict_two_day_posting_freshness(ref_now: datetime) -> None:
    assert is_posting_within_previous_days("2026-11-22T08:00:00Z", max_age_days=2, now=ref_now)[0]
    assert is_posting_within_previous_days("2026-11-21", max_age_days=2, now=ref_now)[0]
    assert is_posting_within_previous_days("2026-11-20", max_age_days=2, now=ref_now)[0]

    ok_old, reason_old = is_posting_within_previous_days("2026-11-19", max_age_days=2, now=ref_now)
    assert not ok_old
    assert "older than 2 days" in reason_old

    ok_missing, reason_missing = is_posting_within_previous_days("", max_age_days=2, require_date=True, now=ref_now)
    assert not ok_missing
    assert "missing" in reason_missing


def test_mid_level_accepts_up_to_5_years_and_rejects_6_plus(
    sample_mid_job: Job,
    mid_profile: ProfileConfig,
    strict_two_day_filters: FilterConfig,
    ref_now: datetime,
) -> None:
    passed, reason = passes_hard_filters(sample_mid_job, mid_profile, strict_two_day_filters, now=ref_now)
    assert passed, reason

    job_5yr = Job(**{**sample_mid_job.to_dict(), "description": "Requires 5+ years of experience in PostgreSQL."})
    assert passes_hard_filters(job_5yr, mid_profile, strict_two_day_filters, now=ref_now)[0]

    job_6yr = Job(**{**sample_mid_job.to_dict(), "description": "Requires 6+ years of experience in PostgreSQL."})
    passed_6, reason_6 = passes_hard_filters(job_6yr, mid_profile, strict_two_day_filters, now=ref_now)
    assert not passed_6
    assert "requires 6+ years" in reason_6


def test_mid_level_excludes_senior_and_intern_titles(
    sample_mid_job: Job,
    mid_profile: ProfileConfig,
    strict_two_day_filters: FilterConfig,
    ref_now: datetime,
) -> None:
    senior_job = Job(**{**sample_mid_job.to_dict(), "title": "Senior Backend Engineer"})
    ok_sr, reason_sr = passes_hard_filters(senior_job, mid_profile, strict_two_day_filters, now=ref_now)
    assert not ok_sr
    assert "senior" in reason_sr

    staff_job = Job(**{**sample_mid_job.to_dict(), "title": "Staff Platform Engineer"})
    ok_st, _ = passes_hard_filters(staff_job, mid_profile, strict_two_day_filters, now=ref_now)
    assert not ok_st


class TestHardFilters(unittest.TestCase):
    def test_all(self) -> None:
        now = datetime(2026, 11, 22, 10, 0, 0, tzinfo=timezone.utc)
        prof = ProfileConfig(level="mid")
        filt = FilterConfig(max_posting_age_days=2, require_posted_date=True)
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
        test_strict_two_day_posting_freshness(now)
        test_mid_level_accepts_up_to_5_years_and_rejects_6_plus(job, prof, filt, now)
        test_mid_level_excludes_senior_and_intern_titles(job, prof, filt, now)
