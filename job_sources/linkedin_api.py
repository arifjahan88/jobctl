"""
job_sources/linkedin_api.py

Pulls job listings from LinkedIn's public guest search — no login or API key
needed. We use the f_WT=2 filter to hard-restrict results to 100% remote, and
f_E=1,2 to target entry-level and internship experience bands.

Because the search endpoint only returns card snippets (titles, company names,
locations), we follow up with a concurrent batch of detail page fetches to get
the actual job descriptions. That's what the ThreadPoolExecutor below is for.
"""

import html
import re
from concurrent.futures import ThreadPoolExecutor
import requests

LINKEDIN_SEARCH_ENDPOINT = "https://www.linkedin.com/jobs-guest/jobs/api/seeMoreJobPostings/search"
LINKEDIN_JOB_DETAIL_TEMPLATE = "https://www.linkedin.com/jobs-guest/jobs/api/jobPosting/{job_id}"

_HEADERS = {
    "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36",
    "Accept-Language": "en-US,en;q=0.9",
}

_JOB_TYPE_KEYWORDS = {
    "internship": ["intern", "internship", "co-op"],
    "part-time": ["part-time", "part time"],
    "contract": ["contract", "contractor", "freelance"],
}

# Words that, if found in a job title, tell us this is too senior for a junior profile
_SENIOR_TITLE_TOKENS = {
    "senior", "sr", "staff", "principal", "lead", "director", "manager", "head", "vp"
}


def _strip_html(raw_html: str) -> str:
    """Converts raw HTML to plain text — handles HTML entities and tag removal."""
    if not raw_html:
        return ""
    text = html.unescape(raw_html)
    text = re.sub(r"<[^>]+>", " ", text)
    return re.sub(r"\s+", " ", text).strip()


def _infer_work_mode(location: str, title: str, description: str) -> str:
    """
    Figures out the work arrangement from keywords in the location, title,
    and description.
    Checks location and description for hybrid or remote cues, preventing
    false on-site classifications when city locations represent remote-eligible roles.
    """
    loc_lower = (location or "").lower()
    title_lower = (title or "").lower()
    desc_lower = (description or "").lower()

    # Check for hybrid first
    if "hybrid" in loc_lower or "hybrid" in title_lower:
        return "hybrid"
    if re.search(r"\bhybrid\b", desc_lower[:600]):
        return "hybrid"

    # Explicit remote in location or title
    remote_keywords = (
        "remote", "wfh", "work from home", "anywhere", "distributed",
        "telecommute", "virtual", "home-based"
    )
    if any(k in loc_lower for k in remote_keywords) or any(k in title_lower for k in remote_keywords):
        return "remote"

    # Check description for clear remote signals
    if re.search(
        r"\b(?:100%\s+remote|fully\s+remote|work\s+from\s+home|remote\s+(?:first|opportunity|position|role|option|friendly)|open\s+to\s+remote|remote\s*[-/]\s*eligible)\b",
        desc_lower
    ):
        return "remote"

    # Also check first 800 chars of description for general remote keywords
    if any(k in desc_lower[:800] for k in ("remote", "work from home", "wfh", "distributed team")):
        return "remote"

    return "on-site"


def _infer_job_type(title: str, description: str) -> str:
    """
    Looks at the title and beginning of the description to figure out if this
    is an internship, part-time, or contract role. Defaults to full-time.
    """
    haystack = f"{title} {description[:400]}".lower()
    for job_type, keywords in _JOB_TYPE_KEYWORDS.items():
        if any(kw in haystack for kw in keywords):
            return job_type
    return "full-time"


def _fetch_job_description(job_id: str) -> str:
    """
    Fetches the full description for a single job by ID. LinkedIn renders the
    description inside a specific div class — we pull that out and strip the HTML.
    Returns an empty string if anything goes wrong, so failures don't block the batch.
    """
    if not job_id:
        return ""
    url = LINKEDIN_JOB_DETAIL_TEMPLATE.format(job_id=job_id)
    try:
        res = requests.get(url, headers=_HEADERS, timeout=6)
        if res.status_code == 200:
            m = re.search(r'<div class="show-more-less-html__markup[^"]*"[^>]*>(.*?)</div>', res.text, re.DOTALL)
            if m:
                return _strip_html(m.group(1))
    except Exception:
        pass
    return ""


def _search_query(query: str, location: str, remote_only: bool = True, start: int = 0) -> list:
    """
    Hits the LinkedIn guest search endpoint and returns the raw HTML card
    blocks from the response. Each card contains the title, company, location,
    and a link — we parse those out in fetch_jobs().
    """
    params = {
        "keywords": query,
        "start": start,
    }
    # LinkedIn ignores the location param for "Worldwide" — that's what we want
    if location and location.lower() not in ("worldwide", "anywhere"):
        params["location"] = location

    if remote_only:
        params["f_WT"] = "2"   # f_WT=2 means "Remote" on LinkedIn
    params["f_E"] = "1,2"      # f_E=1 is Internship, f_E=2 is Entry-Level

    try:
        res = requests.get(LINKEDIN_SEARCH_ENDPOINT, params=params, headers=_HEADERS, timeout=10)
        if res.status_code != 200:
            return []
        cards = re.findall(r"<li[^>]*>(.*?)</li>", res.text, re.DOTALL)
        return cards
    except Exception:
        return []


