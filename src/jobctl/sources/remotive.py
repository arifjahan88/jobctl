"""Remotive Public JSON API adapter (https://remotive.com/api/remote-jobs)."""

from __future__ import annotations

import requests

from jobctl.config import ProfileConfig, SourceOptions
from jobctl.matching.filters import is_posting_within_previous_days
from jobctl.models import Job
from jobctl.sources.base import JobSource, build_http_session, register_source
from jobctl.sources.common import (
    infer_job_type,
    infer_work_mode,
    is_relevant_title,
    sort_and_limit_jobs,
    strip_html,
)

REMOTIVE_API_URL = "https://remotive.com/api/remote-jobs"
REMOTIVE_CATEGORIES: tuple[str, ...] = ("software-dev", "devops")


def parse_remotive_payload(
    payload: dict,
    profile: ProfileConfig,
    max_posting_age_days: int = 2,
) -> list[Job]:
    """Parse Remotive API JSON response into normalized Job instances."""
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

        posted_date = str(item.get("publication_date") or "").strip()
        if max_posting_age_days and max_posting_age_days > 0:
            ok, _ = is_posting_within_previous_days(
                posted_date,
                max_age_days=max_posting_age_days,
                require_date=True,
            )
            if not ok:
                continue

        company = (item.get("company_name") or "Unknown Company").strip()
        location = (item.get("candidate_required_location") or "Worldwide").strip()
        raw_job_type = str(item.get("job_type") or "").replace("_", "-")
        description = strip_html(str(item.get("description") or ""))
        url = str(item.get("url") or "").strip()

        work_mode = infer_work_mode(
            location=location,
            title=title,
            description=description,
            is_remote_flag=True,
        )

        normalized.append(
            Job(
                title=title,
                company=company,
                location=f"Remote ({location})" if "remote" not in location.lower() else location,
                job_type=infer_job_type(title, description, structured_hint=raw_job_type),
                work_mode=work_mode,
                description=description,
                url=url,
                source="Remotive",
                posted_date=posted_date,
            )
        )

    return normalized


@register_source("remotive")
class RemotiveSource(JobSource):
    description = "Remotive Official JSON API (Software Dev & DevOps Remote Jobs)"

    def fetch(
        self,
        profile: ProfileConfig,
        options: SourceOptions,
        max_posting_age_days: int = 2,
        session: requests.Session | None = None,
    ) -> list[Job]:
        http = session or build_http_session()
        all_jobs: list[Job] = []

        for category in REMOTIVE_CATEGORIES:
            try:
                res = http.get(
                    REMOTIVE_API_URL,
                    params={"category": category, "limit": max(options.limit * 2, 50)},
                    timeout=10,
                )
                if res.status_code != 200:
                    continue
                payload = res.json()
                all_jobs.extend(
                    parse_remotive_payload(
                        payload,
                        profile=profile,
                        max_posting_age_days=max_posting_age_days,
                    )
                )
            except Exception:
                continue

        return sort_and_limit_jobs(
            all_jobs,
            limit=options.limit,
            max_posting_age_days=max_posting_age_days,
        )
