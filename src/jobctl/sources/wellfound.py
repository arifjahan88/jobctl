"""Wellfound (AngelList Talent) startup jobs adapter."""

from __future__ import annotations

from concurrent.futures import ThreadPoolExecutor
import json
import re
import requests

from jobctl.config import ProfileConfig, SourceOptions
from jobctl.models import Job
from jobctl.sources.base import JobSource, build_http_session, register_source
from jobctl.sources.common import infer_job_type, is_relevant_title, sort_and_limit_jobs, strip_html

WELLFOUND_JOBS_URL = "https://wellfound.com/jobs"
WELLFOUND_DETAIL_TEMPLATE = "https://wellfound.com/jobs/{job_id}-{slug}"


def _fetch_detail(session: requests.Session, job_info: dict) -> tuple[str, str]:
    job_id = job_info.get("id")
    slug = job_info.get("slug")
    if not job_id or not slug:
        return "", ""

    url = WELLFOUND_DETAIL_TEMPLATE.format(job_id=job_id, slug=slug)
    try:
        res = session.get(url, timeout=8)
        if res.status_code == 200:
            scripts = re.findall(
                r'<script type="application/ld\+json">(.*?)</script>',
                res.text,
                re.DOTALL,
            )
            for block in scripts:
                try:
                    data = json.loads(block)
                    if isinstance(data, dict) and data.get("@type") == "JobPosting":
                        desc = strip_html(data.get("description", ""))
                        date_posted = str(data.get("datePosted", ""))
                        return desc, date_posted
                except Exception:
                    pass
    except Exception:
        pass
    return "", ""


@register_source("wellfound")
class WellfoundSource(JobSource):
    description = "Wellfound Remote Tech Startups"

    def fetch(
        self,
        profile: ProfileConfig,
        options: SourceOptions,
        max_posting_age_days: int = 2,
        session: requests.Session | None = None,
    ) -> list[Job]:
        http = session or build_http_session()
        limit = options.limit or 30

        try:
            res = http.get(WELLFOUND_JOBS_URL, timeout=10)
            if res.status_code != 200:
                return []
        except Exception:
            return []

        next_data = re.search(r'<script id="__NEXT_DATA__"[^>]*>(.*?)</script>', res.text)
        if not next_data:
            return []

        try:
            data = json.loads(next_data.group(1))
            apollo = (
                data.get("props", {})
                .get("pageProps", {})
                .get("apolloState", {})
                .get("data", {})
            )
        except Exception:
            return []

        candidate_jobs: list[dict] = []
        for _, val in apollo.items():
            if not (isinstance(val, dict) and val.get("title")):
                continue
            if not bool(val.get("remote", False)):
                continue

            title = str(val.get("title", "")).strip()
            if not is_relevant_title(title, profile):
                continue

            sref = (val.get("startup") or {}).get("__ref")
            sobj = apollo.get(sref, {}) if sref else {}
            company = sobj.get("name", "Tech Startup")

            candidate_jobs.append(
                {
                    "id": val.get("id", ""),
                    "slug": val.get("slug", ""),
                    "title": title,
                    "company": company,
                    "compensation": val.get("compensation", ""),
                    "locations": val.get("locationNames") or ["Remote / Worldwide"],
                }
            )
            if len(candidate_jobs) >= limit:
                break

        if not candidate_jobs:
            return []

        with ThreadPoolExecutor(max_workers=5) as pool:
            details = list(pool.map(lambda item: _fetch_detail(http, item), candidate_jobs))

        jobs: list[Job] = []
        for item, (desc, date_posted) in zip(candidate_jobs, details):
            job_id = item["id"]
            slug = item["slug"]
            url = (
                WELLFOUND_DETAIL_TEMPLATE.format(job_id=job_id, slug=slug)
                if job_id and slug
                else WELLFOUND_JOBS_URL
            )
            comp = f" | Comp: {item['compensation']}" if item.get("compensation") else ""
            full_desc = f"{desc}\n\nLocations: {', '.join(item['locations'])}{comp}".strip()

            jobs.append(
                Job(
                    title=item["title"],
                    company=item["company"],
                    location="Remote / Worldwide",
                    job_type=infer_job_type(item["title"], full_desc),
                    work_mode="remote",
                    description=full_desc,
                    url=url,
                    source="Wellfound",
                    posted_date=date_posted,
                )
            )

        return sort_and_limit_jobs(jobs, limit=limit, max_posting_age_days=max_posting_age_days)
