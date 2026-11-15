"""
config.py — this is the one file you actually need to edit.

Set your role, skills, and experience level here and jobctl will do the rest.
Everything from which portals to query to how strict the scoring cutoff is
lives in this file.
"""

# ---------------------------------------------------------------------------
# JOB TITLES TO MATCH AGAINST
# ---------------------------------------------------------------------------
# jobctl scores incoming job titles against this list.
# Add or remove titles to match how companies in your target industry write them.
TARGET_JOB_TITLES = [
    # Standard Full-Stack & Web Titles
    "Full-Stack Developer",
    "Full Stack Developer",
    "Fullstack Developer",
    "Full-Stack Engineer",
    "Full Stack Engineer",
    "Fullstack Engineer",
    "Software Engineer - Full Stack",
    "Software Engineer (Full Stack)",
    "Software Development Engineer - Full Stack",
    "Web Developer",
    "Full Stack Web Developer",
    # Early-Career & Junior Variations (0-2 years)
    "Junior Full Stack Developer",
    "Junior Full Stack Engineer",
    "Junior Software Engineer",
    "Junior Web Developer",
    "Associate Software Engineer",
    "Associate Full Stack Engineer",
    "Entry Level Software Engineer",
    "Entry Level Full Stack Developer",
    "Software Engineer I",
    "Software Development Engineer I",
    "SDE I",
    "SE I",
    "Graduate Software Engineer",
    # Internship Variations
    "Software Engineer Intern",
    "Full Stack Developer Intern",
    "Software Engineering Intern",
    "Full Stack Intern",
    "Web Development Intern",
    # Tech Stack-Specific Titles
    "TypeScript Developer",
    "TypeScript Engineer",
    "Node.js Developer",
    "React Developer",
    "React / Node Developer",
    "JavaScript Developer",
    "Full Stack TypeScript Engineer",
    "Frontend Engineer",
    "Backend Engineer",
]

# ---------------------------------------------------------------------------
# YOUR PROFILE — who you are & what you're looking for
# ---------------------------------------------------------------------------
PROFILE = {
    # This drives the search keyword and title scoring
    "role_title": "Full-Stack Developer",
    "target_titles": TARGET_JOB_TITLES,

    # "Junior" enforces a hard ceiling of 2 years of experience in job descriptions
    # Options: "Intern" (0 yr), "Entry-Level" (0-1 yr), "Junior" (0-2 yrs)
    "proficiency_level": "Junior",

    # Only 100% remote — hybrid and on-site listings are skipped
    "work_preferences": ["remote"],

    # Job arrangements you're open to
    "target_job_types": ["internship", "full-time", "part-time", "contract"],

    # Your tech stack — each skill here is looked for in every job description
    # and contributes to the match score (65% weight total)
    "target_skills": [
        "typescript",
        "javascript",
        "react",
        "node.js",
        "next.js",
        "express",
        "nestjs",
        "mongodb",
        "postgresql",
        "rest api",
        "git",
    ],

    # Worldwide means no location filter is applied — truly global search
    "location": "Worldwide",
}

# ---------------------------------------------------------------------------
# WHICH PORTALS TO QUERY
# ---------------------------------------------------------------------------
# Flip any of these to False to skip that source entirely
ENABLE_LINKEDIN = True       # Global guest search (no login needed)
ENABLE_WELLFOUND = True      # Remote-first tech startups
ENABLE_GREENHOUSE = True     # Greenhouse ATS (GitLab, Stripe, Figma, Coinbase, etc.)
ENABLE_LEVER = True          # Lever ATS (Spotify, Postman, Atlassian, etc.)
ENABLE_ASHBY = True          # Ashby ATS (Linear, Sentry, OpenAI, PostHog, etc.)
ENABLE_ADZUNA = False        # Optional — needs API credentials below

# How many listings to pull per source per run
LINKEDIN_LIMIT = 25
WELLFOUND_LIMIT = 25
GREENHOUSE_LIMIT = 50
LEVER_LIMIT = 30
ASHBY_LIMIT = 30

# Custom company slug lists for each ATS. If you leave these as None,
# each adapter falls back to its own built-in global registry.
GREENHOUSE_COMPANIES = None
LEVER_COMPANIES = None
ASHBY_COMPANIES = None

# ---------------------------------------------------------------------------
# EXPERIENCE GUARDRAILS
# ---------------------------------------------------------------------------
# If a job description mentions more years of experience than the limit for
# your proficiency level, the listing is dropped immediately.
MAX_YEARS_EXPERIENCE_BY_LEVEL = {
    "Intern": 0,
    "Entry-Level": 1,
    "Junior": 2,      # e.g. "3+ years required" → automatically excluded
    "Mid-Level": 4,
}

# Phrase-level exclusions — if any of these appear in the title or description,
# the listing is dropped before scoring even runs
SENIOR_EXCLUSION_PHRASES = [
    "senior engineer",
    "senior developer",
    "staff engineer",
    "principal engineer",
    "lead engineer",
    "director",
    "10+ years",
    "8+ years",
    "7+ years",
    "6+ years",
    "5+ years",
    "4+ years",
    "3+ years",
]

# ---------------------------------------------------------------------------
# POSTING FRESHNESS
# ---------------------------------------------------------------------------
# Listings older than this many days are automatically filtered out.
# Set to 30 for a broad window, 7 for only the freshest roles.
# Set to 0 or None to disable date filtering entirely.
MAX_POSTING_AGE_DAYS = 30

# ---------------------------------------------------------------------------
# SCORING TUNING
# ---------------------------------------------------------------------------
# Only listings that hit this score (0–100) make it into the .docx output
MIN_MATCH_SCORE = 60

# Minimum percentage match required for skills and title relevance individually (60-70%)
# Both must meet their respective threshold to be considered a match.
MIN_SKILLS_MATCH_PCT = 60
MIN_TITLE_MATCH_PCT = 60

# How many of your target skills need to appear in a description to count as
# "full credit" for the skills component. Keeping this at 4 means a listing
# doesn't need to mention every single skill in your stack to score well.
SKILL_MATCH_TARGET = 4

# Weight distribution across the three scoring components (must total 1.0)
SCORE_WEIGHTS = {
    "skills": 0.50,          # Skills overlap
    "title_relevance": 0.35, # Title match relevance
    "job_type_match": 0.15,  # Job type arrangement match
}

# ---------------------------------------------------------------------------
# OPTIONAL: ADZUNA AGGREGATOR CREDENTIALS
# ---------------------------------------------------------------------------
ADZUNA_APP_ID = ""
ADZUNA_APP_KEY = ""
ADZUNA_COUNTRY_CODE = "us"

# ---------------------------------------------------------------------------
# OUTPUT
# ---------------------------------------------------------------------------
OUTPUT_DOCX_PATH = "jobctl_matched_jobs.docx"
RESULTS_PER_SOURCE = 30
