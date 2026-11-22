"""SQLite persistence layer for job history (seen vs new matches)."""

from __future__ import annotations

from contextlib import closing
from datetime import datetime, timedelta, timezone
from pathlib import Path
import sqlite3

from jobctl.models import ScoredJob

SCHEMA_SQL = """
CREATE TABLE IF NOT EXISTS jobs (
    job_key     TEXT PRIMARY KEY,
    title       TEXT NOT NULL,
    company     TEXT NOT NULL,
    url         TEXT NOT NULL,
    source      TEXT NOT NULL,
    posted_date TEXT NOT NULL DEFAULT '',
    score       INTEGER NOT NULL,
    first_seen  TEXT NOT NULL,
    last_seen   TEXT NOT NULL,
    times_seen  INTEGER NOT NULL DEFAULT 1
);
CREATE INDEX IF NOT EXISTS idx_jobs_first_seen ON jobs(first_seen);
CREATE INDEX IF NOT EXISTS idx_jobs_score ON jobs(score DESC);
"""


class HistoryStore:
    """Manage the SQLite database that records every matched job across runs."""

    def __init__(self, db_path: str | Path = "data/jobctl.db") -> None:
        self.db_path = Path(db_path)
        self.db_path.parent.mkdir(parents=True, exist_ok=True)
        self._init_schema()

    def _connect(self) -> sqlite3.Connection:
        conn = sqlite3.connect(self.db_path)
        conn.row_factory = sqlite3.Row
        return conn

    def _init_schema(self) -> None:
        with closing(self._connect()) as conn:
            with conn:
                conn.executescript(SCHEMA_SQL)

    def record_jobs(
        self,
        scored_jobs: list[ScoredJob],
        now: datetime | None = None,
    ) -> list[ScoredJob]:
        """
        Upsert scored jobs into SQLite and annotate each ScoredJob with
        `is_new` (True on first sighting) and `times_seen`.
        """
        ts = (now or datetime.now(timezone.utc)).isoformat()
        with closing(self._connect()) as conn:
            with conn:
                for item in scored_jobs:
                    key = item.dedup_key
                    row = conn.execute(
                        "SELECT times_seen, first_seen FROM jobs WHERE job_key = ?",
                        (key,),
                    ).fetchone()

                    if row is None:
                        item.is_new = True
                        item.times_seen = 1
                        conn.execute(
                            """
                            INSERT INTO jobs (
                                job_key, title, company, url, source, posted_date,
                                score, first_seen, last_seen, times_seen
                            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, 1)
                            """,
                            (
                                key,
                                item.title,
                                item.company,
                                item.url,
                                item.source,
                                item.posted_date,
                                item.match_score,
                                ts,
                                ts,
                            ),
                        )
                    else:
                        new_count = int(row["times_seen"]) + 1
                        item.is_new = False
                        item.times_seen = new_count
                        conn.execute(
                            """
                            UPDATE jobs
                               SET score = ?,
                                   last_seen = ?,
                                   times_seen = ?
                             WHERE job_key = ?
                            """,
                            (item.match_score, ts, new_count, key),
                        )
        return scored_jobs

    def list_recent(self, limit: int = 25) -> list[dict]:
        """Return the most recently discovered jobs from the history database."""
        with closing(self._connect()) as conn:
            rows = conn.execute(
                """
                SELECT job_key, title, company, url, source, posted_date,
                       score, first_seen, last_seen, times_seen
                  FROM jobs
                 ORDER BY first_seen DESC, score DESC
                 LIMIT ?
                """,
                (limit,),
            ).fetchall()
        return [dict(r) for r in rows]

    def count(self) -> int:
        with closing(self._connect()) as conn:
            row = conn.execute("SELECT COUNT(*) AS cnt FROM jobs").fetchone()
        return int(row["cnt"]) if row else 0

    def clear(self) -> int:
        """Delete all tracked jobs from SQLite and reclaim disk space with VACUUM."""
        with closing(self._connect()) as conn:
            with conn:
                cur = conn.execute("DELETE FROM jobs")
                deleted = cur.rowcount if cur.rowcount is not None and cur.rowcount >= 0 else 0
            conn.execute("VACUUM")
        return deleted

    def clear_older_than(self, days: int, now: datetime | None = None) -> int:
        """Delete tracked jobs whose `last_seen` timestamp is older than `days` days."""
        if days < 0:
            raise ValueError("days must be >= 0")
        ref_now = now or datetime.now(timezone.utc)
        cutoff_iso = (ref_now - timedelta(days=days)).isoformat()
        with closing(self._connect()) as conn:
            with conn:
                cur = conn.execute("DELETE FROM jobs WHERE last_seen < ?", (cutoff_iso,))
                deleted = cur.rowcount if cur.rowcount is not None and cur.rowcount >= 0 else 0
        return deleted
