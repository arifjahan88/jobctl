"""Hacker News 'Who is hiring?' Algolia Public JSON API adapter."""

from __future__ import annotations

import re

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

HN_STORY_SEARCH_URL = "https://hn.algolia.com/api/v1/search_by_date"
HN_COMMENTS_SEARCH_URL = "https://hn.algolia.com/api/v1/search_by_date"

_URL_RE = re.compile(r"https?://[^\s<>)\"']+", re.IGNORECASE)


def _parse_hn_header_line(first_line: str, profile: ProfileConfig) -> tuple[str, str, str]:
    """
    HN 'Who is hiring?' comments start with a pipe-delimited header:
      'Company Name | Software Engineer / DevOps | Remote (Worldwide) | Full-time | https://...'
    Returns (company, role_title, location).
    """
    parts = [p.strip() for p in first_line.split("|") if p.strip()]
    if not parts:
        return "HN Startup", "", "Remote"

    company = parts[0][:80]
    role_title = ""
    location = "Remote"

    for seg in parts[1:]:
        if _URL_RE.match(seg):
            continue
        if not role_title and is_relevant_title(seg, profile):
            role_title = seg[:100]
        elif any(
            kw in seg.lower()
            for kw in ("remote", "worldwide", "onsite", "hybrid", "utc", "global", "anywhere")
        ):
            location = seg[:80]

    if not role_title and len(parts) >= 2:
        candidate = parts[1][:100]
        if is_relevant_title(candidate, profile):
            role_title = candidate

    return company, role_title, location


def parse_hn_comments_payload(
    payload: dict,
    profile: ProfileConfig,
    remote_only: bool = True,
    max_posting_age_days: int = 2,
) -> list[Job]:
    """Parse Algolia HN comment search payload into normalized Job models."""
    hits = payload.get("hits", []) if isinstance(payload, dict) else []
    if not isinstance(hits, list):
        return []

    normalized: list[Job] = []
    for hit in hits:
        if not isinstance(hit, dict):
            continue
        raw_html = str(hit.get("comment_text") or "").strip()
        if not raw_html:
            continue

        posted_date = str(hit.get("created_at") or "").strip()
        if max_posting_age_days and max_posting_age_days > 0:
            ok, _ = is_posting_within_previous_days(
                posted_date,
                max_age_days=max_posting_age_days,
                require_date=True,
            )
            if not ok:
                continue

        # Split out the header line before stripping all tags
        first_chunk = re.split(r"<p>|<br\s*/?>|\n", raw_html, maxsplit=1)[0]
        header_line = strip_html(first_chunk)
        full_text = strip_html(raw_html)

        company, title, location = _parse_hn_header_line(header_line, profile)
        if not title:
            # Try scanning the full text opening if the first line wasn't pipe-formatted
            if not is_relevant_title(header_line, profile):
                continue
            title = header_line[:90]

        work_mode = infer_work_mode(location=location, title=title, description=full_text)
        if remote_only and work_mode != "remote":
            continue

        object_id = str(hit.get("objectID") or "").strip()
        hn_url = f"https://news.ycombinator.com/item?id={object_id}" if object_id else ""

        normalized.append(
            Job(
                title=title,
                company=company,
                location=location,
                job_type=infer_job_type(title, full_text),
                work_mode=work_mode,
                description=full_text,
                url=hn_url,
                source="HackerNews",
                posted_date=posted_date,
            )
        )

    return normalized


@register_source("hackernews")
class HackerNewsSource(JobSource):
    description = "Hacker News 'Who is Hiring?' Official Algolia JSON API"

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
            story_res = http.get(
                HN_STORY_SEARCH_URL,
                params={
                    "tags": "story,author_whoishiring",
                    "query": "Ask HN: Who is hiring?",
                    "hitsPerPage": 1,
                },
                timeout=8,
            )
            if story_res.status_code != 200:
                return []
            stories = story_res.json().get("hits", [])
            if not stories:
                return []
            story_id = stories[0].get("objectID")
            if not story_id:
                return []

            comments_res = http.get(
                HN_COMMENTS_SEARCH_URL,
                params={
                    "tags": f"comment,story_{story_id}",
                    "hitsPerPage": max(options.limit * 4, 100),
                },
                timeout=10,
            )
            if comments_res.status_code != 200:
                return []
            payload = comments_res.json()
        except Exception:
            return []

        jobs = parse_hn_comments_payload(
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
