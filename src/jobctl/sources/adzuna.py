"""Adzuna Job Search API adapter (credentials loaded from environment or config)."""

from __future__ import annotations

import os
import re
import requests

from jobctl.config import ProfileConfig, SourceOptions
from jobctl.models import Job
from jobctl.sources.base import JobSource, build_http_session, register_source
from jobctl.sources.common import infer_job_type, infer_work_mode, is_relevant_title, sort_and_limit_jobs

ADZUNA_ENDPOINT_TEMPLATE = "https://api.adzuna.com/v1/api/jobs/{country}/search/1"


@register_source("adzuna")
class AdzunaSource(JobSource):
    description = "Adzuna Job Aggregator API (Optional)"

    def fetch(
        self,
        profile: ProfileConfig,
        options: SourceOptions,
        max_posting_age_days: int = 2,
        session: requests.Session | None = None,
    ) -> list[Job]:
        app_id = options.app_id or os.environ.get("ADZUNA_APP_ID", "")
        app_key = options.app_key or os.environ.get("ADZUNA_APP_KEY", "")
        if not app_id or not app_key:
            return []

        http = session or build_http_session()
        country = (options.country_code or "us").strip().lower()
        endpoint = ADZUNA_ENDPOINT_TEMPLATE.format(country=country)

        params: dict[str, str | int] = {
            "app_id": app_id,
            "app_key": app_key,
            "results_per_page": options.limit or 30,
            "what": profile.role_title,
            "content-type": "application/json",
        }
        if max_posting_age_days and max_posting_age_days > 0:
            params["max_days_old"] = max_posting_age_days

        loc = profile.location.strip().lower()
        if loc and loc not in ("worldwide", "remote", "anywhere"):
            params["where"] = profile.location

        try:
            res = http.get(endpoint, params=params, timeout=12)
            if res.status_code != 200:
                return []
            payload = res.json()
        except Exception:
            return []

        raw_jobs = payload.get("results", []) if isinstance(payload, dict) else []
        jobs: list[Job] = []
        for item in raw_jobs:
            if not isinstance(item, dict):
                continue
            title = re.sub(r"\s+", " ", str(item.get("title", ""))).strip()
            if not is_relevant_title(title, profile):
                continue

            description = re.sub(r"\s+", " ", str(item.get("description", ""))).strip()
            company = (item.get("company") or {}).get("display_name", "Unknown Company")
            location_name = (item.get("location") or {}).get("display_name", "Unspecified")
            work_mode = infer_work_mode(location_name, title, description)

            jobs.append(
                Job(
                    title=title,
                    company=company,
                    location=location_name,
                    job_type=infer_job_type(title, description),
                    work_mode=work_mode,
                    description=description,
                    url=str(item.get("redirect_url", "")),
                    source="Adzuna",
                    posted_date=str(item.get("created", "")),
                )
            )

        return sort_and_limit_jobs(
            jobs, limit=options.limit, max_posting_age_days=max_posting_age_days
        )
