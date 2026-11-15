"""
matcher.py — the filtering and scoring brain of jobctl.

Every job listing that comes in from the adapters passes through here.
The flow is simple:

  1. Hard filters — is it remote? Not too senior? Not asking for 5+ years?
     If any of these fail, the listing is dropped immediately.

  2. Soft scoring — how many of your target skills appear in the description?
     Does the title match what you're looking for? Score is 0–100.

  3. Cutoff — anything below MIN_MATCH_SCORE is dropped (or sent to near-misses).

No network calls happen here. This is pure logic, which makes it easy to test
independently of any particular job portal.
"""

import re
from datetime import datetime, timezone, timedelta


def _normalize(text: str) -> str:
    """
    Clean up text so comparisons stay consistent — lowercases everything,
    treats hyphens and underscores as spaces (so "full-stack" and "full stack"
    both hit the same match), and collapses extra whitespace.
    """
    text = re.sub(r"[-_/]", " ", text or "")
    return re.sub(r"\s+", " ", text).strip().lower()


def _extract_years_required(description: str):
    """
    Scans the text for years-of-experience requirements across multiple phrasing
    conventions (e.g. '3+ years of experience', '3-5 years professional experience',
    'minimum 3 years', 'experience: 3+ years', '3+ years building/developing').
    Returns the minimum required years detected (or maximum if a single threshold is stated),
    or None if no experience requirement is found.
    """
    if not description:
        return None

    years_found = []

    # Pattern 1: 'N(+) (- M) years/yrs [within 8 words] experience/exp/working/building/developing'
    for m in re.finditer(
        r"(?:^|\b)(\d+)\s*\+?\s*(?:-|to)?\s*(\d+)?\s*\+?\s*(?:years?|yrs?)\b(?:\s+[\w\-\'\"]+){0,8}\s+(?:experience|exp|working|building|developing|coding|engineering)\b",
        description,
        re.I,
    ):
        y1 = int(m.group(1))
        if y1 < 25:  # discard spurious numbers like 2024
            years_found.append(y1)
        if m.group(2):
            y2 = int(m.group(2))
            if y2 < 25:
                years_found.append(y2)

    # Pattern 2: 'experience/exp [:/-] [within 6 words] N(+) (- M) years/yrs'
    for m in re.finditer(
        r"\b(?:experience|exp)\b(?:\s*[:\-])?(?:\s+[\w\-\'\"]+){0,6}\s+(\d+)\s*\+?\s*(?:-|to)?\s*(\d+)?\s*\+?\s*(?:years?|yrs?)\b",
        description,
        re.I,
    ):
        y1 = int(m.group(1))
        if y1 < 25:
            years_found.append(y1)
        if m.group(2):
            y2 = int(m.group(2))
            if y2 < 25:
                years_found.append(y2)

    # Pattern 3: 'minimum of N / at least N / requires N years'
    for m in re.finditer(
        r"\b(?:minimum\s+(?:of\s+)?|at\s+least\s+|require[sd]?\s+(?:a\s+minimum\s+of\s+)?|must\s+have\s+)(\d+)\s*\+?\s*(?:-|to)?\s*(\d+)?\s*\+?\s*(?:years?|yrs?)\b",
        description,
        re.I,
    ):
        y1 = int(m.group(1))
        if y1 < 25:
            years_found.append(y1)
        if m.group(2):
            y2 = int(m.group(2))
            if y2 < 25:
                years_found.append(y2)

    # Pattern 4: Direct 'N+ years' shorthand (e.g. '3+ years', '4+ years', '5+ yrs')
    for m in re.finditer(r"\b(\d+)\+\s*(?:years?|yrs?)\b", description, re.I):
        y1 = int(m.group(1))
        if y1 < 25:
            years_found.append(y1)

    return max(years_found) if years_found else None


def _parse_posted_date(date_str: str) -> datetime | None:
    """
    Attempt to parse a posted_date string into a timezone-aware datetime.
    Handles the various formats returned by different adapters:
      - ISO date: "2026-09-01"
      - ISO datetime: "2026-09-01T12:00:00Z" or "2026-09-01T12:00:00+00:00"
      - Lever-style ISO: "2026-09-01T12:00:00.000Z"
    Returns None if parsing fails or the string is empty.
    """
    if not date_str or not date_str.strip():
        return None

    date_str = date_str.strip()

    # Try ISO datetime first (handles Z suffix, +00:00 offsets, fractional seconds)
    for fmt in (
        "%Y-%m-%dT%H:%M:%S%z",
        "%Y-%m-%dT%H:%M:%S.%f%z",
        "%Y-%m-%dT%H:%M:%S",
        "%Y-%m-%dT%H:%M:%S.%f",
        "%Y-%m-%d",
    ):
        try:
            # Replace 'Z' with '+00:00' for Python's %z
            normalized = date_str.replace("Z", "+00:00")
            dt = datetime.strptime(normalized, fmt)
            # If no timezone, assume UTC
            if dt.tzinfo is None:
                dt = dt.replace(tzinfo=timezone.utc)
            return dt
        except ValueError:
            continue

    return None


