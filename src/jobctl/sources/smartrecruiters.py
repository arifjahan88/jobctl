"""SmartRecruiters Public Posting API adapter (https://api.smartrecruiters.com/v1/companies/{company}/postings)."""

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
)

SMARTRECRUITERS_ENDPOINT_TEMPLATE = (
    "https://api.smartrecruiters.com/v1/companies/{company}/postings"
)

DEFAULT_SMARTRECRUITERS_COMPANIES: list[str] = [
    "Visa",
    "BoschGroup",
    "Equinix",
    "Devoteam",
    "Natixis",
    "Wolt",
    "Square",
    "Block",
    "Criteo",
    "Aiven",
]


def parse_smartrecruiters_payload(
    payload: dict,
    company_slug: str,
    profile: ProfileConfig,
    remote_only: bool = True,
    max_posting_age_days: int = 2,
) -> list[Job]:
    """Parse SmartRecruiters company postings JSON into normalized Job models."""
    raw_jobs = payload.get("content", []) if isinstance(payload, dict) else []
    if not isinstance(raw_jobs, list):
        return []

    normalized: list[Job] = []
    for item in raw_jobs:
        if not isinstance(item, dict):
            continue
        title = (item.get("name") or "").strip()
        if not is_relevant_title(title, profile):
            continue

        posted_date = str(item.get("releasedDate") or "").strip()
        if max_posting_age_days and max_posting_age_days > 0:
            ok, _ = is_posting_within_previous_days(
                posted_date,
                max_age_days=max_posting_age_days,
                require_date=True,
            )
            if not ok:
                continue

        loc_obj = item.get("location") if isinstance(item.get("location"), dict) else {}
        is_remote = bool(loc_obj.get("remote", False))
        city = loc_obj.get("city") or ""
        country = loc_obj.get("country") or ""
        loc_parts = [p for p in (city, country) if p]
        raw_location = ", ".join(loc_parts) if loc_parts else "Remote / Worldwide"
        if is_remote and "remote" not in raw_location.lower():
            raw_location = f"Remote ({raw_location})"

        emp_obj = item.get("typeOfEmployment") if isinstance(item.get("typeOfEmployment"), dict) else {}
        emp_label = str(emp_obj.get("label") or "")

        dept_obj = item.get("department") if isinstance(item.get("department"), dict) else {}
        dept_label = str(dept_obj.get("label") or "")
        description = f"{title} {dept_label} {raw_location}".strip()

        work_mode = infer_work_mode(
            location=raw_location,
            title=title,
            description=description,
            is_remote_flag=is_remote,
        )
        if remote_only and work_mode != "remote":
            continue

        comp_obj = item.get("company") if isinstance(item.get("company"), dict) else {}
        company_name = comp_obj.get("name") or format_company_name(company_slug)
        job_id = str(item.get("id") or "").strip()
        url_link = (
            f"https://jobs.smartrecruiters.com/{company_slug}/{job_id}"
            if job_id
            else str(item.get("ref") or "")
        )

        normalized.append(
            Job(
                title=title,
                company=company_name,
                location=raw_location,
                job_type=infer_job_type(title, description, structured_hint=emp_label),
                work_mode=work_mode,
                description=description,
                url=url_link,
                source=f"SmartRecruiters ({company_slug})",
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
    slug = company_slug.strip()
    url = SMARTRECRUITERS_ENDPOINT_TEMPLATE.format(company=slug)
    try:
        res = session.get(url, params={"limit": 100}, timeout=8)
        if res.status_code != 200:
            return []
        payload = res.json()
    except Exception:
        return []
    return parse_smartrecruiters_payload(
        payload,
        company_slug=slug,
        profile=profile,
        remote_only=remote_only,
        max_posting_age_days=max_posting_age_days,
    )


@register_source("smartrecruiters")
class SmartRecruitersSource(JobSource):
    description = "SmartRecruiters Public Posting API (Global Cloud & FinTech)"

    def fetch(
        self,
        profile: ProfileConfig,
        options: SourceOptions,
        max_posting_age_days: int = 2,
        session: requests.Session | None = None,
    ) -> list[Job]:
        http = session or build_http_session()
        companies = options.companies or DEFAULT_SMARTRECRUITERS_COMPANIES
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