def fetch_jobs(profile: dict, limit: int = 30) -> list:
    """
    Main entry point. Runs targeted queries (role + skills, "Junior <role>",
    and remote-targeted variations) across multiple pages, then fetches full
    descriptions for each card concurrently, and normalizes everything into
    the standard Quaero job dict schema.
    """
    role_title = profile.get("role_title", "Full Stack Developer")
    target_skills = profile.get("target_skills", [])
    location = profile.get("location", "Worldwide")
    remote_only = "remote" in profile.get("work_preferences", ["remote"])

    # Run targeted queries with remote keywords
    top_skills = " ".join(target_skills[:3]) if target_skills else "React Node"
    search_queries = [
        f"{role_title} {top_skills}",
        f"Junior {role_title}",
        f"{role_title} remote",
        f"Junior {role_title} remote",
    ]

    seen_ids = set()
    parsed_cards = []

    for query in search_queries:
        for page_start in (0, 10, 20):
            cards = _search_query(query, location, remote_only=remote_only, start=page_start)
            if not cards:
                break
            for card in cards:
                # Extract the relevant fields from each card's HTML
                title_m = re.search(r'<h3[^>]*class="[^"]*base-search-card__title[^"]*"[^>]*>\s*([^<]+?)\s*</h3>', card)
                comp_m = re.search(r'<h4[^>]*class="[^"]*base-search-card__subtitle[^"]*"[^>]*>.*?<a[^>]*>\s*([^<]+?)\s*</a>', card, re.DOTALL)
                if not comp_m:
                    comp_m = re.search(r'<h4[^>]*class="[^"]*base-search-card__subtitle[^"]*"[^>]*>\s*([^<]+?)\s*</h4>', card)
                loc_m = re.search(r'<span[^>]*class="[^"]*job-search-card__location[^"]*"[^>]*>\s*([^<]+?)\s*</span>', card)
                link_m = re.search(r'<a[^>]*class="[^"]*base-card__full-link[^"]*"[^>]*href="([^"]+)"', card)
                time_m = re.search(r'<time[^>]*datetime="([^"]+)"', card)

                if not (title_m and link_m):
                    continue

                raw_url = link_m.group(1).split("?")[0]
                # Job IDs on LinkedIn are 8+ digit numbers embedded in the URL
                job_id_match = re.search(r"(\d{8,})", raw_url)
                job_id = job_id_match.group(1) if job_id_match else raw_url
                if job_id in seen_ids:
                    continue
                seen_ids.add(job_id)

                title = html.unescape(title_m.group(1).strip())

                # Drop senior titles early, before even fetching the description
                title_tokens = set(re.sub(r"[^\w\s]", " ", title.lower()).split())
                if _SENIOR_TITLE_TOKENS.intersection(title_tokens):
                    continue

                company = html.unescape(comp_m.group(1).strip()) if comp_m else "Unknown Company"
                job_loc = html.unescape(loc_m.group(1).strip()) if loc_m else "Remote / Worldwide"
                posted_date = time_m.group(1) if time_m else ""

                parsed_cards.append({
                    "title": title,
                    "company": company,
                    "location": job_loc,
                    "url": raw_url,
                    "job_id": job_id,
                    "posted_date": posted_date,
                })
                # Gather slightly more candidate cards since non-remote ones will be filtered after description inspection
                if len(parsed_cards) >= limit * 2:
                    break
            if len(parsed_cards) >= limit * 2:
                break
        if len(parsed_cards) >= limit * 2:
            break

    if not parsed_cards:
        return []

    # Fetch all descriptions in parallel — much faster than doing it one by one
    with ThreadPoolExecutor(max_workers=5) as executor:
        job_ids = [c["job_id"] for c in parsed_cards]
        descriptions = list(executor.map(_fetch_job_description, job_ids))

    normalized = []
    for card, desc in zip(parsed_cards, descriptions):
        title = card["title"]
        loc = card["location"]
        wm = _infer_work_mode(loc, title, desc)
        if remote_only and wm != "remote":
            # If our inference says it's not remote, skip it rather than
            # force-labeling it — that was causing on-site jobs to leak through
            continue

        normalized.append({
            "title": title,
            "company": card["company"],
            "location": loc,
            "job_type": _infer_job_type(title, desc),
            "work_mode": wm,
            "description": desc,
            "url": card["url"],
            "source": "LinkedIn",
            "posted_date": card["posted_date"],
        })

    return normalized[:limit] if limit else normalized