def _is_posting_fresh(date_str: str, max_age_days: int) -> tuple[bool, str]:
    """
    Check if a posting is within the freshness window.

    Returns (is_fresh: bool, reason: str).
    If the date can't be parsed, the job is considered fresh (benefit of the doubt).
    """
    if not max_age_days or max_age_days <= 0:
        return True, ""

    dt = _parse_posted_date(date_str)
    if dt is None:
        # Can't determine age — keep the listing rather than penalize it
        return True, ""

    cutoff = datetime.now(timezone.utc) - timedelta(days=max_age_days)
    if dt < cutoff:
        age_days = (datetime.now(timezone.utc) - dt).days
        return False, f"posting is {age_days} days old (max {max_age_days})"

    return True, ""


def passes_hard_filters(
    job: dict, config: dict, max_years: int, senior_exclusion_phrases: list,
    max_posting_age_days: int = 0,
) -> tuple:
    """
    Returns (passed: bool, reason: str).
    If passed is False, reason explains exactly why — useful for the rejection
    log that main.py prints at the end of a run.
    """
    # Posting freshness check — drop stale listings before doing anything else
    if max_posting_age_days and max_posting_age_days > 0:
        is_fresh, freshness_reason = _is_posting_fresh(
            job.get("posted_date", ""), max_posting_age_days
        )
        if not is_fresh:
            return False, freshness_reason

    description = _normalize(job.get("description", ""))
    title = _normalize(job.get("title", ""))

    # Wrong job type? Skip it.
    if job.get("job_type") not in config["target_job_types"]:
        return False, f"job_type '{job.get('job_type')}' not in target list"

    # Not remote? Skip it.
    if job.get("work_mode") not in config["work_preferences"]:
        return False, f"work_mode '{job.get('work_mode')}' not in preferences"

    # Title contains a seniority word like "senior", "lead", "director", etc.?
    # Drop it — these almost always have hidden experience requirements even if
    # the posted level sounds junior-friendly.
    if config.get("proficiency_level") in ("Intern", "Entry-Level", "Junior"):
        senior_title_tokens = {"senior", "sr", "staff", "principal", "lead", "director", "vp", "manager", "head"}
        title_tokens = set(title.split())
        matched_senior = senior_title_tokens.intersection(title_tokens)
        if matched_senior:
            return False, f"title indicates high seniority ({', '.join(sorted(matched_senior))})"

    combined_text = f"{title} {description}"

    # Phrase-level check — catches things like "3+ years" in the body text
    if any(phrase in combined_text for phrase in senior_exclusion_phrases):
        return False, "matched a senior-level exclusion phrase"

    # Number-based check — drops anything requiring more years than your level allows
    years_required = _extract_years_required(combined_text)
    if years_required is not None and years_required > max_years:
        return False, f"requires {years_required}+ years (max allowed: {max_years})"

    return True, ""


def _title_match_ratio(job_title: str, target_titles: list) -> float:
    """
    Checks the job title against every title variant in your target_titles list
    and returns the best word-overlap ratio found. This means a listing titled
    "Backend Engineer" still scores well if "Backend Engineer" is in your list,
    even if your role_title is "Full-Stack Developer".

    Falls back to role_title alone if target_titles isn't set — so older
    config.py files without that field won't break.
    """
    best_ratio = 0.0
    for candidate in target_titles:
        candidate_words = _normalize(candidate).split()
        if not candidate_words:
            continue
        hits = sum(1 for word in candidate_words if word in job_title)
        ratio = hits / len(candidate_words)
        best_ratio = max(best_ratio, ratio)
    return best_ratio


