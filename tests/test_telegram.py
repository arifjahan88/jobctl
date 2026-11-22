"""Unit tests for the message-only Telegram Bot notifier (`src/jobctl/notifiers/telegram.py`)."""

from __future__ import annotations

from datetime import datetime
from pathlib import Path
import unittest
from unittest.mock import MagicMock

from jobctl.config import AppConfig
from jobctl.models import Job, ScoreBreakdown, ScoredJob
from jobctl.notifiers.telegram import (
    TelegramConfig,
    format_telegram_messages,
    send_telegram_report,
    send_telegram_test_message,
)


def _sample_scored_job(idx: int = 1) -> ScoredJob:
    base_job = Job(
        title=f"Backend Engineer #{idx}",
        company="Supabase",
        location="Remote",
        job_type="full-time",
        work_mode="remote",
        description="Build scalable PostgreSQL and TypeScript microservices.",
        url=f"https://jobs.ashbyhq.com/supabase/{idx}",
        source="Ashby (supabase)",
        posted_date="2026-11-22T09:00:00Z",
    )
    return ScoredJob(
        job=base_job,
        match_score=88,
        match_summary="Skills 100%, Title 85%, JobType 100%",
        matched_skills=["postgresql", "typescript", "node.js", "docker", "kubernetes"],
        score_breakdown=ScoreBreakdown(skills_pct=100, title_pct=85, job_type_pct=100),
        is_new=True,
    )


def test_format_telegram_messages_contains_clickable_links_and_no_files() -> None:
    cfg = AppConfig()
    jobs = [_sample_scored_job(1), _sample_scored_job(2)]
    messages = format_telegram_messages(
        jobs=jobs,
        config=cfg,
        run_date_dir=Path("search_results/2026-11-22"),
        now=datetime(2026, 11, 22, 11, 0),
    )
    assert len(messages) == 1
    msg = messages[0]
    assert "jobctl Daily Job Report" in msg
    assert "Previous 2 days (2026-11-20 to 2026-11-22)" in msg
    assert 'href="https://jobs.ashbyhq.com/supabase/1"' in msg
    assert "Backend Engineer #1" in msg
    assert "[88/100]" in msg
    assert "Skills:" not in msg
    assert "Open Job Posting" not in msg


def test_format_telegram_messages_chunks_long_reports() -> None:
    cfg = AppConfig()
    jobs = [_sample_scored_job(i) for i in range(1, 15)]
    messages = format_telegram_messages(
        jobs=jobs,
        config=cfg,
        now=datetime(2026, 11, 22, 11, 0),
        max_len=900,
    )
    assert len(messages) > 1
    assert "continued" in messages[1]


def test_send_telegram_report_posts_message_only() -> None:
    cfg = AppConfig()
    tg = TelegramConfig(
        enabled=True,
        bot_token="123456:TEST_TOKEN",
        chat_id="987654321",
        notify_on_empty=True,
    )
    mock_session = MagicMock()
    mock_response = MagicMock()
    mock_response.status_code = 200
    mock_session.post.return_value = mock_response

    ok = send_telegram_report(
        jobs=[_sample_scored_job(1)],
        config=cfg,
        tg_config=tg,
        session=mock_session,
    )
    assert ok is True
    assert mock_session.post.call_count == 1
    call_args = mock_session.post.call_args
    assert "https://api.telegram.org/bot123456:TEST_TOKEN/sendMessage" in call_args[0][0]
    payload = call_args[1]["json"]
    assert payload["chat_id"] == "987654321"
    assert payload["parse_mode"] == "HTML"
    assert "https://jobs.ashbyhq.com/supabase/1" in payload["text"]


def test_send_telegram_test_message() -> None:
    tg = TelegramConfig(
        enabled=True,
        bot_token="123456:TEST_TOKEN",
        chat_id="987654321",
    )
    mock_session = MagicMock()
    mock_response = MagicMock()
    mock_response.status_code = 200
    mock_session.post.return_value = mock_response

    ok, err = send_telegram_test_message(tg_config=tg, session=mock_session)
    assert ok is True
    assert err == ""


def test_format_telegram_messages_skipped_seen_hint() -> None:
    cfg = AppConfig()
    messages = format_telegram_messages(
        jobs=[],
        config=cfg,
        now=datetime(2026, 11, 22, 11, 0),
        skipped_seen_count=7,
    )
    assert len(messages) == 1
    assert "7 match(es) were already seen" in messages[0]
    assert "jobctl history --clear" in messages[0]


class TestTelegramNotifier(unittest.TestCase):
    def test_all(self) -> None:
        test_format_telegram_messages_contains_clickable_links_and_no_files()
        test_format_telegram_messages_chunks_long_reports()
        test_send_telegram_report_posts_message_only()
        test_send_telegram_test_message()
        test_format_telegram_messages_skipped_seen_hint()
