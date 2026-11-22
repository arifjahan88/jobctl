"""Hard filters for job listings: strict 2-day freshness window, work mode, job type, and level seniority."""

from __future__ import annotations

from datetime import datetime, timedelta, timezone
from email.utils import parsedate_to_datetime
import re

from jobctl.config import FilterConfig, ProfileConfig
from jobctl.matching.text import extract_years_required, normalize_text, tokenize_title
from jobctl.models import Job


def parse_posted_date(date_str: str) -> datetime | None:
    """
    Parse a posted_date string into a timezone-aware UTC datetime.
    Supports:
      - ISO date: "2026-11-21"
      - ISO datetime: "2026-11-21T12:00:00Z", "2026-11-21T12:00:00+00:00", "2026-11-21T12:00:00.000Z"
      - Relative strings from LinkedIn cards: "2 hours ago", "1 day ago", "Just now"
    """
    if not date_str or not date_str.strip():
        return None

    raw = date_str.strip()

    # Handle relative date strings (e.g., "4 hours ago", "1 day ago", "30 minutes ago")
    lower = raw.lower()
    if lower in ("just now", "today", "new"):
        return datetime.now(timezone.utc)
    rel_match = re.search(r"(\d+)\s+(minute|hour|day|week|month)s?\s+ago", lower)
    if rel_match:
        qty = int(rel_match.group(1))
        unit = rel_match.group(2)
        now = datetime.now(timezone.utc)
        if unit == "minute":
            return now - timedelta(minutes=qty)
        if unit == "hour":
            return now - timedelta(hours=qty)
        if unit == "day":
            return now - timedelta(days=qty)
        if unit == "week":
            return now - timedelta(weeks=qty)
        if unit == "month":
            return now - timedelta(days=qty * 30)

    normalized = raw.replace("Z", "+00:00")

    # Try datetime.fromisoformat first (Python 3.11+ handles most ISO variants)
    try:
        dt = datetime.fromisoformat(normalized)
        if dt.tzinfo is None:
            dt = dt.replace(tzinfo=timezone.utc)
        return dt.astimezone(timezone.utc)
    except ValueError:
        pass

    for fmt in (
        "%Y-%m-%dT%H:%M:%S%z",
        "%Y-%m-%dT%H:%M:%S.%f%z",
        "%Y-%m-%dT%H:%M:%S",
        "%Y-%m-%dT%H:%M:%S.%f",
        "%Y-%m-%d %H:%M:%S",
        "%Y-%m-%d",
        "%d %b %Y",
        "%d %B %Y",
    ):
        try:
            dt = datetime.strptime(normalized, fmt)
            if dt.tzinfo is None:
                dt = dt.replace(tzinfo=timezone.utc)
            return dt.astimezone(timezone.utc)
        except ValueError:
            continue

    # Try RFC-2822 / RSS pubDate format (e.g., "Sat, 21 Nov 2026 14:30:00 +0000")
    try:
        dt = parsedate_to_datetime(raw)
        if dt.tzinfo is None:
            dt = dt.replace(tzinfo=timezone.utc)
        return dt.astimezone(timezone.utc)
    except Exception:
        pass

    return None


def is_posting_within_previous_days(
    date_str: str,
    max_age_days: int = 2,
    require_date: bool = True,
    now: datetime | None = None,
) -> tuple[bool, str]:
    """
    Strictly check whether a job was posted within the previous `max_age_days` calendar dates
    (e.g. when max_age_days=2 and today is 2026-11-22, jobs posted on 2026-11-20, 2026-11-21,
    or 2026-11-22 pass; anything from 2026-11-19 or older is rejected).
    """
    if max_age_days is None or max_age_days <= 0:
        return True, ""

    dt = parse_posted_date(date_str)
    if dt is None:
        if require_date:
            return False, "missing or unparseable posted_date"
        return True, ""

    ref_now = (now or datetime.now(timezone.utc)).astimezone(timezone.utc)
    cutoff_date = (ref_now - timedelta(days=max_age_days)).date()
    posted_date = dt.date()

    if posted_date < cutoff_date:
        age_days = (ref_now.date() - posted_date).days
        return False, f"posting is older than {max_age_days} days ({age_days}d old)"

    return True, ""


def passes_hard_filters(
    job: Job,
    profile: ProfileConfig,
    filters: FilterConfig,
    now: datetime | None = None,
) -> tuple[bool, str]:
    """
    Evaluate all hard guardrails on a single job listing.
    Returns (passed: bool, rejection_reason: str).
    """
    # 1. Strict posting freshness (previous 2 dates by default)
    if filters.max_posting_age_days and filters.max_posting_age_days > 0:
        is_fresh, freshness_reason = is_posting_within_previous_days(
            job.posted_date,
            max_age_days=filters.max_posting_age_days,
            require_date=filters.require_posted_date,
            now=now,
        )
        if not is_fresh:
            return False, freshness_reason

    # 2. Job type check
    if job.job_type.lower() not in profile.job_types:
        return False, f"job_type '{job.job_type}' not in target list"

    # 3. Work mode check (remote only by default)
    if job.work_mode.lower() not in profile.work_modes:
        return False, f"work_mode '{job.work_mode}' not in preferences"

    # 4. Level-aware title token exclusion (e.g., excludes Senior/Staff/Principal/Lead/Manager/Intern for Mid)
    title_tokens = set(tokenize_title(job.title))
    excluded_tokens = profile.preset.excluded_title_tokens
    matched_excluded = excluded_tokens.intersection(title_tokens)
    if matched_excluded:
        tokens_str = ", ".join(sorted(matched_excluded))
        return False, f"title excluded for {profile.level} level ({tokens_str})"

    norm_title = normalize_text(job.title)
    norm_desc = normalize_text(job.description)
    combined_text = f"{norm_title} {norm_desc}"

    # 5. Extra user-configured excluded phrases
    for phrase in filters.extra_excluded_phrases:
        norm_phrase = normalize_text(phrase)
        if norm_phrase and norm_phrase in combined_text:
            return False, "matched an excluded phrase"

    # 6. Experience ceiling for the active level preset (Mid-Level allows up to 5 years)
    max_years = filters.effective_max_years(profile)
    years_required = extract_years_required(f"{job.title} {job.description}")
    if years_required is not None and years_required > max_years:
        return False, f"requires {years_required}+ years (max allowed: {max_years})"

    return True, ""
