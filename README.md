<div align="center">

<img src="assets/logo.png" alt="jobctl — Automated Engineering Job Control Plane" width="140" />

# jobctl

**Control-plane CLI & Docker Daemon for your engineering job search. Aggregate, filter, score, and receive daily Telegram alerts for fresh remote roles across 14 ATS & job APIs.**

`jobctl` is a modular Python CLI engineered for **Mid-Level Software Engineers, DevOps Engineers, PostgreSQL / Database Engineers, and Scalable ERP Developers**. It queries **14 job portals concurrently**, enforces a strict **previous 2-day freshness window**, applies word-boundary + alias skill matching, tracks seen listings in SQLite, exports multi-format reports into `search_results/<YYYY-MM-DD>/`, and sends formatted job links straight to your **Telegram** every day at **11:00 AM** (or any schedule you set via environment variables).

![Python 3.11+](https://img.shields.io/badge/python-3.11%2B-0D9488.svg)
![License: MIT](https://img.shields.io/badge/License-MIT-15803D.svg)
![Level: Mid-Level 2-5 Yrs](https://img.shields.io/badge/Level-Mid%20(2--5%20yrs)-0F172A.svg)
![Freshness: Last 2 Days](https://img.shields.io/badge/Freshness-Last%202%20Days-2563EB.svg)
![Sources: 14 Public APIs](https://img.shields.io/badge/Sources-14%20Public%20APIs-7C3AED.svg)

</div>

---

## Why `jobctl`?

Job boards are flooded with stale 30-day-old ghost listings, senior/staff roles masquerading under generic searches, and naive keyword filters that match `git` inside *"digital"* or label *"international team"* as an internship.

`jobctl` treats job hunting like an engineering pipeline:

1. **Strict 2-Day Freshness (`max_posting_age_days = 2`):** Queries portals with 48-hour filters (`f_TPR=r172800` on LinkedIn, `max_days_old=2` on Adzuna) and drops any listing older than the previous two calendar dates.
2. **14 Concurrent Public APIs:** Queries LinkedIn, Greenhouse, Ashby, Lever, Wellfound, Remotive, RemoteOK, WeWorkRemotely, Hacker News ("Who's Hiring"), SmartRecruiters, Recruitee, Workable, BDJobs, and Adzuna in parallel using a resilient HTTP session with automatic backoff retries on `429` / `5xx`.
3. **Word-Boundary + Alias Skill Engine:** Matches whole terms with built-in synonym expansion (`postgres` / `psql` → `postgresql`, `k8s` / `helm` → `kubernetes`, `node` → `node.js`, `odoo` / `sap` → `erp`) while preventing substring false positives.
4. **Level-Aware Guardrails:** Configured out-of-the-box for **Mid-Level (2–5 years)**—accepting roles requiring up to 5 years while automatically filtering out Senior, Staff, Principal, Lead, Director, and Intern roles.
5. **SQLite Deduplication Across Runs:** Persists every match in `data/jobctl.db` so daily runs highlight `[NEW]` opportunities without repeating yesterday's list.
6. **Scheduled Docker Daemon + Telegram Alerts:** Run `docker compose up -d` once—`jobctl daemon` wakes up every day at `11:00 AM` (configurable day & time via `.env`), saves dated reports to `search_results/<YYYY-MM-DD>/`, and sends formatted clickable job links to your Telegram chat.

---

## Supported Portals (14 Sources)

| # | Source | Public API / Access Method | Auth Required? | Focus Area |
| :-: | :--- | :--- | :---: | :--- |
| 1 | **LinkedIn** | Guest Search (`f_WT=2`, `f_E=2,3,4`, `f_TPR=r172800`) | No | Global remote Software, Backend, DevOps & PostgreSQL roles posted in last 48h |
| 2 | **Greenhouse** | Official Public REST API (`boards-api.greenhouse.io`) | No | Cloud, DevOps & Data leaders (GitLab, Cloudflare, Datadog, HashiCorp, Cockroach Labs, Grafana Labs, Timescale, Vercel) |
| 3 | **Ashby** | Official Public REST API (`api.ashbyhq.com`) | No | Modern infra & Postgres platforms (Supabase, Neon, Railway, Render, Linear, Sentry, PostHog, OpenAI) |
| 4 | **Lever** | Official Public REST API (`api.lever.co`) | No | Scaling engineering orgs (Spotify, Postman, Atlassian, Auth0, Palantir, Zapier) |
| 5 | **Wellfound** | Next.js Apollo Graph Feed + JSON-LD | No | Remote-first Seed to Series C startups |
| 6 | **Remotive** | Official Public JSON API (`remotive.com/api/remote-jobs`) | No | Dedicated remote Software Dev & DevOps roles |
| 7 | **RemoteOK** | Official Public JSON Feed (`remoteok.com/api`) | No | Worldwide remote engineering listings |
| 8 | **WeWorkRemotely** | Official Public RSS Feeds (`weworkremotely.com/*.rss`) | No | Remote Back-End, Full-Stack & DevOps/Sysadmin boards |
| 9 | **Hacker News** | Official Algolia JSON API (`hn.algolia.com/api/v1`) | No | Latest monthly *"Ask HN: Who is hiring?"* comments posted in last 2 days |
| 10 | **SmartRecruiters** | Official Public Posting API (`api.smartrecruiters.com`) | No | Global tech & cloud companies (Aiven, Block, Square, Visa, Equinix, Wolt) |
| 11 | **Recruitee** | Official Public Careers API (`*.recruitee.com/api/offers`) | No | Remote-friendly SaaS & product orgs (Baserow, Hotjar, Mollie, Framer) |
| 12 | **Workable** | Public Widget JSON API (`apply.workable.com/api/v1/widget`) | No | Open-source & database companies (Percona, Canonical, Netdata, Mattermost) |
| 13 | **BDJobs** | Public Web Search JSON Endpoint (`api.bdjobs.com`) | No | Bangladesh software, DevOps & ERP listings |
| 14 | **Adzuna** | REST API (optional, via `.env`) | API Key | Global job aggregator (`max_days_old=2`) |

---

## Step-by-Step Guide: Telegram Setup & Running the Daily 11:00 AM Docker Daemon (`-d`)

All Telegram credentials and schedule settings are configured **exclusively via environment variables** (`.env`), so no API tokens or chat IDs are ever exposed in source code or commits. The bot sends **only formatted messages with clickable job links** (no file uploads).

### Step 1: Create Your Telegram Bot & Get `TELEGRAM_BOT_TOKEN`
1. Open Telegram (phone or desktop) and search for **[@BotFather](https://t.me/BotFather)** (verified blue checkmark).
2. Send `/newbot`.
3. Choose a display name (for example: `jobctl Daily Alerts`).
4. Choose a username ending in `bot` (for example: `arif_jobctl_bot`).
5. BotFather will reply with your HTTP API token (e.g. `7123456789:AAH_xyz...`). Copy it — this is your **`TELEGRAM_BOT_TOKEN`**.

### Step 2: Activate Your Bot & Get `TELEGRAM_CHAT_ID`
1. Click `t.me/<your_bot_username>` in BotFather's message, press **Start**, and send `hello`. *(Telegram bots cannot message you until you initiate a chat first.)*
2. Find your numeric **`TELEGRAM_CHAT_ID`** using either option:
   - **Option A (`@userinfobot`):** Message **[@userinfobot](https://t.me/userinfobot)** on Telegram and press **Start** — it replies with your `Id: 123456789`.
   - **Option B (`getUpdates` API):** Run:
     ```bash
     curl -s "https://api.telegram.org/bot<YOUR_BOT_TOKEN>/getUpdates"
     ```
     and copy the number from `"chat":{"id":123456789}`.

### Step 3: Configure `.env` (Git-Ignored)
Copy [`.env.example`](.env.example) to `.env`:
```bash
cp .env.example .env
```
Edit `.env` to set your token, chat ID, and desired schedule:
```dotenv
# --- Timezone & Daily/Weekday Schedule (Changeable anytime) ---
TZ=Asia/Dhaka
JOBCTL_SCHEDULE_TIME=11:00
# Options: "daily" (or "*"), "weekdays", "weekends", or comma-separated days: "sun,mon,tue,wed,thu"
JOBCTL_SCHEDULE_DAYS=daily
# Set to true if you also want an immediate run when the container starts
JOBCTL_RUN_ON_STARTUP=false

# --- Telegram Bot Credentials (Formatted messages & links only, no files sent) ---
TELEGRAM_ENABLED=true
TELEGRAM_BOT_TOKEN=7123456789:AAH_your_token_here
TELEGRAM_CHAT_ID=123456789
TELEGRAM_NOTIFY_ON_EMPTY=true
```

### Step 4: Test Your Telegram Notification Immediately
Verify that your bot sends a formatted test message to your Telegram chat:
```bash
jobctl notify-test
# Or via Docker:
docker compose run --rm jobctl notify-test
```

### Step 5: Start the Background Docker Container (`-d`)
- **Using Docker Compose (Recommended):**
  ```bash
  docker compose up -d --build
  ```
- **Or using `docker run -d`:**
  ```bash
  docker build -t jobctl:latest .
  docker run -d \
    --name jobctl-daemon \
    --restart unless-stopped \
    --env-file .env \
    -v "$(pwd)/search_results:/app/search_results" \
    -v "$(pwd)/data:/app/data" \
    jobctl:latest daemon
  ```
- **Inspect live daemon schedule & logs:**
  ```bash
  docker logs -f jobctl-daemon
  ```
- **Change the day or time anytime:**
  Update `JOBCTL_SCHEDULE_TIME` (e.g. `09:30`) or `JOBCTL_SCHEDULE_DAYS` (e.g. `sun,mon,tue,wed,thu`) in `.env`, then run `docker compose up -d`.

---

## Local Quick Start

```bash
python3 -m venv .venv
source .venv/bin/activate
pip install -e .

# Optional: initialize your personal jobctl.toml from the template
jobctl init

# Run a one-shot search (automatically sends Telegram links if TELEGRAM_BOT_TOKEN is set in .env)
jobctl run
```

### CLI Commands

```bash
jobctl run                              # Run full search (last 2 days) & write to search_results/<YYYY-MM-DD>/
jobctl run --notify                     # Force sending Telegram message digest after the run
jobctl run --no-notify                  # Run locally without sending a Telegram alert
jobctl run --dry-run -v                 # Test fetch & scoring in terminal without writing files
jobctl run --sources remotive,remoteok  # Query specific sources only
jobctl daemon                           # Start the continuous daily/weekday background scheduler
jobctl daemon --time 11:00 --schedule-days sun,mon,tue,wed,thu
jobctl notify-test                      # Send a test message to your Telegram chat
jobctl sources                          # List all 14 registered sources, status, and limits
jobctl history --limit 25               # View recently discovered jobs from SQLite history
jobctl init                             # Copy jobctl.example.toml -> jobctl.toml
```

---

## Dated Output Folder Structure (`search_results/`)

Every execution creates a dated subfolder for today's date (`YYYY-MM-DD`) inside `search_results/` and timestamps each run (`HHMMSS`) so multiple runs on the same day never overwrite each other:

```text
search_results/
└── 2026-11-22/
    ├── jobctl_110000.docx     # Formatted Word report with clickable Apply hyperlinks
    ├── jobctl_110000.csv      # Spreadsheet-ready tabular export
    ├── jobctl_110000.json     # Structured JSON payload for automation
    ├── jobctl_110000.md       # Markdown digest table
    └── run_110000.log         # Full telemetry log, rejection breakdown & near-misses
```

---

## License

MIT — see [LICENSE](LICENSE).
