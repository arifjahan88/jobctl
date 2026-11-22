# Changelog

All notable changes to **jobctl** are documented in this file.

## [2.0.0] - 2026-11-22

### Added
- Rebranded the project to **jobctl** with a new CLI-first package layout (`src/jobctl/`) and custom logo (`assets/logo.png`).
- Added `jobctl` CLI with `run`, `sources`, `history`, and `init` subcommands.
- Added TOML configuration (`jobctl.example.toml` / `jobctl.toml`) with built-in experience level presets (`intern`, `entry`, `junior`, `mid`, `senior`).
- Updated default profile to **Mid-Level Software Engineer (2–5 years)** with **DevOps, PostgreSQL, and Scalable ERP** skills and target titles.
- Enforced strict **2-day posting freshness** (`max_posting_age_days = 2`, `require_posted_date = true`) across all adapters and hard filters, including source-side time window parameters (`f_TPR=r172800` on LinkedIn, `max_days_old=2` on Adzuna).
- Added dated results directory structure: every run saves `.docx`, `.csv`, `.json`, `.md`, and `run_<HHMMSS>.log` files inside `search_results/<YYYY-MM-DD>/`.
- Added SQLite job history (`data/jobctl.db`) to track seen vs. new matches across runs.
- Added multi-stage `Dockerfile`, `.dockerignore`, `Makefile`, `.env.example`, and comprehensive offline unit test suite.

### Fixed
- Fixed substring false positives in skill matching (`git` in "digital", `react` in "reactive", `express` in "expression", `sql` in "postgresql") using word-boundary regexes and a canonical alias map.
- Fixed false internship classification when descriptions mention "international" or "internal".
- Fixed experience range parsing (`"2-4 years"`) to use the minimum qualifying bound (`2`) instead of the upper bound (`4`).
- Replaced sequential portal queries with true concurrent execution across all enabled sources.
