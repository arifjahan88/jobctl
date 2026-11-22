"""Telegram Bot message-only notifier configured strictly via environment variables."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
import html
import logging
import os
from pathlib import Path

import requests

from jobctl.config import AppConfig
from jobctl.models import ScoredJob

TELEGRAM_MAX_MESSAGE_LEN = 3900


@dataclass(slots=True)
class TelegramConfig:
    enabled: bool = False
    bot_token: str = ""
    chat_id: str = ""
    notify_on_empty: bool = True

    @property
    def is_configured(self) -> bool:
        return bool(self.bot_token.strip() and self.chat_id.strip())


def load_dotenv_into_environ(dotenv_path: str | Path = ".env") -> None:
    """
    Lightweight stdlib loader for `.env` when running outside Docker.
    Existing environment variables always take precedence.
    """
    path = Path(dotenv_path)
    if not path.is_file():
        return
    try:
        for raw_line in path.read_text(encoding="utf-8").splitlines():
            line = raw_line.strip()
            if not line or line.startswith("#") or "=" not in line:
                continue
            key, val = line.split("=", 1)
            key = key.strip()
            val = val.strip().strip("'").strip('"')
            if key and key not in os.environ:
                os.environ[key] = val
    except Exception:
        pass


def _parse_bool_env(name: str, default: bool) -> bool:
    raw = os.environ.get(name)
    if raw is None or not raw.strip():
        return default
    return raw.strip().lower() in ("1", "true", "yes", "on")


def load_telegram_config_from_env(dotenv_path: str | Path = ".env") -> TelegramConfig:
    """
    Load Telegram credentials strictly from environment variables
    (with `.env` fallback for local CLI calls).
    """
    load_dotenv_into_environ(dotenv_path)
    token = os.environ.get("TELEGRAM_BOT_TOKEN", "").strip()
    chat_id = os.environ.get("TELEGRAM_CHAT_ID", "").strip()
    has_creds = bool(token and chat_id)
    enabled = _parse_bool_env("TELEGRAM_ENABLED", default=has_creds)
    notify_on_empty = _parse_bool_env("TELEGRAM_NOTIFY_ON_EMPTY", default=True)
    return TelegramConfig(
        enabled=enabled,
        bot_token=token,
        chat_id=chat_id,
        notify_on_empty=notify_on_empty,
    )


def _format_single_job_block(index: int, job: ScoredJob) -> str:
    """Format one matched job entry in clean Telegram HTML with a clickable Apply link."""
    title_esc = html.escape(job.title)
    company_esc = html.escape(job.company)
    source_esc = html.escape(job.source)
    mode_esc = html.escape(job.work_mode)
    jtype_esc = html.escape(job.job_type)
    date_tag = html.escape(job.posted_date[:10] if job.posted_date else "Recent")

    skills_preview = ", ".join(job.matched_skills[:7]) if job.matched_skills else "general match"
    if len(job.matched_skills) > 7:
        skills_preview += f" (+{len(job.matched_skills) - 7} more)"
    skills_esc = html.escape(skills_preview)

    url_clean = (job.url or "").strip()
    if url_clean.startswith(("http://", "https://")):
        url_attr = html.escape(url_clean, quote=True)
        title_line = f"{index}. <b>[{job.match_score}/100]</b> <a href=\"{url_attr}\">{title_esc}</a> — <b>{company_esc}</b>"
        link_line = f"   🔗 <a href=\"{url_attr}\">Open Job Posting</a>"
    else:
        title_line = f"{index}. <b>[{job.match_score}/100]</b> {title_esc} — <b>{company_esc}</b>"
        link_line = "   🔗 Link unavailable"

    return (
        f"{title_line}\n"
        f"   📅 {date_tag} · 🌍 {mode_esc} ({jtype_esc}) · <i>{source_esc}</i>\n"
        f"   🛠 Skills: <code>{skills_esc}</code>\n"
        f"{link_line}"
    )


def format_telegram_messages(
    jobs: list[ScoredJob],
    config: AppConfig,
    run_date_dir: Path | None = None,
    now: datetime | None = None,
    max_len: int = TELEGRAM_MAX_MESSAGE_LEN,
) -> list[str]:
    """
    Build one or more HTML-formatted Telegram messages containing all matched job links.
    Never attaches or uploads files; splits cleanly if total text exceeds Telegram's 4096-char limit.
    """
    current = now or datetime.now()
    date_str = current.strftime("%Y-%m-%d %H:%M")
    role_esc = html.escape(config.profile.role_title)
    level_esc = html.escape(config.profile.preset.label)
    modes_esc = html.escape(", ".join(m.title() for m in config.profile.work_modes))
    folder_str = html.escape(str(run_date_dir)) if run_date_dir else f"search_results/{current.strftime('%Y-%m-%d')}"

    header = (
        f"🚀 <b>jobctl Daily Job Report — {date_str}</b>\n"
        f"👤 <b>Profile:</b> {role_esc} ({level_esc} · {modes_esc})\n"
        f"⏱ <b>Window:</b> Previous {config.filters.max_posting_age_days} days\n"
        f"📂 <b>Saved to:</b> <code>{folder_str}</code>\n"
        f"✅ <b>New Matches:</b> {len(jobs)}\n"
    )

    if not jobs:
        empty_msg = (
            f"{header}\n"
            f"<i>No new matching jobs met your score threshold ({config.scoring.min_score}/100) "
            f"in the last {config.filters.max_posting_age_days} days.</i>"
        )
        return [empty_msg]

    messages: list[str] = []
    current_chunks: list[str] = [header]
    current_len = len(header)

    for idx, job in enumerate(jobs, start=1):
        block = _format_single_job_block(idx, job)
        addition_len = len(block) + 2  # account for "\n\n"
        if current_len + addition_len > max_len and len(current_chunks) > 1:
            messages.append("\n\n".join(current_chunks))
            cont_header = f"🚀 <b>jobctl Report (continued — part {len(messages) + 1})</b>"
            current_chunks = [cont_header, block]
            current_len = len(cont_header) + addition_len
        else:
            current_chunks.append(block)
            current_len += addition_len

    if current_chunks:
        messages.append("\n\n".join(current_chunks))

    return messages


def _post_telegram_message(
    bot_token: str,
    chat_id: str,
    html_text: str,
    session: requests.Session | None = None,
) -> tuple[bool, str]:
    """Send a single HTML message via the Telegram Bot API `sendMessage` endpoint."""
    url = f"https://api.telegram.org/bot{bot_token}/sendMessage"
    http = session or requests.Session()
    payload = {
        "chat_id": chat_id,
        "text": html_text,
        "parse_mode": "HTML",
        "disable_web_page_preview": True,
    }
    try:
        res = http.post(url, json=payload, timeout=12)
        if res.status_code == 200:
            return True, ""
        return False, f"HTTP {res.status_code}: {res.text[:200]}"
    except Exception as exc:
        return False, str(exc)


def send_telegram_report(
    jobs: list[ScoredJob],
    config: AppConfig,
    tg_config: TelegramConfig | None = None,
    run_date_dir: Path | None = None,
    now: datetime | None = None,
    session: requests.Session | None = None,
) -> bool:
    """
    Send formatted job match messages (with clickable links, no files) to Telegram.
    Returns True if all messages succeeded (or if notification was intentionally skipped).
    """
    logger = logging.getLogger("jobctl")
    tg = tg_config or load_telegram_config_from_env()

    if not tg.enabled:
        return True

    if not tg.is_configured:
        logger.warning(
            "Telegram notifications enabled but TELEGRAM_BOT_TOKEN or TELEGRAM_CHAT_ID is missing."
        )
        return False

    if not jobs and not tg.notify_on_empty:
        logger.info("No new jobs matched and TELEGRAM_NOTIFY_ON_EMPTY=false; skipping Telegram alert.")
        return True

    messages = format_telegram_messages(
        jobs=jobs,
        config=config,
        run_date_dir=run_date_dir,
        now=now,
    )

    all_ok = True
    for idx, msg in enumerate(messages, start=1):
        ok, err = _post_telegram_message(
            bot_token=tg.bot_token,
            chat_id=tg.chat_id,
            html_text=msg,
            session=session,
        )
        if not ok:
            logger.error(f"Telegram message part {idx}/{len(messages)} failed: {err}")
            all_ok = False

    if all_ok:
        logger.info(
            f"Telegram notification sent ({len(messages)} message(s), {len(jobs)} job link(s))."
        )
    return all_ok


def send_telegram_test_message(
    tg_config: TelegramConfig | None = None,
    session: requests.Session | None = None,
) -> tuple[bool, str]:
    """Send a diagnostic message to verify TELEGRAM_BOT_TOKEN and TELEGRAM_CHAT_ID."""
    tg = tg_config or load_telegram_config_from_env()
    if not tg.is_configured:
        return (
            False,
            "TELEGRAM_BOT_TOKEN and/or TELEGRAM_CHAT_ID environment variables are not set.",
        )

    schedule_time = os.environ.get("JOBCTL_SCHEDULE_TIME", "11:00")
    schedule_days = os.environ.get("JOBCTL_SCHEDULE_DAYS", "daily")
    tz_name = os.environ.get("TZ", "Asia/Dhaka")

    test_html = (
        "✅ <b>jobctl Telegram Bot Connected!</b>\n\n"
        f"• <b>Schedule:</b> <code>{html.escape(schedule_days)}</code> at "
        f"<code>{html.escape(schedule_time)}</code> ({html.escape(tz_name)})\n"
        "• <b>Delivery Mode:</b> Formatted messages &amp; job links only (no file uploads)\n"
        "• <b>Link Preview Test:</b> <a href=\"https://news.ycombinator.com/jobs\">Sample Job Link</a>"
    )
    return _post_telegram_message(
        bot_token=tg.bot_token,
        chat_id=tg.chat_id,
        html_text=test_html,
        session=session,
    )
