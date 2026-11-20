"""Ashby Job Board REST API adapter."""

from __future__ import annotations

from concurrent.futures import ThreadPoolExecutor, as_completed
import requests

from jobctl.config import ProfileConfig, SourceOptions
from jobctl.matching.filters import is_posting_within_previous_days
from jobctl.models import Job
from jobctl.sources.base import JobSource, build_http_session, register_source
from jobctl.sources.common import (
    format_company_name,
    infer_job_type,
    infer_work_mode,
    is_relevant_title,
    sort_and_limit_jobs,
    strip_html,
)

ASHBY_ENDPOINT_TEMPLATE = "https://api.ashbyhq.com/posting-api/job-board/{company}"

DEFAULT_ASHBY_COMPANIES: list[str] = [
    "linear",
    "retool",
    "ramp",
    "openai",
    "sentry",
    "posthog",
    "perplexity",
    "supabase",
    "neon",
    "railway",
    "render",
    "superhuman",
    "clerk",
    "dub",
    "resend",
    "cal-com",
    "vapi",
    "browserbase",
]


def parse_ashby_payload(
    payload: dict,
    company_slug: str,
    profile: ProfileConfig,
    remote_only: bool = True,
    max_posting_age_days: int = 2,
) -> list[Job]:
    """Parse a single Ashby board JSON response into normalized Job models."""
    raw_jobs = payload.get("jobs", []) if isinstance(payload, dict) else []
    if not isinstance(raw_jobs, list):
        return []

    normalized: list[Job] = []
    for item in raw_jobs:
        if not isinstance(item, dict):
            continue
        title = (item.get("title") or "").strip()
        if not is_relevant_title(title, profile):
            continue

        posted_date = item.get("publishedAt") or ""
        if max_posting_age_days and max_posting_age_days > 0:
            ok, _ = is_posting_within_previous_days(
                posted_date, max_age_days=max_posting_age_days, require_date=True
            )
            if not ok:
                continue

        location = item.get("location") or "Remote / Worldwide"
        workplace_type = item.get("workplaceType") or ""
        is_remote = bool(item.get("isRemote", False))
        employment_type = item.get("employmentType") or ""
        description = item.get("descriptionPlain") or strip_html(item.get("descriptionHtml", ""))

        work_mode = infer_work_mode(
            location=location,
            title=title,
            description=description,
            structured_workplace=workplace_type,
            is_remote_flag=is_remote,
        )
        if remote_only and work_mode != "remote":
            continue

        url_link = item.get("jobUrl") or item.get("applyUrl") or ""

        normalized.append(
            Job(
                title=title,
                company=format_company_name(company_slug),
                location=location,
                job_type=infer_job_type(title, description, structured_hint=employment_type),
                work_mode=work_mode,
                description=description,
                url=url_link,
                source=f"Ashby ({company_slug})",
                posted_date=str(posted_date),
            )
        )

    return normalized


def _fetch_board(
    session: requests.Session,
    company_slug: str,
    profile: ProfileConfig,
    remote_only: bool,
    max_posting_age_days: int,
) -> list[Job]:
    slug = company_slug.strip().lower()
    url = ASHBY_ENDPOINT_TEMPLATE.format(company=slug)
    try:
        res = session.get(url, timeout=8)
        if res.status_code != 200:
            return []
        payload = res.json()
    except Exception:
        return []
    return parse_ashby_payload(
        payload,
        company_slug=slug,
        profile=profile,
        remote_only=remote_only,
        max_posting_age_days=max_posting_age_days,
    )


@register_source("ashby")
class AshbySource(JobSource):
    description = "Ashby ATS Public Boards (Infra, Postgres & High-Growth Tech)"

    def fetch(
        self,
        profile: ProfileConfig,
        options: SourceOptions,
        max_posting_age_days: int = 2,
        session: requests.Session | None = None,
    ) -> list[Job]:
        http = session or build_http_session()
        companies = options.companies or DEFAULT_ASHBY_COMPANIES
        remote_only = "remote" in profile.work_modes

        all_jobs: list[Job] = []
        with ThreadPoolExecutor(max_workers=12) as pool:
            futures = {
                pool.submit(
                    _fetch_board, http, slug, profile, remote_only, max_posting_age_days
                ): slug
                for slug in companies
            }
            for future in as_completed(futures):
                try:
                    all_jobs.extend(future.result())
                except Exception:
                    pass

        return sort_and_limit_jobs(
            all_jobs, limit=options.limit, max_posting_age_days=max_posting_age_days
        )
