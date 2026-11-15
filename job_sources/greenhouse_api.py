"""
job_sources/greenhouse_api.py

Adapter for the Greenhouse Job Board API. Greenhouse exposes a free, unauthenticated
REST endpoint for every company that uses it — no API key, no login, nothing.
We query a curated list of remote-friendly tech companies in parallel and collect
whatever matches the profile.

API endpoint format:
  https://boards-api.greenhouse.io/v1/boards/{company}/jobs?content=true

The ?content=true flag is important — without it, descriptions aren't included.
"""

import html
import re
from concurrent.futures import ThreadPoolExecutor, as_completed
import requests

GREENHOUSE_ENDPOINT_TEMPLATE = "https://boards-api.greenhouse.io/v1/boards/{company}/jobs?content=true"

# Companies we query by default when no custom list is provided in config.py.
# These are all known to post remote-friendly tech roles regularly.
DEFAULT_GREENHOUSE_COMPANIES = [
    "gitlab", "automattic", "elastic", "stripe", "figma", "datadog",
    "mongodb", "instacart", "gusto", "cloudflare", "affirm", "hashicorp",
    "coinbase", "dropbox", "discord", "brex", "carta", "plaid",
    "anduril", "benchling", "docker", "canonical", "reddit", "twitch"
]

_HEADERS = {
    "User-Agent": "Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36"
}

_JOB_TYPE_KEYWORDS = {
    "internship": ["intern", "internship", "co-op"],
    "part-time": ["part-time", "part time"],
    "contract": ["contract", "contractor", "freelance"],
}

# General tech-role keywords used as a fallback relevance check
_COMMON_TECH_KEYWORDS = {
    "developer", "engineer", "software", "programmer", "frontend", "front-end",
    "backend", "back-end", "fullstack", "full-stack", "full stack", "web",
    "intern", "internship", "sde", "swe", "devops", "cloud", "data", "ui", "ux"
}

_SENIOR_TITLE_TOKENS = {
    "senior", "sr", "staff", "principal", "lead", "director", "manager", "head", "vp"
}


def _strip_html(raw_html: str) -> str:
    """
    Greenhouse descriptions come back as double-escaped HTML (the HTML itself
    is HTML-entity-encoded), so we unescape once, then strip the tags.
    """
    if not raw_html:
        return ""
    text = html.unescape(raw_html)
    text = re.sub(r"<[^>]+>", " ", text)
    return re.sub(r"\s+", " ", text).strip()


def _is_relevant_role(title: str, profile: dict) -> bool:
    """
    Title-level relevance check — we do this before fetching details to avoid
    wasting time on roles that obviously don't fit (e.g. "Senior Data Scientist").
    Returns True if the title matches your targets or at least looks like a tech role.
    """
    title_lower = title.lower()
    title_tokens = set(re.sub(r"[^\w\s]", " ", title_lower).split())

    # Drop senior roles immediately for junior profiles
    if profile.get("proficiency_level") in ("Intern", "Entry-Level", "Junior"):
        if _SENIOR_TITLE_TOKENS.intersection(title_tokens):
            return False

    # Build a set of meaningful words from your target title list
    target_words = set()
    for t in profile.get("target_titles", []) + [profile.get("role_title", "")]:
        target_words.update(re.sub(r"[^\w\s]", " ", t.lower()).split())
    target_words.difference_update({"and", "or", "in", "at", "for", "to", "the", "a", "an", "i", "ii", "iii"})

    if any(w in title_lower for w in target_words if len(w) > 2):
        return True

    # Fallback: at least loosely looks like a tech role?
    return any(k in title_lower for k in _COMMON_TECH_KEYWORDS)


def _infer_work_mode(location: str, title: str, description: str) -> str:
    """
    Greenhouse doesn't have a dedicated work-mode field, so we infer it from
    keywords in the location string, title, and first 300 chars of description.
    """
    haystack = f"{location} {title} {description[:500]}".lower()
    if "hybrid" in haystack:
        return "hybrid"
    if "remote" in haystack or "anywhere" in haystack or "distributed" in haystack or "wfh" in haystack or "work from home" in haystack:
        return "remote"
    return "on-site"


def _infer_job_type(title: str, description: str) -> str:
    """Infers the employment type from the title and description. Defaults to full-time."""
    haystack = f"{title} {description[:400]}".lower()
    for job_type, keywords in _JOB_TYPE_KEYWORDS.items():
        if any(kw in haystack for kw in keywords):
            return job_type
    return "full-time"


def _fetch_company_board(company_slug: str, profile: dict, remote_only: bool) -> list:
    """
    Fetches all open jobs from a single company's Greenhouse board.
    Returns a list of normalized job dicts, or an empty list if anything fails.
    Network errors are silently swallowed so one unresponsive company doesn't
    block all the others running concurrently.
    """
    url = GREENHOUSE_ENDPOINT_TEMPLATE.format(company=company_slug.strip().lower())
    try:
        response = requests.get(url, headers=_HEADERS, timeout=8)
        if response.status_code != 200:
            return []
        payload = response.json()
    except Exception:
        return []

    raw_jobs = payload.get("jobs", [])
    normalized = []

    for job in raw_jobs:
        title = job.get("title", "").strip()
        if not title or not _is_relevant_role(title, profile):
            continue

        raw_location = job.get("location", {}).get("name", "") or "Remote / Worldwide"
        description = _strip_html(job.get("content", ""))
        work_mode = _infer_work_mode(raw_location, title, description)

        # Skip if not remote and we're in remote-only mode
        if remote_only and work_mode != "remote":
            continue

        company_name = job.get("company_name", "") or company_slug.capitalize()
        url_link = job.get("absolute_url", "")
        # Prefer actual creation/publication date over updated_at (which changes on minor typo edits)
        posted_date = (
            job.get("first_published")
            or job.get("first_published_at")
            or job.get("created_at")
            or job.get("updated_at", "")
        )

        normalized.append({
            "title": title,
            "company": company_name,
            "location": raw_location,
            "job_type": _infer_job_type(title, description),
            "work_mode": work_mode,
            "description": description,
            "url": url_link,
            "source": f"Greenhouse ({company_slug})",
            "posted_date": posted_date,
        })

    return normalized


def fetch_jobs(profile: dict, companies: list = None, max_workers: int = 15, limit: int = 100) -> list:
    """
    Queries all Greenhouse company boards concurrently and returns a flat list
    of matching remote junior listings. Uses a thread pool so 20+ boards can
    be checked in roughly the same time it takes to check one.
    """
    target_companies = companies or DEFAULT_GREENHOUSE_COMPANIES
    remote_only = "remote" in profile.get("work_preferences", ["remote"])

    all_jobs = []
    with ThreadPoolExecutor(max_workers=max_workers) as executor:
        futures = {executor.submit(_fetch_company_board, comp, profile, remote_only): comp for comp in target_companies}
        for future in as_completed(futures):
            try:
                jobs = future.result()
                all_jobs.extend(jobs)
            except Exception:
                pass

    return all_jobs[:limit] if limit else all_jobs
