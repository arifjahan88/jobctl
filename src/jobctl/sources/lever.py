"""Lever Postings REST API adapter."""

from __future__ import annotations

from concurrent.futures import ThreadPoolExecutor, as_completed
from datetime import datetime, timezone
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

LEVER_ENDPOINT_TEMPLATE = "https://api.lever.co/v0/postings/{company}?mode=json"

DEFAULT_LEVER_COMPANIES: list[str] = [
    "spotify",
    "palantir",
    "atlassian",
    "postman",
    "auth0",
    "lever",
    "webflow",
    "zapier",
    "fullstory",
    "ironclad",
    "eventbrite",
    "deliveroo",
]


def format_epoch_ms(epoch_ms: int | float | None) -> str:
    """Convert Lever millisecond epoch timestamp to ISO-8601 UTC string."""
    try:
        if isinstance(epoch_ms, (int, float)) and epoch_ms > 0:
            return datetime.fromtimestamp(epoch_ms / 1000.0, timezone.utc).isoformat()
    except Exception:
        pass
    return ""


def parse_lever_payload(
    raw_jobs: list,
    company_slug: str,
    profile: ProfileConfig,
    remote_only: bool = True,
    max_posting_age_days: int = 2,
) -> list[Job]:
    """Parse a single Lever board JSON list into normalized Job models."""
    if not isinstance(raw_jobs, list):
        return []

    normalized: list[Job] = []
    for item in raw_jobs:
        if not isinstance(item, dict):
            continue
        title = (item.get("text") or "").strip()
        if not is_relevant_title(title, profile):
            continue

        posted_date = format_epoch_ms(item.get("createdAt"))
        if max_posting_age_days and max_posting_age_days > 0:
            ok, _ = is_posting_within_previous_days(
                posted_date, max_age_days=max_posting_age_days, require_date=True
            )
            if not ok:
                continue

        categories = item.get("categories") or {}
        commitment = categories.get("commitment") or ""
        location = categories.get("location") or "Remote / Worldwide"
        workplace_type = item.get("workplaceType") or ""

        desc_plain = item.get("descriptionPlain") or strip_html(item.get("description", ""))
        add_plain = item.get("additionalPlain") or strip_html(item.get("additional", ""))
        full_desc = f"{desc_plain}\n\n{add_plain}".strip()

        work_mode = infer_work_mode(
            location=location,
            title=title,
            description=full_desc,
            structured_workplace=workplace_type,
        )
        if remote_only and work_mode != "remote":
            continue

        url_link = item.get("hostedUrl") or item.get("applyUrl") or ""

        normalized.append(
            Job(
                title=title,
                company=format_company_name(company_slug),
                location=location,
                job_type=infer_job_type(title, full_desc, structured_hint=commitment),
                work_mode=work_mode,
                description=full_desc,
                url=url_link,
                source=f"Lever ({company_slug})",
                posted_date=posted_date,
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
    url = LEVER_ENDPOINT_TEMPLATE.format(company=slug)
    try:
        res = session.get(url, timeout=8)
        if res.status_code != 200:
            return []
        payload = res.json()
    except Exception:
        return []
    return parse_lever_payload(
        payload,
        company_slug=slug,
        profile=profile,
        remote_only=remote_only,
        max_posting_age_days=max_posting_age_days,
    )


@register_source("lever")
class LeverSource(JobSource):
    description = "Lever ATS Public Boards (Enterprise & Scaling Tech)"

    def fetch(
        self,
        profile: ProfileConfig,
        options: SourceOptions,
        max_posting_age_days: int = 2,
        session: requests.Session | None = None,
    ) -> list[Job]:
        http = session or build_http_session()
        companies = options.companies or DEFAULT_LEVER_COMPANIES
        remote_only = "remote" in profile.work_modes

        all_jobs: list[Job] = []
        with ThreadPoolExecutor(max_workers=10) as pool:
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
