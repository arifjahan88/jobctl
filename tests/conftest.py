"""Shared pytest fixtures for jobctl unit tests."""

from __future__ import annotations

from datetime import datetime, timezone
import pytest

from jobctl.config import AppConfig, FilterConfig, ProfileConfig, ScoringConfig
from jobctl.models import Job


@pytest.fixture
def ref_now() -> datetime:
    return datetime(2026, 11, 22, 10, 0, 0, tzinfo=timezone.utc)


@pytest.fixture
def mid_profile() -> ProfileConfig:
    return ProfileConfig(level="mid")


@pytest.fixture
def strict_two_day_filters() -> FilterConfig:
    return FilterConfig(max_posting_age_days=2, require_posted_date=True)


@pytest.fixture
def default_scoring() -> ScoringConfig:
    return ScoringConfig()


@pytest.fixture
def sample_mid_job() -> Job:
    return Job(
        title="Backend Software Engineer II",
        company="Supabase",
        location="Remote / Worldwide",
        job_type="full-time",
        work_mode="remote",
        description=(
            "We are looking for a mid-level Backend Engineer with 2-4 years of experience "
            "building scalable services with TypeScript, Node.js, NestJS, PostgreSQL, Docker, "
            "Kubernetes, and GitHub Actions CI/CD on AWS."
        ),
        url="https://boards.greenhouse.io/supabase/jobs/12345",
        source="Greenhouse (supabase)",
        posted_date="2026-11-21T14:30:00Z",
    )


@pytest.fixture
def app_config(mid_profile: ProfileConfig, strict_two_day_filters: FilterConfig, default_scoring: ScoringConfig) -> AppConfig:
    return AppConfig(
        profile=mid_profile,
        filters=strict_two_day_filters,
        scoring=default_scoring,
    )
