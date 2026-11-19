"""Matching engine: text normalization, hard filters, and weighted scoring."""

from jobctl.matching.filters import is_posting_within_previous_days, parse_posted_date, passes_hard_filters
from jobctl.matching.scoring import deduplicate_jobs, filter_and_score_jobs, score_job
from jobctl.matching.text import extract_years_required, match_skills, normalize_text, title_match_ratio

__all__ = [
    "deduplicate_jobs",
    "extract_years_required",
    "filter_and_score_jobs",
    "is_posting_within_previous_days",
    "match_skills",
    "normalize_text",
    "parse_posted_date",
    "passes_hard_filters",
    "score_job",
    "title_match_ratio",
]
