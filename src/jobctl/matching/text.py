"""Text normalization, word-boundary skill matching with aliases, and experience extraction."""

from __future__ import annotations

from functools import lru_cache
import re

# Canonical skill -> common synonyms / spelling variants
SKILL_ALIASES: dict[str, tuple[str, ...]] = {
    "typescript": ("typescript",),
    "javascript": ("javascript", "ecmascript"),
    "node.js": ("node.js", "nodejs", "node js", "node"),
    "nestjs": ("nestjs", "nest.js", "nest js"),
    "express": ("express.js", "expressjs", "express"),
    "react": ("react.js", "reactjs", "react"),
    "next.js": ("next.js", "nextjs", "next js"),
    "postgresql": ("postgresql", "postgres", "psql", "pgvector"),
    "sql": ("sql", "pl/pgsql", "tsql", "t-sql"),
    "redis": ("redis",),
    "docker": ("docker", "dockerfile", "docker-compose", "containerization"),
    "kubernetes": ("kubernetes", "k8s", "helm", "kubectl"),
    "ci/cd": ("ci/cd", "ci cd", "cicd", "continuous integration", "continuous delivery", "continuous deployment"),
    "github actions": ("github actions", "gh actions"),
    "aws": ("aws", "amazon web services", "ec2", "ecs", "eks", "rds", "s3"),
    "linux": ("linux", "ubuntu", "debian", "rhel", "bash", "systemd"),
    "terraform": ("terraform", "iac", "infrastructure as code", "opentofu"),
    "nginx": ("nginx", "reverse proxy"),
    "microservices": ("microservices", "micro-services", "microservice", "distributed systems"),
    "rest api": ("rest api", "restful api", "restful", "rest apis", "graphql", "grpc"),
    "erp": ("erp", "enterprise resource planning", "odoo", "sap", "netsuite", "erpnext"),
    "mongodb": ("mongodb", "mongo"),
    "git": ("git",),
    "python": ("python", "fastapi", "django"),
    "go": ("golang",),
}

TITLE_STOP_WORDS: frozenset[str] = frozenset(
    {
        "and",
        "or",
        "in",
        "at",
        "for",
        "to",
        "the",
        "a",
        "an",
        "of",
        "with",
        "remote",
    }
)


def normalize_text(text: str) -> str:
    """Lowercase text, replace hyphens/underscores/slashes with spaces, and collapse whitespace."""
    cleaned = re.sub(r"[-_/]", " ", text or "")
    return re.sub(r"\s+", " ", cleaned).strip().lower()


def tokenize_title(text: str) -> list[str]:
    """Split a job title into lowercase alphanumeric tokens."""
    cleaned = re.sub(r"[^a-zA-Z0-9\+\.#]+", " ", (text or "").lower())
    return [tok.strip(".") for tok in cleaned.split() if tok.strip(".")]


@lru_cache(maxsize=512)
def _compile_skill_regex(term: str) -> re.Pattern[str]:
    """
    Build a strict word-boundary regex for a skill or alias.
    Prevents substring false positives like:
      - 'git' matching 'digital'
      - 'react' matching 'reactive'
      - 'express' matching 'expression'
      - 'sql' matching 'postgresql' or 'nosql'
    """
    norm = term.strip().lower()
    # Allow flexible separator between words/dots/slashes (e.g. "node.js", "ci/cd")
    tokens = [re.escape(part) for part in re.split(r"[\s\./\-]+", norm) if part]
    if not tokens:
        return re.compile(r"(?!x)x")
    body = r"[\s\./\-]*".join(tokens)
    return re.compile(rf"(?<![a-z0-9_]){body}(?![a-z0-9_])", re.IGNORECASE)


def skill_matches_text(skill: str, text: str) -> bool:
    """Return True if `skill` (or any of its registered aliases) appears as a whole term in `text`."""
    if not text or not skill:
        return False
    canonical = skill.strip().lower()
    variants = SKILL_ALIASES.get(canonical, (canonical,))
    for variant in variants:
        if _compile_skill_regex(variant).search(text):
            return True
    return False


def match_skills(skills: list[str], text: str) -> list[str]:
    """Return all skills from `skills` that match `text` using word-boundary + alias matching."""
    if not text:
        return []
    return [skill for skill in skills if skill_matches_text(skill, text)]


def extract_years_required(description: str) -> int | None:
    """
    Extract required years of experience from a job description.

    When a range is given (e.g. "2-4 years of experience" or "3 to 5 years"),
    we take the LOWER bound (the minimum required to qualify: 2 or 3).
    When multiple requirements are stated across the description, we return
    the maximum of those minimum thresholds.
    """
    if not description:
        return None

    thresholds: list[int] = []

    patterns = (
        # Pattern 1: "N (+ / - M) years ... experience/working/building/developing/engineering"
        r"(?:^|\b)(\d+)\s*\+?\s*(?:(?:-|to|–)\s*(\d+)\s*\+?\s*)?(?:years?|yrs?)\b"
        r"(?:\s+[\w\-\'\"/,\(\)]+){0,8}\s+"
        r"(?:experience|exp|working|building|developing|coding|engineering|designing|managing)\b",
        # Pattern 2: "experience: N (- M) years"
        r"\b(?:experience|exp)\b(?:\s*[:\-])?(?:\s+[\w\-\'\"/,\(\)]+){0,6}\s+"
        r"(\d+)\s*\+?\s*(?:(?:-|to|–)\s*(\d+)\s*\+?\s*)?(?:years?|yrs?)\b",
        # Pattern 3: "minimum of N / at least N / requires N (- M) years"
        r"\b(?:minimum\s+(?:of\s+)?|at\s+least\s+|require[sd]?\s+(?:a\s+minimum\s+of\s+)?|must\s+have\s+)"
        r"(\d+)\s*\+?\s*(?:(?:-|to|–)\s*(\d+)\s*\+?\s*)?(?:years?|yrs?)\b",
        # Pattern 4: Direct "N+ years" shorthand (e.g. "3+ years", "5+ yrs")
        r"\b(\d+)\+\s*(?:years?|yrs?)\b",
    )

    for pat in patterns:
        for match in re.finditer(pat, description, re.IGNORECASE):
            lower_bound = int(match.group(1))
            if 0 < lower_bound < 20:
                thresholds.append(lower_bound)

    return max(thresholds) if thresholds else None


def title_match_ratio(job_title: str, target_titles: list[str]) -> float:
    """
    Compute the best token-overlap ratio between `job_title` and `target_titles`.
    Uses whole tokens (excluding stop words) rather than raw substrings so
    "Engineer" doesn't artificially match unrelated words.
    """
    job_tokens = set(tokenize_title(job_title)) - TITLE_STOP_WORDS
    if not job_tokens:
        return 0.0

    best_ratio = 0.0
    for candidate in target_titles:
        cand_tokens = [t for t in tokenize_title(candidate) if t not in TITLE_STOP_WORDS]
        if not cand_tokens:
            continue
        hits = sum(1 for tok in cand_tokens if tok in job_tokens)
        ratio = hits / len(cand_tokens)
        if ratio > best_ratio:
            best_ratio = ratio
    return best_ratio
