"""Workable Public Widget JSON API adapter (https://apply.workable.com/api/v1/widget/accounts/{company})."""

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

WORKABLE_WIDGET_TEMPLATE = (
    "https://apply.workable.com/api/v1/widget/accounts/{company}?details=true"
)

DEFAULT_WORKABLE_COMPANIES: list[str] = [
    "workable",
    "canonical",
    "balena",
    "netdata",
    "Percona",
    "mattermost",
    "rocketchat",
    "scrapinghub",
]


def parse_workable_payload(
    payload: dict,
    company_slug: str,
    profile: ProfileConfig,
    remote_only: bool = True,
    max_posting_age_days: int = 2,
) -> list[Job]:
    """Parse a Workable widget JSON response into normalized Job models."""
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

        posted_date = str(
            item.get("published_on") or item.get("created_at") or ""
        ).strip()
        if max_posting_age_days and max_posting_age_days > 0:
            ok, _ = is_posting_within_previous_days(
                posted_date,
                max_age_days=max_posting_age_days,
                require_date=True,
            )
            if not ok:
                continue

        is_remote = bool(item.get("telecommuting", False))
        city = item.get("city") or ""
        country = item.get("country") or ""
        loc_parts = [p for p in (city, country) if p]
        raw_location = ", ".join(loc_parts) if loc_parts else "Remote / Worldwide"
        if is_remote and "remote" not in raw_location.lower():
            raw_location = f"Remote ({raw_location})"

        description = strip_html(str(item.get("description") or ""))
        emp_type = str(item.get("employment_type") or "")

        work_mode = infer_work_mode(
            location=raw_location,
            title=title,
            description=description,
            is_remote_flag=is_remote,
        )
        if remote_only and work_mode != "remote":
            continue

        company_name = payload.get("name") or format_company_name(company_slug)
        url_link = str(item.get("url") or item.get("shortlink") or "").strip()

        normalized.append(
            Job(
                title=title,
                company=str(company_name),
                location=raw_location,
                job_type=infer_job_type(title, description, structured_hint=emp_type),
                work_mode=work_mode,
                description=description,
                url=url_link,
                source=f"Workable ({company_slug})",
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
    url = WORKABLE_WIDGET_TEMPLATE.format(company=slug)
    try:
        res = session.get(url, timeout=8)
        if res.status_code != 200:
            return []
        payload = res.json()
    except Exception:
        return []
    return parse_workable_payload(
        payload,
        company_slug=slug,
        profile=profile,
        remote_only=remote_only,
        max_posting_age_days=max_posting_age_days,
    )


@register_source("workable")
class WorkableSource(JobSource):
    description = "Workable Public Widget JSON API (Open-Source & Cloud Teams)"

    def fetch(
        self,
        profile: ProfileConfig,
        options: SourceOptions,
        max_posting_age_days: int = 2,
        session: requests.Session | None = None,
    ) -> list[Job]:
        http = session or build_http_session()
        companies = options.companies or DEFAULT_WORKABLE_COMPANIES
        remote_only = "remote" in profile.work_modes

        all_jobs: list[Job] = []
        with ThreadPoolExecutor(max_workers=8) as pool:
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
            all_jobs,
            limit=options.limit,
            max_posting_age_days=max_posting_age_days,
        )
