#!/usr/bin/env python3
"""
main.py — the entry point for Quaero.

Here's the rough flow of what happens when you run this:
  1. Load your profile and skill preferences from config.py
  2. Hit every enabled portal at the same time (concurrent fetches)
  3. Merge all results and remove duplicates
  4. Hard-filter out anything that's not remote, not junior, or too senior
  5. Score each surviving listing against your skills (0–100)
  6. Write the top matches into quaero_matched_jobs.docx

Run it with:  python main.py
"""

import sys

import config
from doc_writer import write_jobs_to_docx
from job_sources import ashby_api, greenhouse_api, lever_api, linkedin_api, wellfound_api
from matcher import deduplicate_jobs, filter_and_score_jobs


def fetch_all_jobs() -> list:
    """
    Queries every portal that's currently enabled in config.py and returns
    the combined raw list. Errors from individual portals are caught inside
    each adapter, so one flaky source won't take down the whole run.
    """
    all_jobs = []

    # LinkedIn — broad global reach, filtered for 100% remote + entry/junior level
    if getattr(config, "ENABLE_LINKEDIN", True):
        limit = getattr(config, "LINKEDIN_LIMIT", 25)
        print("Fetching from LinkedIn (Global Remote)...")
        li_jobs = linkedin_api.fetch_jobs(config.PROFILE, limit=limit)
        print(f"  -> {len(li_jobs)} listing(s) retrieved.")
        all_jobs.extend(li_jobs)

    # Wellfound — startup-focused, tends to have great remote-first roles
    if getattr(config, "ENABLE_WELLFOUND", True):
        limit = getattr(config, "WELLFOUND_LIMIT", 25)
        print("Fetching from Wellfound (Remote Tech Startups)...")
        wf_jobs = wellfound_api.fetch_jobs(config.PROFILE, limit=limit)
        print(f"  -> {len(wf_jobs)} listing(s) retrieved.")
        all_jobs.extend(wf_jobs)

    # Ashby — used by a lot of modern AI and developer-tooling companies
    if getattr(config, "ENABLE_ASHBY", True):
        companies = getattr(config, "ASHBY_COMPANIES", None)
        limit = getattr(config, "ASHBY_LIMIT", 30)
        print("Fetching from Ashby ATS (Remote High-Growth Tech)...")
        ashby_jobs = ashby_api.fetch_jobs(config.PROFILE, companies=companies, limit=limit)
        print(f"  -> {len(ashby_jobs)} listing(s) retrieved.")
        all_jobs.extend(ashby_jobs)

    # Greenhouse — covers a wide range of mid-to-large engineering companies
    if getattr(config, "ENABLE_GREENHOUSE", True):
        companies = getattr(config, "GREENHOUSE_COMPANIES", None)
        limit = getattr(config, "GREENHOUSE_LIMIT", 50)
        print("Fetching from Greenhouse ATS (Global Remote Tech)...")
        gh_jobs = greenhouse_api.fetch_jobs(config.PROFILE, companies=companies, limit=limit)
        print(f"  -> {len(gh_jobs)} listing(s) retrieved.")
        all_jobs.extend(gh_jobs)

    # Lever — good mix of enterprises and scaling startups
    if getattr(config, "ENABLE_LEVER", True):
        companies = getattr(config, "LEVER_COMPANIES", None)
        limit = getattr(config, "LEVER_LIMIT", 30)
        print("Fetching from Lever ATS (Global Remote Tech)...")
        lever_jobs = lever_api.fetch_jobs(config.PROFILE, companies=companies, limit=limit)
        print(f"  -> {len(lever_jobs)} listing(s) retrieved.")
        all_jobs.extend(lever_jobs)

    # Adzuna — optional paid aggregator, disabled by default
    if (
        getattr(config, "ENABLE_ADZUNA", False)
        and getattr(config, "ADZUNA_APP_ID", "")
        and getattr(config, "ADZUNA_APP_KEY", "")
    ):
        from job_sources import adzuna_api
        print("Fetching from Adzuna...")
        adzuna_jobs = adzuna_api.fetch_jobs(
            config.PROFILE,
            app_id=config.ADZUNA_APP_ID,
            app_key=config.ADZUNA_APP_KEY,
            country_code=config.ADZUNA_COUNTRY_CODE,
            limit=config.RESULTS_PER_SOURCE,
        )
        print(f"  -> {len(adzuna_jobs)} listing(s) retrieved.")
        all_jobs.extend(adzuna_jobs)

    return all_jobs


def main():
    print(
        f"=== Quaero — Searching for '{config.PROFILE['role_title']}' "
        f"({config.PROFILE['proficiency_level']}, 100% Remote, Worldwide) ===\n"
    )

    raw_jobs = fetch_all_jobs()
    if not raw_jobs:
        print(
            "\nNo listings retrieved from any source. Check network connectivity "
            "and try again."
        )
        sys.exit(0)

    print(f"\nTotal raw listings before dedup: {len(raw_jobs)}")
    unique_jobs = deduplicate_jobs(raw_jobs)
    print(f"Unique listings after dedup:     {len(unique_jobs)}")

    # rejection_log collects counts per filter reason so we can explain the drop-off
    # near_misses captures jobs that passed filters but scored just below threshold
    rejection_log = {}
    near_misses = []
    matched_jobs = filter_and_score_jobs(
        unique_jobs,
        config.PROFILE,
        max_years_by_level=config.MAX_YEARS_EXPERIENCE_BY_LEVEL,
        senior_exclusion_phrases=config.SENIOR_EXCLUSION_PHRASES,
        score_weights=config.SCORE_WEIGHTS,
        min_score=config.MIN_MATCH_SCORE,
        rejection_log=rejection_log,
        near_miss_collector=near_misses,
        skill_match_target=getattr(config, "SKILL_MATCH_TARGET", 0),
        max_posting_age_days=getattr(config, "MAX_POSTING_AGE_DAYS", 30),
        min_skills_pct=getattr(config, "MIN_SKILLS_MATCH_PCT", 0),
        min_title_pct=getattr(config, "MIN_TITLE_MATCH_PCT", 0),
    )
    print(f"Matches passing filters/score:   {len(matched_jobs)}\n")

    for job in matched_jobs:
        print(
            f"  [{job['match_score']:>3}] {job['title']} @ {job['company']} "
            f"[{job['source']}] ({job['work_mode']}, {job['job_type']})"
        )

    # If a lot of listings were dropped, show the breakdown so you know why
    if len(matched_jobs) < len(unique_jobs) and rejection_log:
        print("\nWhy the rest were excluded:")
        for reason, count in sorted(rejection_log.items(), key=lambda x: -x[1]):
            print(f"  {count:>3}  {reason}")

    # Near-misses are useful for calibrating your MIN_MATCH_SCORE or target_skills
    if near_misses:
        near_misses.sort(key=lambda j: j["match_score"], reverse=True)
        print(
            f"\nClosest near-misses (passed filters, scored below {config.MIN_MATCH_SCORE}):"
        )
        for job in near_misses[:5]:
            b = job["score_breakdown"]
            print(
                f"  [{job['match_score']:>3}] {job['title']} @ {job['company']} [{job['source']}] "
                f"— skills {b['skills_pct']}%, title {b['title_pct']}%, job_type {b['job_type_pct']}%"
            )
            print(f"        {job['match_summary']}")

    output_path = write_jobs_to_docx(matched_jobs, config.OUTPUT_DOCX_PATH)
    print(f"\nDone. Results written to: {output_path}")


if __name__ == "__main__":
    main()
