"""BDJobs Public JSON Search API adapter (https://api.bdjobs.com/Jobs/api/JobSearch/GetJobSearch)."""

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

BDJOBS_API_URL = "https://api.bdjobs.com/Jobs/api/JobSearch/GetJobSearch"
BDJOBS_DETAIL_URL_TEMPLATE = "https://jobs.bdjobs.com/jobdetails.asp?id={job_id}"


def parse_bdjobs_payload(
    payload: dict,
    profile: ProfileConfig,
    remote_only: bool = True,
    max_posting_age_days: int = 2,
) -> list[Job]:
    """Parse BDJobs JSON search response (`data` / `common` array) into normalized Job models."""
    if not isinstance(payload, dict):
        return []

    raw_jobs = payload.get("data") or payload.get("jobs") or []
    if not isinstance(raw_jobs, list):
        return []

    normalized: list[Job] = []
    for item in raw_jobs:
        if not isinstance(item, dict):
            continue
        title = str(item.get("jobTitle") or item.get("title") or "").strip()
        if not is_relevant_title(title, profile):
            continue

        posted_date = str(
            item.get("publishDate") or item.get("posted_date") or item.get("postedOn") or ""
        ).strip()
        if max_posting_age_days and max_posting_age_days > 0:
            ok, _ = is_posting_within_previous_days(
                posted_date,
                max_age_days=max_posting_age_days,
                require_date=True,
            )
            if not ok:
                continue

        company = str(item.get("compName") or item.get("company") or "BDJobs Employer").strip()
        location = str(item.get("location") or "Bangladesh").strip()
        context = strip_html(
            f"{item.get('jobContext') or ''} {item.get('experience') or ''} "
            f"{item.get('eduRec') or ''} {item.get('description') or ''}"
        )

        work_mode = infer_work_mode(
            location=location,
            title=title,
            description=context,
        )
        if remote_only and work_mode != "remote":
            continue

        job_id = str(item.get("jobId") or item.get("id") or "").strip()
        url = str(item.get("url") or "").strip()
        if not url and job_id:
            url = BDJOBS_DETAIL_URL_TEMPLATE.format(job_id=job_id)

        normalized.append(
            Job(
                title=title,
                company=company,
                location=location,
                job_type=infer_job_type(title, context),
                work_mode=work_mode,
                description=context,
                url=url,
                source="BDJobs",
                posted_date=posted_date,
            )
        )

    return normalized


@register_source("bdjobs")
class BDJobsSource(JobSource):
    description = "BDJobs Public Web Search JSON API (Bangladesh IT & Engineering)"

    def fetch(
        self,
        profile: ProfileConfig,
        options: SourceOptions,
        max_posting_age_days: int = 2,
        session: requests.Session | None = None,
    ) -> list[Job]:
        http = session or build_http_session()
        remote_only = "remote" in profile.work_modes

        try:
            res = http.get(
                BDJOBS_API_URL,
                params={
                    "keyword": profile.role_title,
                    "qOT": "1",
                    "rpp": max(options.limit, 50),
                    "pg": 1,
                },
                timeout=10,
            )
            if res.status_code != 200:
                return []
            payload = res.json()
        except Exception:
            return []

        jobs = parse_bdjobs_payload(
            payload,
            profile=profile,
            remote_only=remote_only,
            max_posting_age_days=max_posting_age_days,
        )
        return sort_and_limit_jobs(
            jobs,
            limit=options.limit,
            max_posting_age_days=max_posting_age_days,
        )
