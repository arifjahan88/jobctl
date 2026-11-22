"""Unit tests for word-boundary skill matching, alias expansion, and experience range parsing."""

from __future__ import annotations

import unittest

from jobctl.matching.text import (
    extract_years_required,
    match_skills,
    skill_matches_text,
    title_match_ratio,
)


def test_skill_word_boundary_prevents_false_positives() -> None:
    text = (
        "Drive our digital transformation with reactive UI patterns, regular expressions, "
        "and NoSQL document stores."
    )
    assert not skill_matches_text("git", text)
    assert not skill_matches_text("react", text)
    assert not skill_matches_text("express", text)
    assert not skill_matches_text("sql", text)


def test_skill_aliases_match_canonical_skills() -> None:
    text = "Experience managing Postgres databases, k8s clusters, Node services, and GH Actions."
    matched = match_skills(
        ["postgresql", "kubernetes", "node.js", "github actions", "terraform"],
        text,
    )
    assert matched == ["postgresql", "kubernetes", "node.js", "github actions"]


def test_extract_years_uses_lower_bound_of_ranges() -> None:
    assert extract_years_required("Requires 2-4 years of professional software engineering experience.") == 2
    assert extract_years_required("At least 3 to 5 years building backend systems.") == 3
    assert extract_years_required("5+ years of DevOps experience required.") == 5
    assert extract_years_required("Founded in 2024 with 50+ employees worldwide.") is None


def test_title_match_ratio_uses_tokens() -> None:
    targets = ["Software Engineer", "DevOps Engineer", "Database Engineer"]
    assert title_match_ratio("DevOps Engineer (Remote)", targets) == 1.0
    assert title_match_ratio("Backend Software Engineer II", targets) == 1.0
    assert title_match_ratio("Account Executive", targets) == 0.0


class TestTextMatching(unittest.TestCase):
    def test_all(self) -> None:
        test_skill_word_boundary_prevents_false_positives()
        test_skill_aliases_match_canonical_skills()
        test_extract_years_uses_lower_bound_of_ranges()
        test_title_match_ratio_uses_tokens()