def score_job(
    job: dict, config: dict, weights: dict, skill_match_target: int = None
) -> dict:
    """
    Computes a 0–100 match score for a single job and returns a copy of the
    job dict with 'match_score', 'match_summary', 'matched_skills', and
    'score_breakdown' added in.

    About skill_match_target: this controls how many matched skills = full credit.
    Defaults to min(4, total skills). The reason for the cap is that requiring
    ALL 13 of your target skills to appear in one description is unrealistic —
    a listing that mentions 4–5 solid skills is already a very good match.
    """
    description = _normalize(job.get("description", ""))
    title = _normalize(job.get("title", ""))
    combined_text = f"{title} {description}"

    # Skill matching is word-by-word rather than exact-phrase. A skill like
    # "rest api" is counted as matched if both "rest" and "api" appear in the
    # description, even if they're not adjacent. This is more forgiving and
    # avoids missing listings that phrase things slightly differently.
    skills = config["target_skills"]
    matched_skills = []
    for skill in skills:
        skill_words = _normalize(skill).split()
        if skill_words and all(word in combined_text for word in skill_words):
            matched_skills.append(skill)

    target = skill_match_target or min(4, len(skills)) or 1
    skill_ratio = min(len(matched_skills) / target, 1.0)

    # Title relevance — checks against every variant in target_titles
    target_titles = config.get("target_titles") or [config["role_title"]]
    title_ratio = _title_match_ratio(title, target_titles)

    # Job type match — by this point, the hard filter already confirmed the
    # type is in the target list, so this is basically always full credit
    job_type_score = 1.0 if job.get("job_type") in config["target_job_types"] else 0.0

    final_score = round(
        100
        * (
            weights["skills"] * skill_ratio
            + weights["title_relevance"] * title_ratio
            + weights["job_type_match"] * job_type_score
        )
    )

    if matched_skills:
        summary = (
            f"Matches {len(matched_skills)}/{len(skills)} target skills: "
            f"{', '.join(matched_skills)}."
        )
    else:
        summary = "No direct skill keyword overlap found in description."

    enriched = dict(job)
    enriched["match_score"] = final_score
    enriched["match_summary"] = summary
    enriched["matched_skills"] = matched_skills
    # score_breakdown is attached for debugging / near-miss reporting — it's
    # not written to the docx but main.py shows it for near-miss jobs
    enriched["score_breakdown"] = {
        "skills_pct": round(skill_ratio * 100),
        "title_pct": round(title_ratio * 100),
        "job_type_pct": round(job_type_score * 100),
    }
    return enriched


def filter_and_score_jobs(
    jobs: list,
    config: dict,
    max_years_by_level: dict,
    senior_exclusion_phrases: list,
    score_weights: dict,
    min_score: int,
    rejection_log: dict = None,
    near_miss_collector: list = None,
    skill_match_target: int = None,
    max_posting_age_days: int = 0,
    min_skills_pct: int = 0,
    min_title_pct: int = 0,
) -> list:
    """
    Runs the full pipeline over a list of normalized jobs and returns only
    the ones that pass hard filters AND hit the minimum match score,
    sorted best-first.

    Pass in rejection_log (a dict) to get a count breakdown of why listings
    were dropped — useful for diagnosing why you got fewer results than expected.

    Pass in near_miss_collector (a list) to capture jobs that passed the hard
    filters but scored just below min_score — handy for calibrating your
    MIN_MATCH_SCORE or target_skills without having to guess blindly.
    """
    max_years = max_years_by_level.get(config["proficiency_level"], 2)
    results = []

    for job in jobs:
        passed, reason = passes_hard_filters(
            job,
            config,
            max_years,
            senior_exclusion_phrases,
            max_posting_age_days=max_posting_age_days,
        )
        if not passed:
            if rejection_log is not None:
                # Group by category rather than the full message so the counts
                # stay meaningful (e.g. "job_type mismatch: 5" not 5 separate entries)
                category = reason.split("'")[0].strip() if "'" in reason else reason
                rejection_log[category] = rejection_log.get(category, 0) + 1
            continue

        scored = score_job(job, config, score_weights, skill_match_target)

        # Check skills and title threshold requirements (e.g. 60-70% match)
        skills_pct = scored["score_breakdown"]["skills_pct"]
        title_pct = scored["score_breakdown"]["title_pct"]

        if min_skills_pct and skills_pct < min_skills_pct:
            if rejection_log is not None:
                category = f"skills match too low ({skills_pct}% < {min_skills_pct}%)"
                rejection_log[category] = rejection_log.get(category, 0) + 1
            if near_miss_collector is not None:
                near_miss_collector.append(scored)
            continue

        if min_title_pct and title_pct < min_title_pct:
            if rejection_log is not None:
                category = f"title relevance too low ({title_pct}% < {min_title_pct}%)"
                rejection_log[category] = rejection_log.get(category, 0) + 1
            if near_miss_collector is not None:
                near_miss_collector.append(scored)
            continue

        if scored["match_score"] >= min_score:
            results.append(scored)
        else:
            if rejection_log is not None:
                category = (
                    f"below min_score (needed {min_score}, got {scored['match_score']})"
                )
                rejection_log[category] = rejection_log.get(category, 0) + 1
            if near_miss_collector is not None:
                near_miss_collector.append(scored)

    results.sort(key=lambda j: j["match_score"], reverse=True)
    return results


def deduplicate_jobs(jobs: list) -> list:
    """
    Removes duplicate listings across sources using (normalized title, normalized company)
    as the key. Keeps the first occurrence, which is deterministic because sources
    are always queried in the same fixed order (LinkedIn → Wellfound → Ashby → Greenhouse → Lever).
    """
    seen = set()
    unique_jobs = []

    for job in jobs:
        key = (_normalize(job.get("title", "")), _normalize(job.get("company", "")))
        if key not in seen:
            seen.add(key)
            unique_jobs.append(job)

    return unique_jobs
