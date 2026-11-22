"""RemoteOK Public JSON API adapter (https://remoteok.com/api)."""

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

REMOTEOK_API_URL = "https://remoteok.com/api"


def parse_remoteok_payload(
    payload: list,
    profile: ProfileConfig,
    max_posting_age_days: int = 2,
) -> list[Job]:
    """Parse RemoteOK JSON list (skipping index 0 legal metadata element) into Job models."""
    if not isinstance(payload, list):
        return []

    normalized: list[Job] = []
    for item in payload:
        if not isinstance(item, dict):
            continue
        # First element in RemoteOK API response is a legal/terms dictionary without a position
        title = (item.get("position") or item.get("title") or "").strip()
        if not title or not is_relevant_title(title, profile):
            continue

        posted_date = str(item.get("date") or "").strip()
        if max_posting_age_days and max_posting_age_days > 0:
            ok, _ = is_posting_within_previous_days(
                posted_date,
                max_age_days=max_posting_age_days,
                require_date=True,
            )
            if not ok:
                continue

        company = (item.get("company") or "Unknown Company").strip()
        location = (item.get("location") or "Remote / Worldwide").strip() or "Remote / Worldwide"
        tags = item.get("tags") if isinstance(item.get("tags"), list) else []
        tags_text = " ".join(str(t) for t in tags if t)
        raw_desc = strip_html(str(item.get("description") or ""))
        description = f"{raw_desc} {tags_text}".strip()
        url = str(item.get("url") or item.get("apply_url") or "").strip()

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
                location=location if "remote" in location.lower() else f"Remote ({location})",
                job_type=infer_job_type(title, description),
                work_mode=work_mode,
                description=description,
                url=url,
                source="RemoteOK",
                posted_date=posted_date,
            )
        )

    return normalized


@register_source("remoteok")
class RemoteOKSource(JobSource):
    description = "RemoteOK Official Public JSON Feed (Worldwide Remote Tech)"

    def fetch(
        self,
        profile: ProfileConfig,
        options: SourceOptions,
        max_posting_age_days: int = 2,
        session: requests.Session | None = None,
    ) -> list[Job]:
        http = session or build_http_session()
        try:
            res = http.get(
                REMOTEOK_API_URL,
                headers={"Accept": "application/json"},
                timeout=10,
            )
            if res.status_code != 200:
                return []
            payload = res.json()
        except Exception:
            return []

        jobs = parse_remoteok_payload(
            payload,
            profile=profile,
            max_posting_age_days=max_posting_age_days,
        )
        return sort_and_limit_jobs(
            jobs,
            limit=options.limit,
            max_posting_age_days=max_posting_age_days,
        )
