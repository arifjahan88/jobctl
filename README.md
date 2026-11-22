<div align="center">

<img src="assets/logo.png" alt="jobctl — Automated Engineering Job Control Plane" width="140" />

# jobctl

**Control-plane CLI for your engineering job search. Aggregate, filter, and score fresh remote roles directly from ATS APIs.**

`jobctl` is a modular Python CLI engineered for **Mid-Level Software Engineers, DevOps Engineers, PostgreSQL / Database Engineers, and Scalable ERP Developers**. It queries LinkedIn, Wellfound, Greenhouse, Lever, and Ashby concurrently, enforces a strict **previous 2-day freshness window**, applies word-boundary + alias skill matching, tracks seen listings in SQLite, and exports multi-format reports into `search_results/<YYYY-MM-DD>/`.

![Python 3.11+](https://img.shields.io/badge/python-3.11%2B-0D9488.svg)
![License: MIT](https://img.shields.io/badge/License-MIT-15803D.svg)
![Level: Mid-Level 2-5 Yrs](https://img.shields.io/badge/Level-Mid%20(2--5%20yrs)-0F172A.svg)
![Freshness: Last 2 Days](https://img.shields.io/badge/Freshness-Last%202%20Days-2563EB.svg)

</div>

---

## Why `jobctl`?

Job boards are flooded with stale 30-day-old ghost listings, senior/staff roles masquerading under generic searches, and naive keyword filters that match `git` inside *"digital"* or label *"international team"* as an internship.

`jobctl` treats job hunting like an engineering pipeline:

1. **Strict 2-Day Freshness (`max_posting_age_days = 2`):** Queries portals with 48-hour filters (`f_TPR=r172800` on LinkedIn, `max_days_old=2` on Adzuna) and drops any listing older than the previous two calendar dates.
2. **True Concurrent Fetching:** Queries LinkedIn, Wellfound, Ashby, Greenhouse, and Lever in parallel using a resilient HTTP session with automatic backoff retries on `429` / `5xx`.
3. **Word-Boundary + Alias Skill Engine:** Matches whole terms with built-in synonym expansion (`postgres` / `psql` → `postgresql`, `k8s` / `helm` → `kubernetes`, `node` → `node.js`, `odoo` / `sap` → `erp`) while preventing substring false positives.
4. **Level-Aware Guardrails:** Configured out-of-the-box for **Mid-Level (2–5 years)**—accepting roles requiring up to 5 years while automatically filtering out Senior, Staff, Principal, Lead, Director, and Intern roles.
5. **SQLite Deduplication Across Runs:** Persists every match in `data/jobctl.db` so daily runs highlight `[NEW]` opportunities without repeating yesterday's list.
6. **Dated Multi-Format Output:** Every run creates `search_results/<YYYY-MM-DD>/` containing `.docx` (with clickable Apply links), `.csv`, `.json`, `.md`, and a detailed `run_<HHMMSS>.log`.

---

## Supported Portals

| Source | Access Method | Focus Area |
| :--- | :--- | :--- |
| **LinkedIn** | Guest Search (`f_WT=2`, `f_E=2,3,4`, `f_TPR=r172800`) | Global remote Software, Backend, DevOps & PostgreSQL roles posted in last 48h |
| **Greenhouse** | Official Public REST API | Cloud, DevOps & Data leaders (GitLab, Cloudflare, Datadog, HashiCorp, Cockroach Labs, Grafana Labs, Timescale, Vercel) |
| **Ashby** | Official Public REST API | Modern infra & Postgres platforms (Supabase, Neon, Railway, Render, Linear, Sentry, PostHog, OpenAI) |
| **Lever** | Official Public REST API | Scaling engineering orgs (Spotify, Postman, Atlassian, Auth0, Palantir, Zapier) |
| **Wellfound** | Next.js Apollo Graph Feed + JSON-LD | Remote-first Seed to Series C startups |
| **Adzuna** | REST API (optional, via `.env`) | Global job aggregator (`max_days_old=2`) |

---

## Quick Start

```bash
python3 -m venv .venv
source .venv/bin/activate
pip install -e .

# Optional: initialize your personal jobctl.toml from the template
jobctl init

# Run the full pipeline
jobctl run
```

Or run directly as a module without installing console scripts:

```bash
python -m jobctl run
```

### CLI Commands

```bash
jobctl run                              # Run full search (last 2 days) & write to search_results/<YYYY-MM-DD>/
jobctl run --dry-run -v                 # Test fetch & scoring in terminal without writing files
jobctl run --sources greenhouse,ashby   # Query specific sources only
jobctl run --days 2 --min-score 65      # Override freshness window or minimum match score
jobctl run --all                        # Export both NEW and previously SEEN matches
jobctl sources                          # List all registered sources, status, and limits
jobctl history --limit 25               # View recently discovered jobs from SQLite history
jobctl init                             # Copy jobctl.example.toml -> jobctl.toml
```

---

## Dated Output Folder Structure (`search_results/`)

Every execution creates a dated subfolder for today's date (`YYYY-MM-DD`) inside `search_results/` and timestamps each run (`HHMMSS`) so multiple runs on the same day never overwrite each other:

```text
search_results/
└── 2026-11-22/
    ├── jobctl_112045.docx     # Formatted Word report with clickable Apply hyperlinks
    ├── jobctl_112045.csv      # Spreadsheet-ready tabular export
    ├── jobctl_112045.json     # Structured JSON payload for automation
    ├── jobctl_112045.md       # Markdown digest table
    └── run_112045.log         # Full telemetry log, rejection breakdown & near-misses
```

---

## Configuration (`jobctl.toml`)

All settings live in `jobctl.toml` (generated from [`jobctl.example.toml`](jobctl.example.toml)):

```toml
[profile]
role_title = "Software Engineer"
level = "mid"                      # intern | entry | junior | mid | senior
work_modes = ["remote"]
job_types = ["full-time", "contract"]
location = "Worldwide"

skills = [
    "typescript", "javascript", "node.js", "nestjs", "express",
    "react", "next.js", "postgresql", "sql", "redis",
    "docker", "kubernetes", "ci/cd", "github actions", "aws",
    "linux", "terraform", "nginx", "microservices", "rest api", "erp",
]

[filters]
max_posting_age_days = 2           # Strictly only jobs from the previous 2 dates
require_posted_date = true         # Drop listings without a verifiable timestamp

[scoring]
min_score = 60
min_skills_pct = 50
min_title_pct = 50
skill_match_target = 5
weights = { skills = 0.55, title = 0.35, job_type = 0.10 }

[output]
results_dir = "search_results"
formats = ["docx", "csv", "json", "md"]
only_new = true
history_db = "data/jobctl.db"
```

### Built-in Level Presets

| Level Key | Experience Range | Max Years Allowed | LinkedIn `f_E` | Title Exclusions |
| :--- | :--- | :---: | :---: | :--- |
| `intern` | 0 yrs | `0` | `1` | Senior, Staff, Principal, Lead, Manager, Mid, Junior |
| `entry` | 0–1 yr | `1` | `1,2` | Senior, Staff, Principal, Lead, Manager, II, III |
| `junior` | 0–2 yrs | `2` | `1,2` | Senior, Staff, Principal, Lead, Manager, III |
| **`mid`** | **2–5 yrs** | **`5`** | **`2,3,4`** | **Senior, Sr, Staff, Principal, Lead, Manager, Director, VP, Intern** |
| `senior` | 5–10 yrs | `10` | `4` | Principal, Director, VP, Head, Chief, Intern |

---

## Running with Docker

```bash
# Build the image
docker build -t jobctl:latest .

# Run and mount search_results/ and data/ to your host machine
docker run --rm \
  -v "$(pwd)/search_results:/app/search_results" \
  -v "$(pwd)/data:/app/data" \
  jobctl:latest run
```

---

## Project Architecture

```text
jobctl/
├── pyproject.toml                 # Package metadata, dependencies & console entry point
├── jobctl.example.toml            # Documented TOML configuration template
├── Dockerfile                     # Non-root Python 3.12 container image
├── Makefile                       # Developer shortcuts (install, test, lint, run, docker)
├── assets/
│   └── logo.png                   # jobctl brand icon
├── search_results/                # Auto-created dated output folders (<YYYY-MM-DD>/)
├── data/                          # SQLite job history database (jobctl.db)
├── src/jobctl/
│   ├── cli.py                     # CLI argument parser & subcommands
│   ├── config.py                  # Typed dataclasses, TOML loader & level presets
│   ├── models.py                  # Job, ScoredJob, ScoreBreakdown & SourceStat models
│   ├── pipeline.py                # Concurrent source execution & export orchestration
│   ├── log.py                     # Console & per-run file logging
│   ├── matching/
│   │   ├── text.py                # Word-boundary skill regexes, aliases & years parser
│   │   ├── filters.py             # Strict 2-day freshness & level-aware hard filters
│   │   └── scoring.py             # Weighted 0–100 scoring & URL deduplication
│   ├── sources/
│   │   ├── base.py                # JobSource ABC, @register_source & retry HTTP session
│   │   ├── common.py              # Shared HTML stripping, work-mode & job-type inference
│   │   ├── linkedin.py            # LinkedIn 48h remote guest search adapter
│   │   ├── greenhouse.py          # Greenhouse ATS adapter
│   │   ├── lever.py               # Lever ATS adapter
│   │   ├── ashby.py               # Ashby ATS adapter
│   │   ├── wellfound.py           # Wellfound startup jobs adapter
│   │   └── adzuna.py              # Optional Adzuna aggregator adapter
│   ├── storage/
│   │   └── history.py             # SQLite seen/new job tracker
│   └── exporters/
│       ├── paths.py               # search_results/<YYYY-MM-DD>/ path builder
│       ├── docx.py                # Branded Word exporter with clickable links
│       └── tabular.py             # CSV, JSON & Markdown exporters
└── tests/                         # Offline unit test suite
```

---

## License

MIT — see [LICENSE](LICENSE).
