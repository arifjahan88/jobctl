"""Shared HTML stripping, work-mode/job-type inference, and title relevance checks."""

from __future__ import annotations

import html
import re

from jobctl.config import ProfileConfig
from jobctl.matching.filters import is_posting_within_previous_days, parse_posted_date
from jobctl.matching.text import TITLE_STOP_WORDS, tokenize_title
from jobctl.models import Job

_INTERNSHIP_RE = re.compile(r"\b(?:intern|internship|co[\s\-]?op|trainee)\b", re.IGNORECASE)
_PART_TIME_RE = re.compile(r"\b(?:part[\s\-]?time)\b", re.IGNORECASE)
_CONTRACT_RE = re.compile(
    r"\b(?:contract|contractor|freelance|consultant|temporary|fixed[\s\-]?term)\b",
    re.IGNORECASE,
)

_HYBRID_RE = re.compile(r"\bhybrid\b", re.IGNORECASE)
_REMOTE_RE = re.compile(
    r"\b(?:remote|wfh|work\s+from\s+home|anywhere|distributed|telecommute|virtual|home[\s\-]based)\b",
    re.IGNORECASE,
)

_COMMON_TECH_TOKENS: frozenset[str] = frozenset(
    {
        "developer",
        "engineer",
        "engineering",
        "software",
        "programmer",
        "frontend",
        "backend",
        "fullstack",
        "web",
        "sde",
        "swe",
        "devops",
        "sre",
        "platform",
        "cloud",
        "infrastructure",
        "database",
        "postgresql",
        "postgres",
        "data",
        "erp",
        "systems",
    }
)

_COMPANY_DISPLAY_NAMES: dict[str, str] = {
    "gitlab": "GitLab",
    "automattic": "Automattic",
    "mongodb": "MongoDB",
    "datadog": "Datadog",
    "hashicorp": "HashiCorp",
    "cloudflare": "Cloudflare",
    "openai": "OpenAI",
    "posthog": "PostHog",
    "cal-com": "Cal.com",
    "auth0": "Auth0",
    "webflow": "Webflow",
    "fullstory": "FullStory",
    "grafanalabs": "Grafana Labs",
    "cockroachlabs": "Cockroach Labs",
    "timescale": "Timescale",
}


def format_company_name(slug_or_name: str) -> str:
    """Format an ATS company slug into a clean human-readable company name."""
    raw = (slug_or_name or "").strip()
    if not raw:
        return "Unknown Company"
    lower = raw.lower()
    if lower in _COMPANY_DISPLAY_NAMES:
        return _COMPANY_DISPLAY_NAMES[lower]
    if any(ch.isupper() for ch in raw):
        return raw
    return " ".join(part.capitalize() for part in re.split(r"[-_]+", raw) if part)


def strip_html(raw_html: str) -> str:
    """Decode HTML entities (including double-escaped ATS payloads) and strip tags."""
    if not raw_html:
        return ""
    text = html.unescape(html.unescape(raw_html))
    text = re.sub(r"<[^>]+>", " ", text)
    return re.sub(r"\s+", " ", text).strip()


def infer_job_type(title: str, description: str = "", structured_hint: str = "") -> str:
    """
    Infer employment type using strict word-boundary regexes so 'international' or
    'internal' never falsely triggers 'internship'. Checks structured hints and
    title first before inspecting the opening of the description.
    """
    primary = f"{structured_hint} {title}".strip()
    if _INTERNSHIP_RE.search(primary):
        return "internship"
    if _PART_TIME_RE.search(primary):
        return "part-time"
    if _CONTRACT_RE.search(primary):
        return "contract"

    snippet = (description or "")[:350]
    if _PART_TIME_RE.search(snippet):
        return "part-time"
    if _CONTRACT_RE.search(snippet):
        return "contract"
    if _INTERNSHIP_RE.search(snippet):
        return "internship"
    return "full-time"


def infer_work_mode(
    location: str,
    title: str,
    description: str = "",
    structured_workplace: str = "",
    is_remote_flag: bool = False,
) -> str:
    """Infer whether a role is remote, hybrid, or on-site."""
    wpt = (structured_workplace or "").strip().lower()
    if wpt == "remote" or is_remote_flag:
        return "remote"
    if wpt == "hybrid":
        return "hybrid"
    if wpt in ("onsite", "on-site", "inperson", "in_person", "in-person"):
        return "on-site"

    header_text = f"{location or ''} {title or ''}"
    desc_head = (description or "")[:700]

    if _HYBRID_RE.search(header_text) or _HYBRID_RE.search(desc_head):
        return "hybrid"
    if _REMOTE_RE.search(header_text) or _REMOTE_RE.search(desc_head):
        return "remote"
    return "on-site"


def is_relevant_title(title: str, profile: ProfileConfig) -> bool:
    """
    Fast pre-filter on job titles before downloading or scoring full descriptions.
    1. Rejects titles containing excluded tokens for the active experience level.
    2. Accepts titles overlapping with target_titles or general engineering tokens.
    """
    if not title or not title.strip():
        return False

    tokens = set(tokenize_title(title))
    if not tokens:
        return False

    if profile.preset.excluded_title_tokens.intersection(tokens):
        return False

    target_words: set[str] = set()
    for candidate in profile.target_titles + [profile.role_title]:
        target_words.update(tokenize_title(candidate))
    target_words -= TITLE_STOP_WORDS

    if tokens.intersection(target_words):
        return True

    return bool(tokens.intersection(_COMMON_TECH_TOKENS))


def sort_and_limit_jobs(
    jobs: list[Job],
    limit: int | None,
    max_posting_age_days: int = 2,
) -> list[Job]:
    """
    Filter jobs to the previous `max_posting_age_days` dates, sort newest-first
    (with deterministic tie-breaking by title and company), and slice to `limit`.
    """
    filtered: list[Job] = []
    for job in jobs:
        if max_posting_age_days and max_posting_age_days > 0:
            ok, _ = is_posting_within_previous_days(
                job.posted_date,
                max_age_days=max_posting_age_days,
                require_date=True,
            )
            if not ok:
                continue
        filtered.append(job)

    def _sort_key(item: Job) -> tuple[float, str, str]:
        dt = parse_posted_date(item.posted_date)
        ts = dt.timestamp() if dt is not None else 0.0
        return (-ts, item.company.lower(), item.title.lower())

    filtered.sort(key=_sort_key)
    return filtered[:limit] if limit else filtered
