"""LinkedIn public guest search adapter with level-aware experience codes and 2-day time filter."""

from __future__ import annotations

from concurrent.futures import ThreadPoolExecutor
import html
import re
import requests

from jobctl.config import ProfileConfig, SourceOptions
from jobctl.matching.filters import is_posting_within_previous_days
from jobctl.models import Job
from jobctl.sources.base import JobSource, build_http_session, register_source
from jobctl.sources.common import infer_job_type, infer_work_mode, is_relevant_title, sort_and_limit_jobs, strip_html

LINKEDIN_SEARCH_ENDPOINT = "https://www.linkedin.com/jobs-guest/jobs/api/seeMoreJobPostings/search"
LINKEDIN_JOB_DETAIL_TEMPLATE = "https://www.linkedin.com/jobs-guest/jobs/api/jobPosting/{job_id}"


def build_linkedin_queries(profile: ProfileConfig) -> list[str]:
    """Build level-appropriate search queries for LinkedIn based on role and core stack."""
    role = profile.role_title or "Software Engineer"
    skills = profile.skills
    top_stack = " ".join(skills[:2]) if skills else "TypeScript PostgreSQL"

    if profile.level in ("intern", "entry", "junior"):
        return [
            f"{role} {top_stack}",
            f"Junior {role}",
            f"{role} remote",
        ]

    return [
        f"{role} {top_stack}",
        f"Backend Engineer PostgreSQL",
        f"DevOps Engineer Docker Kubernetes",
        f"{role} PostgreSQL Docker",
    ]


def parse_linkedin_cards(raw_html: str, profile: ProfileConfig, max_posting_age_days: int = 2) -> list[dict]:
    """Parse raw HTML `<li>` cards from LinkedIn guest search into candidate metadata dicts."""
    cards = re.findall(r"<li[^>]*>(.*?)</li>", raw_html or "", re.DOTALL)
    parsed: list[dict] = []

    for card in cards:
        title_m = re.search(
            r'<h3[^>]*class="[^"]*base-search-card__title[^"]*"[^>]*>\s*([^<]+?)\s*</h3>',
            card,
        )
        comp_m = re.search(
            r'<h4[^>]*class="[^"]*base-search-card__subtitle[^"]*"[^>]*>.*?<a[^>]*>\s*([^<]+?)\s*</a>',
            card,
            re.DOTALL,
        )
        if not comp_m:
            comp_m = re.search(
                r'<h4[^>]*class="[^"]*base-search-card__subtitle[^"]*"[^>]*>\s*([^<]+?)\s*</h4>',
                card,
            )
        loc_m = re.search(
            r'<span[^>]*class="[^"]*job-search-card__location[^"]*"[^>]*>\s*([^<]+?)\s*</span>',
            card,
        )
        link_m = re.search(
            r'<a[^>]*class="[^"]*base-card__full-link[^"]*"[^>]*href="([^"]+)"',
            card,
        )
        time_m = re.search(r'<time[^>]*datetime="([^"]+)"', card)

        if not (title_m and link_m):
            continue

        title = html.unescape(title_m.group(1).strip())
        if not is_relevant_title(title, profile):
            continue

        posted_date = time_m.group(1).strip() if time_m else ""
        if max_posting_age_days and max_posting_age_days > 0:
            ok, _ = is_posting_within_previous_days(
                posted_date, max_age_days=max_posting_age_days, require_date=True
            )
            if not ok:
                continue

        raw_url = link_m.group(1).split("?")[0]
        job_id_match = re.search(r"(\d{8,})", raw_url)
        job_id = job_id_match.group(1) if job_id_match else raw_url

        company = html.unescape(comp_m.group(1).strip()) if comp_m else "Unknown Company"
        job_loc = html.unescape(loc_m.group(1).strip()) if loc_m else "Remote / Worldwide"

        parsed.append(
            {
                "title": title,
                "company": company,
                "location": job_loc,
                "url": raw_url,
                "job_id": job_id,
                "posted_date": posted_date,
            }
        )

    return parsed


def _fetch_job_description(session: requests.Session, job_id: str) -> str:
    if not job_id or not job_id.isdigit():
        return ""
    url = LINKEDIN_JOB_DETAIL_TEMPLATE.format(job_id=job_id)
    try:
        res = session.get(url, timeout=7)
        if res.status_code == 200:
            match = re.search(
                r'<div class="show-more-less-html__markup[^"]*"[^>]*>(.*?)</div>',
                res.text,
                re.DOTALL,
            )
            if match:
                return strip_html(match.group(1))
    except Exception:
        pass
    return ""


@register_source("linkedin")
class LinkedInSource(JobSource):
    description = "LinkedIn Guest Search (Global Remote, 48h window)"

    def fetch(
        self,
        profile: ProfileConfig,
        options: SourceOptions,
        max_posting_age_days: int = 2,
        session: requests.Session | None = None,
    ) -> list[Job]:
        http = session or build_http_session()
        limit = options.limit or 40
        remote_only = "remote" in profile.work_modes
        queries = build_linkedin_queries(profile)

        # f_TPR=r{seconds} restricts LinkedIn search directly to the past N days (2 days = r172800)
        tpr_seconds = max(1, max_posting_age_days) * 86400 if max_posting_age_days else 172800

        seen_ids: set[str] = set()
        candidate_cards: list[dict] = []

        for query in queries:
            for page_start in (0, 25):
                params: dict[str, str | int] = {
                    "keywords": query,
                    "start": page_start,
                    "f_E": profile.preset.linkedin_f_e,
                    "f_TPR": f"r{tpr_seconds}",
                }
                if profile.location and profile.location.lower() not in ("worldwide", "anywhere"):
                    params["location"] = profile.location
                if remote_only:
                    params["f_WT"] = "2"

                try:
                    res = http.get(LINKEDIN_SEARCH_ENDPOINT, params=params, timeout=10)
                    if res.status_code != 200 or not res.text.strip():
                        break
                except Exception:
                    break

                cards = parse_linkedin_cards(res.text, profile, max_posting_age_days=max_posting_age_days)
                if not cards:
                    break

                for card in cards:
                    jid = card["job_id"]
                    if jid in seen_ids:
                        continue
                    seen_ids.add(jid)
                    candidate_cards.append(card)
                    if len(candidate_cards) >= limit * 2:
                        break
                if len(candidate_cards) >= limit * 2:
                    break
            if len(candidate_cards) >= limit * 2:
                break

        if not candidate_cards:
            return []

        with ThreadPoolExecutor(max_workers=6) as pool:
            descriptions = list(
                pool.map(lambda c: _fetch_job_description(http, c["job_id"]), candidate_cards)
            )

        jobs: list[Job] = []
        for card, desc in zip(candidate_cards, descriptions):
            work_mode = infer_work_mode(card["location"], card["title"], desc)
            if remote_only and work_mode != "remote":
                continue

            jobs.append(
                Job(
                    title=card["title"],
                    company=card["company"],
                    location=card["location"],
                    job_type=infer_job_type(card["title"], desc),
                    work_mode=work_mode,
                    description=desc,
                    url=card["url"],
                    source="LinkedIn",
                    posted_date=card["posted_date"],
                )
            )

        return sort_and_limit_jobs(jobs, limit=limit, max_posting_age_days=max_posting_age_days)
