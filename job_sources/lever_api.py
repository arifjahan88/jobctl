"""
job_sources/lever_api.py

Adapter for the Lever Postings API. Like Greenhouse, Lever exposes a fully
public, unauthenticated REST endpoint per company — no API key needed at all.

API endpoint format:
  https://api.lever.co/v0/postings/{company}?mode=json

A nice thing about Lever is that it provides both HTML and plain-text versions
of the description (descriptionPlain / additionalPlain), so we don't need to
do any HTML parsing in most cases.
"""

import datetime
import html
import re
from concurrent.futures import ThreadPoolExecutor, as_completed
import requests

LEVER_ENDPOINT_TEMPLATE = "https://api.lever.co/v0/postings/{company}?mode=json"

# Default company registry — all known to use Lever and post remote tech roles.
# You can override this with LEVER_COMPANIES in config.py.
DEFAULT_LEVER_COMPANIES = [
    "spotify", "palantir", "atlassian", "postman", "auth0", "lever",
    "deliveroo", "ironclad", "eventbrite", "webflow", "zapier", "fullstory"
]

_HEADERS = {
    "User-Agent": "Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36"
}

_JOB_TYPE_KEYWORDS = {
    "internship": ["intern", "internship", "co-op"],
    "part-time": ["part-time", "part time"],
    "contract": ["contract", "contractor", "freelance"],
}

_COMMON_TECH_KEYWORDS = {
    "developer", "engineer", "software", "programmer", "frontend", "front-end",
    "backend", "back-end", "fullstack", "full-stack", "full stack", "web",
    "intern", "internship", "sde", "swe", "devops", "cloud", "data", "ui", "ux"
}

_SENIOR_TITLE_TOKENS = {
    "senior", "sr", "staff", "principal", "lead", "director", "manager", "head", "vp"
}


def _strip_html(raw_html: str) -> str:
    """Strips HTML tags and decodes entities. Used as a fallback when plain text isn't available."""
    if not raw_html:
        return ""
    text = html.unescape(raw_html)
    text = re.sub(r"<[^>]+>", " ", text)
    return re.sub(r"\s+", " ", text).strip()


def _is_relevant_role(title: str, profile: dict) -> bool:
    """
    Title-level relevance check. Drops senior titles for junior profiles,
    then checks whether the title has meaningful overlap with your target titles.
    Falls back to a generic tech keyword match if the title doesn't directly overlap.
    """
    title_lower = title.lower()
    title_tokens = set(re.sub(r"[^\w\s]", " ", title_lower).split())

    if profile.get("proficiency_level") in ("Intern", "Entry-Level", "Junior"):
        if _SENIOR_TITLE_TOKENS.intersection(title_tokens):
            return False

    target_words = set()
    for t in profile.get("target_titles", []) + [profile.get("role_title", "")]:
        target_words.update(re.sub(r"[^\w\s]", " ", t.lower()).split())
    target_words.difference_update({"and", "or", "in", "at", "for", "to", "the", "a", "an", "i", "ii", "iii"})

    if any(w in title_lower for w in target_words if len(w) > 2):
        return True

    return any(k in title_lower for k in _COMMON_TECH_KEYWORDS)


def _infer_work_mode(workplace_type: str, location: str, title: str, description: str) -> str:
    """
    Lever includes a workplaceType field ("remote", "hybrid", "onsite") in newer
    postings. When that's present, we use it directly. Otherwise we fall back to
    keyword scanning across location + title + description.
    """
    wpt = (workplace_type or "").lower()
    if wpt in ("remote", "hybrid", "onsite"):
        return "on-site" if wpt == "onsite" else wpt

    haystack = f"{location} {title} {description[:500]}".lower()
    if "hybrid" in haystack:
        return "hybrid"
    if "remote" in haystack or "anywhere" in haystack or "distributed" in haystack or "wfh" in haystack or "work from home" in haystack:
        return "remote"
    return "on-site"


def _infer_job_type(commitment: str, title: str, description: str) -> str:
    """
    Lever has a 'commitment' field in categories (e.g. "Full-Time", "Internship").
    We check that first, then fall back to keyword scanning if it's missing.
    """
    haystack = f"{commitment} {title} {description[:300]}".lower()
    for job_type, keywords in _JOB_TYPE_KEYWORDS.items():
        if any(kw in haystack for kw in keywords):
            return job_type
    return "full-time"


def _format_created_at(epoch_ms) -> str:
    """
    Lever stores the posting date as a Unix timestamp in milliseconds.
    Converts to an ISO 8601 string, or returns empty string if it looks invalid.
    """
    try:
        if isinstance(epoch_ms, (int, float)) and epoch_ms > 0:
            return datetime.datetime.fromtimestamp(epoch_ms / 1000.0, datetime.timezone.utc).isoformat()
    except Exception:
        pass
    return ""


def _fetch_company_board(company_slug: str, profile: dict, remote_only: bool) -> list:
    """
    Fetches and normalizes all open listings from a single Lever company board.
    Returns [] on any error so failures don't block other concurrent fetches.
    """
    url = LEVER_ENDPOINT_TEMPLATE.format(company=company_slug.strip().lower())
    try:
        response = requests.get(url, headers=_HEADERS, timeout=8)
        if response.status_code != 200:
            return []
        raw_jobs = response.json()
        if not isinstance(raw_jobs, list):
            return []
    except Exception:
        return []

    normalized = []
    for job in raw_jobs:
        title = job.get("text", "").strip()
        if not title or not _is_relevant_role(title, profile):
            continue

        categories = job.get("categories", {}) or {}
        commitment = categories.get("commitment", "") or ""
        location = categories.get("location", "") or "Remote / Worldwide"
        workplace_type = job.get("workplaceType", "") or ""

        # Prefer plain text fields — they're cleaner and don't need HTML parsing
        desc_plain = job.get("descriptionPlain", "") or _strip_html(job.get("description", ""))
        add_plain = job.get("additionalPlain", "") or _strip_html(job.get("additional", ""))
        full_desc = f"{desc_plain}\n\n{add_plain}".strip()

        work_mode = _infer_work_mode(workplace_type, location, title, full_desc)
        if remote_only and work_mode != "remote":
            continue

        url_link = job.get("hostedUrl", "") or job.get("applyUrl", "")
        posted_date = _format_created_at(job.get("createdAt"))

        normalized.append({
            "title": title,
            "company": company_slug.capitalize(),
            "location": location,
            "job_type": _infer_job_type(commitment, title, full_desc),
            "work_mode": work_mode,
            "description": full_desc,
            "url": url_link,
            "source": f"Lever ({company_slug})",
            "posted_date": posted_date,
        })

    return normalized


def fetch_jobs(profile: dict, companies: list = None, max_workers: int = 15, limit: int = 50) -> list:
    """
    Queries all Lever company boards concurrently and returns the combined
    list of remote junior listings (up to the limit).
    """
    target_companies = companies or DEFAULT_LEVER_COMPANIES
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
