"""
job_sources/wellfound_api.py

Adapter for Wellfound (formerly AngelList Talent) — the go-to board for
remote-first tech startup jobs. Wellfound doesn't have a public API, but
their pages are server-side rendered with Next.js, so the full job data is
embedded in a __NEXT_DATA__ script tag on the jobs page. We parse that,
filter for remote-only listings, and then fetch each job's detail page
concurrently to get the full description.
"""

import html
import json
import re
from concurrent.futures import ThreadPoolExecutor
import requests

WELLFOUND_JOBS_URL = "https://wellfound.com/jobs"
WELLFOUND_DETAIL_TEMPLATE = "https://wellfound.com/jobs/{job_id}-{slug}"

_HEADERS = {
    "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36",
    "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
    "Accept-Language": "en-US,en;q=0.9",
}

_JOB_TYPE_KEYWORDS = {
    "internship": ["intern", "internship", "co-op"],
    "part-time": ["part-time", "part time"],
    "contract": ["contract", "contractor", "freelance"],
}

# General tech-role keywords we use as a fallback when the title doesn't
# match your exact target titles — helps catch roles phrased differently
_COMMON_TECH_KEYWORDS = {
    "developer", "engineer", "software", "programmer", "frontend", "front-end",
    "backend", "back-end", "fullstack", "full-stack", "full stack", "web",
    "intern", "internship", "sde", "swe", "devops", "cloud", "data", "ui"
}

_SENIOR_TITLE_TOKENS = {
    "senior", "sr", "staff", "principal", "lead", "director", "manager", "head", "vp"
}


def _strip_html(raw_html: str) -> str:
    """Strips HTML tags and entities, returns clean plain text."""
    if not raw_html:
        return ""
    text = html.unescape(raw_html)
    text = re.sub(r"<[^>]+>", " ", text)
    return re.sub(r"\s+", " ", text).strip()


def _is_relevant_role(title: str, profile: dict) -> bool:
    """
    Quick relevance check before we bother fetching the full description.
    Drops senior titles for junior profiles, then checks if the title
    has any overlap with your target titles or at least looks like a tech role.
    """
    title_lower = title.lower()
    title_tokens = set(re.sub(r"[^\w\s]", " ", title_lower).split())

    # Early bail for junior profiles — senior titles are irrelevant
    if profile.get("proficiency_level") in ("Intern", "Entry-Level", "Junior"):
        if _SENIOR_TITLE_TOKENS.intersection(title_tokens):
            return False

    # Collect all meaningful words from your target title list
    target_words = set()
    for t in profile.get("target_titles", []) + [profile.get("role_title", "")]:
        target_words.update(re.sub(r"[^\w\s]", " ", t.lower()).split())
    target_words.difference_update({"and", "or", "in", "at", "for", "to", "the", "a", "an", "i", "ii", "iii"})

    if any(w in title_lower for w in target_words if len(w) > 2):
        return True

    # Fallback: at least looks like a tech job?
    return any(k in title_lower for k in _COMMON_TECH_KEYWORDS)


def _fetch_wellfound_detail(job_info: dict) -> tuple[str, str]:
    """
    Fetches the full description and posted_date for a single Wellfound job.
    Each job page has a JSON-LD script block with @type: JobPosting.
    Returns (description, posted_date).
    """
    job_id = job_info.get("id")
    slug = job_info.get("slug")
    if not job_id or not slug:
        return "", ""

    url = WELLFOUND_DETAIL_TEMPLATE.format(job_id=job_id, slug=slug)
    try:
        res = requests.get(url, headers=_HEADERS, timeout=8)
        if res.status_code == 200:
            scripts = re.findall(r'<script type="application/ld\+json">(.*?)</script>', res.text, re.DOTALL)
            for s in scripts:
                try:
                    data = json.loads(s)
                    if data.get("@type") == "JobPosting":
                        desc = _strip_html(data.get("description", ""))
                        date_posted = data.get("datePosted", "")
                        return desc, date_posted
                except Exception:
                    pass
    except Exception:
        pass
    return "", ""


def fetch_jobs(profile: dict, limit: int = 30) -> list:
    """
    Fetches live remote startup jobs from Wellfound. The flow is:
    1. Load the /jobs page and parse the __NEXT_DATA__ Apollo state
    2. Find all JobListing objects in Apollo cache, keep only remote ones
    3. Filter by title relevance and resolve company names from __ref pointers
    4. Fetch full descriptions concurrently for the candidate batch
    5. Normalize everything into the standard jobctl job schema
    """
    try:
        res = requests.get(WELLFOUND_JOBS_URL, headers=_HEADERS, timeout=10)
        if res.status_code != 200:
            print(f"[Wellfound] Request returned status {res.status_code}")
            return []
    except Exception as exc:
        print(f"[Wellfound] Request failed: {exc}")
        return []

    # The entire job dataset is embedded in this Next.js script tag
    next_data = re.search(r'<script id="__NEXT_DATA__"[^>]*>(.*?)</script>', res.text)
    if not next_data:
        return []

    try:
        data = json.loads(next_data.group(1))
        apollo = data.get("props", {}).get("pageProps", {}).get("apolloState", {}).get("data", {})
    except Exception:
        return []

    candidate_jobs = []
    for k, v in apollo.items():
        if not (isinstance(v, dict) and v.get("title")):
            continue

        # We only care about 100% remote listings
        is_remote = bool(v.get("remote", False))
        if not is_remote:
            continue

        title = v.get("title", "").strip()
        if not _is_relevant_role(title, profile):
            continue

        # Company info is stored as a __ref pointer to a Startup object in Apollo cache
        sref = v.get("startup", {}).get("__ref")
        sobj = apollo.get(sref, {}) if sref else {}
        company = sobj.get("name", "Tech Startup")
        slug = v.get("slug", "")
        job_id = v.get("id", "")

        candidate_jobs.append({
            "id": job_id,
            "slug": slug,
            "title": title,
            "company": company,
            "compensation": v.get("compensation", ""),
            "locations": v.get("locationNames", []) or ["Remote / Worldwide"],
        })
        if len(candidate_jobs) >= limit:
            break

    if not candidate_jobs:
        return []

    # Fetch all descriptions at once rather than one by one
    with ThreadPoolExecutor(max_workers=5) as executor:
        details = list(executor.map(_fetch_wellfound_detail, candidate_jobs))

    normalized = []
    for job, (desc, date_posted) in zip(candidate_jobs, details):
        title = job["title"]
        job_id = job["id"]
        slug = job["slug"]
        url = WELLFOUND_DETAIL_TEMPLATE.format(job_id=job_id, slug=slug) if job_id and slug else "https://wellfound.com/jobs"

        # Guess the job type from the title and description opening
        haystack = f"{title} {desc[:300]}".lower()
        job_type = "full-time"
        for jt, kws in _JOB_TYPE_KEYWORDS.items():
            if any(kw in haystack for kw in kws):
                job_type = jt
                break

        comp = f" | Comp: {job['compensation']}" if job.get("compensation") else ""
        full_desc = f"{desc}\n\nLocations: {', '.join(job['locations'])}{comp}".strip()

        normalized.append({
            "title": title,
            "company": job["company"],
            "location": "Remote / Worldwide",
            "job_type": job_type,
            "work_mode": "remote",
            "description": full_desc,
            "url": url,
            "source": "Wellfound",
            "posted_date": date_posted or "",
        })

    return normalized
