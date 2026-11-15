"""
job_sources/ashby_api.py

Adapter for the Ashby Job Board API. Ashby is becoming increasingly popular
with modern AI and developer-tooling companies (Linear, OpenAI, PostHog, Sentry,
Perplexity, etc.), and like Greenhouse and Lever it has a fully public API
that requires no authentication.

API endpoint format:
  https://api.ashbyhq.com/posting-api/job-board/{company}

A nice Ashby feature: listings include a dedicated isRemote boolean and a
workplaceType field ("Remote", "Hybrid", "InPerson"), so we don't have to
guess the work mode from keywords most of the time. They also expose both
descriptionPlain and descriptionHtml, so HTML stripping is rarely needed.
"""

import html
import re
from concurrent.futures import ThreadPoolExecutor, as_completed
import requests

ASHBY_ENDPOINT_TEMPLATE = "https://api.ashbyhq.com/posting-api/job-board/{company}"

# Default company registry. You can override with ASHBY_COMPANIES in config.py.
DEFAULT_ASHBY_COMPANIES = [
    "linear", "retool", "ramp", "openai", "sentry", "posthog", "perplexity",
    "superhuman", "clerk", "dub", "resend", "cal-com", "vapi", "browserbase"
]

_HEADERS = {
    "User-Agent": "Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36"
}

_JOB_TYPE_KEYWORDS = {
    "internship": ["intern", "internship", "co-op"],
    "part-time": ["part-time", "part time", "parttime"],
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
    """Strips HTML tags and decodes entities. Fallback for when descriptionPlain is missing."""
    if not raw_html:
        return ""
    text = html.unescape(raw_html)
    text = re.sub(r"<[^>]+>", " ", text)
    return re.sub(r"\s+", " ", text).strip()


def _is_relevant_role(title: str, profile: dict) -> bool:
    """
    Quick title-level filter before we even look at the description.
    Drops senior roles for junior profiles, then checks title overlap with your target list.
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


def _infer_work_mode(workplace_type: str, is_remote: bool, location: str, title: str, description: str = "") -> str:
    """
    Ashby makes this easy — if isRemote is True or workplaceType is "Remote", we're done.
    Only falls back to keyword scanning when those fields are missing or unclear.
    Now also scans the description as a last resort.
    """
    wpt = (workplace_type or "").lower()
    if wpt == "remote" or is_remote:
        return "remote"
    if wpt == "hybrid":
        return "hybrid"
    if wpt in ("inperson", "onsite"):
        return "on-site"

    # If the structured fields didn't tell us, scan for keywords
    haystack = f"{location} {title} {description[:500]}".lower()
    if "hybrid" in haystack:
        return "hybrid"
    if "remote" in haystack or "anywhere" in haystack or "distributed" in haystack or "wfh" in haystack:
        return "remote"
    return "on-site"


def _infer_job_type(employment_type: str, title: str) -> str:
    """
    Uses the employmentType field from Ashby first, then falls back to
    keyword scanning the title if that field is absent or vague.
    """
    haystack = f"{employment_type} {title}".lower()
    for job_type, keywords in _JOB_TYPE_KEYWORDS.items():
        if any(kw in haystack for kw in keywords):
            return job_type
    return "full-time"


def _fetch_company_board(company_slug: str, profile: dict, remote_only: bool) -> list:
    """
    Fetches and normalizes all open listings from a single Ashby company board.
    Returns [] on any error to keep the concurrent fetch pool happy.
    """
    url = ASHBY_ENDPOINT_TEMPLATE.format(company=company_slug.strip().lower())
    try:
        response = requests.get(url, headers=_HEADERS, timeout=8)
        if response.status_code != 200:
            return []
        payload = response.json()
    except Exception:
        return []

    raw_jobs = payload.get("jobs", [])
    if not isinstance(raw_jobs, list):
        return []

    normalized = []
    for job in raw_jobs:
        title = job.get("title", "").strip()
        if not title or not _is_relevant_role(title, profile):
            continue

        location = job.get("location", "") or "Remote / Worldwide"
        workplace_type = job.get("workplaceType", "")
        is_remote = bool(job.get("isRemote", False))
        employment_type = job.get("employmentType", "")
        # Prefer the plain text description if available — it's already clean
        description = job.get("descriptionPlain", "") or _strip_html(job.get("descriptionHtml", ""))
        work_mode = _infer_work_mode(workplace_type, is_remote, location, title, description)

        if remote_only and work_mode != "remote":
            continue
        url_link = job.get("jobUrl", "") or job.get("applyUrl", "")
        posted_date = job.get("publishedAt", "")

        normalized.append({
            "title": title,
            "company": company_slug.capitalize(),
            "location": location,
            "job_type": _infer_job_type(employment_type, title),
            "work_mode": work_mode,
            "description": description,
            "url": url_link,
            "source": f"Ashby ({company_slug})",
            "posted_date": posted_date,
        })

    return normalized


def fetch_jobs(profile: dict, companies: list = None, max_workers: int = 15, limit: int = 50) -> list:
    """
    Queries all Ashby company boards concurrently and returns a flat list of
    matching remote junior listings (up to the limit).
    """
    target_companies = companies or DEFAULT_ASHBY_COMPANIES
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
