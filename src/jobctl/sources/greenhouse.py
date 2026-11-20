"""Greenhouse Job Board REST API adapter."""

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

GREENHOUSE_ENDPOINT_TEMPLATE = "https://boards-api.greenhouse.io/v1/boards/{company}/jobs?content=true"

# Curated remote-friendly engineering, infrastructure, cloud, and database companies on Greenhouse
DEFAULT_GREENHOUSE_COMPANIES: list[str] = [
    "gitlab",
    "automattic",
    "elastic",
    "stripe",
    "figma",
    "datadog",
    "mongodb",
    "cloudflare",
    "hashicorp",
    "cockroachlabs",
    "grafanalabs",
    "timescale",
    "vercel",
    "planetscale",
    "temporal",
    "tailscale",
    "coinbase",
    "dropbox",
    "discord",
    "brex",
    "carta",
    "plaid",
    "docker",
    "canonical",
    "affirm",
    "gusto",
    "instacart",
    "reddit",
]


def parse_greenhouse_payload(
    payload: dict,
    company_slug: str,
    profile: ProfileConfig,
    remote_only: bool = True,
    max_posting_age_days: int = 2,
) -> list[Job]:
    """Parse a single Greenhouse company board JSON payload into normalized Job models."""
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

        posted_date = (
            item.get("first_published")
            or item.get("first_published_at")
            or item.get("created_at")
            or item.get("updated_at")
            or ""
        )
        if max_posting_age_days and max_posting_age_days > 0:
            ok, _ = is_posting_within_previous_days(
                posted_date, max_age_days=max_posting_age_days, require_date=True
            )
            if not ok:
                continue

        raw_location = (item.get("location") or {}).get("name") or "Remote / Worldwide"
        description = strip_html(item.get("content", ""))
        work_mode = infer_work_mode(raw_location, title, description)
        if remote_only and work_mode != "remote":
            continue

        company_name = item.get("company_name") or format_company_name(company_slug)
        url_link = item.get("absolute_url", "")

        normalized.append(
            Job(
                title=title,
                company=company_name,
                location=raw_location,
                job_type=infer_job_type(title, description),
                work_mode=work_mode,
                description=description,
                url=url_link,
                source=f"Greenhouse ({company_slug})",
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
    url = GREENHOUSE_ENDPOINT_TEMPLATE.format(company=slug)
    try:
        res = session.get(url, timeout=8)
        if res.status_code != 200:
            return []
        payload = res.json()
    except Exception:
        return []
    return parse_greenhouse_payload(
        payload,
        company_slug=slug,
        profile=profile,
        remote_only=remote_only,
        max_posting_age_days=max_posting_age_days,
    )


@register_source("greenhouse")
class GreenhouseSource(JobSource):
    description = "Greenhouse ATS Public Boards (Cloud, DevOps & Global Tech)"

    def fetch(
        self,
        profile: ProfileConfig,
        options: SourceOptions,
        max_posting_age_days: int = 2,
        session: requests.Session | None = None,
    ) -> list[Job]:
        http = session or build_http_session()
        companies = options.companies or DEFAULT_GREENHOUSE_COMPANIES
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
