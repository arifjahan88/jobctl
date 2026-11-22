"""WeWorkRemotely Public RSS Feeds adapter."""

from __future__ import annotations

import xml.etree.ElementTree as ET

import requests

from jobctl.config import ProfileConfig, SourceOptions
from jobctl.matching.filters import is_posting_within_previous_days, parse_posted_date
from jobctl.models import Job
from jobctl.sources.base import JobSource, build_http_session, register_source
from jobctl.sources.common import (
    infer_job_type,
    infer_work_mode,
    is_relevant_title,
    sort_and_limit_jobs,
    strip_html,
)

WWR_RSS_FEEDS: tuple[str, ...] = (
    "https://weworkremotely.com/categories/remote-back-end-programming-jobs.rss",
    "https://weworkremotely.com/categories/remote-full-stack-programming-jobs.rss",
    "https://weworkremotely.com/categories/remote-devops-sysadmin-jobs.rss",
)


def _split_company_and_title(raw_title: str) -> tuple[str, str]:
    """WeWorkRemotely RSS <title> is formatted as 'Company Name: Job Title'."""
    if ":" in raw_title:
        company_part, title_part = raw_title.split(":", 1)
        company = company_part.strip()
        title = title_part.strip()
        if company and title:
            return company, title
    return "WeWorkRemotely Employer", raw_title.strip()


def parse_wwr_rss(
    xml_text: str,
    profile: ProfileConfig,
    max_posting_age_days: int = 2,
) -> list[Job]:
    """Parse WeWorkRemotely RSS XML into normalized Job models."""
    if not xml_text or not xml_text.strip():
        return []

    try:
        root = ET.fromstring(xml_text)
    except ET.ParseError:
        return []

    normalized: list[Job] = []
    for item in root.findall(".//item"):
        raw_title = (item.findtext("title") or "").strip()
        if not raw_title:
            continue

        company, title = _split_company_and_title(raw_title)
        if not is_relevant_title(title, profile):
            continue

        pub_date_raw = (item.findtext("pubDate") or "").strip()
        if max_posting_age_days and max_posting_age_days > 0:
            ok, _ = is_posting_within_previous_days(
                pub_date_raw,
                max_age_days=max_posting_age_days,
                require_date=True,
            )
            if not ok:
                continue

        parsed_dt = parse_posted_date(pub_date_raw)
        iso_date = parsed_dt.isoformat() if parsed_dt is not None else pub_date_raw

        region = (
            item.findtext("{https://weworkremotely.com}region")
            or item.findtext("region")
            or "Worldwide"
        ).strip()
        raw_type = (
            item.findtext("{https://weworkremotely.com}type")
            or item.findtext("type")
            or ""
        ).strip()
        link = (item.findtext("link") or item.findtext("guid") or "").strip()
        description = strip_html(item.findtext("description") or "")

        work_mode = infer_work_mode(
            location=region,
            title=title,
            description=description,
            is_remote_flag=True,
        )

        normalized.append(
            Job(
                title=title,
                company=company,
                location=f"Remote ({region})",
                job_type=infer_job_type(title, description, structured_hint=raw_type),
                work_mode=work_mode,
                description=description,
                url=link,
                source="WeWorkRemotely",
                posted_date=iso_date,
            )
        )

    return normalized


@register_source("weworkremotely")
class WeWorkRemotelySource(JobSource):
    description = "WeWorkRemotely Official RSS Feeds (Back-End, Full-Stack & DevOps)"

    def fetch(
        self,
        profile: ProfileConfig,
        options: SourceOptions,
        max_posting_age_days: int = 2,
        session: requests.Session | None = None,
    ) -> list[Job]:
        http = session or build_http_session()
        all_jobs: list[Job] = []

        for feed_url in WWR_RSS_FEEDS:
            try:
                res = http.get(feed_url, timeout=10)
                if res.status_code != 200:
                    continue
                all_jobs.extend(
                    parse_wwr_rss(
                        res.text,
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
