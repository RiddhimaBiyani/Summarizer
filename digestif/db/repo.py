"""Database repository for Digestif with WAL mode and sqlite-vec integration."""

import datetime
import json
import sqlite3
from pathlib import Path
from typing import Any

import sqlite_vec

from digestif.observability import logger
from digestif.settings import settings


class Repository:
    def __init__(self, db_path: Path | str | None = None):
        self._explicit_db_path = Path(db_path) if db_path is not None else None
        self._init_db()

    @property
    def db_path(self) -> Path:
        if self._explicit_db_path is not None:
            return self._explicit_db_path
        return settings.db_path

    def set_db_path(self, new_path: Path | str) -> None:
        """Switches database path dynamically and initializes schema."""
        self._explicit_db_path = Path(new_path)
        self._init_db()

    def get_connection(self) -> sqlite3.Connection:
        """Returns a configured SQLite connection with sqlite-vec and row_factory."""
        self.db_path.parent.mkdir(parents=True, exist_ok=True)
        conn = sqlite3.connect(
            str(self.db_path),
            timeout=30.0,
            check_same_thread=False,
            isolation_level=None,  # autocommit mode / explicit transaction management
        )
        conn.row_factory = sqlite3.Row
        conn.execute("PRAGMA foreign_keys = ON;")
        conn.execute("PRAGMA journal_mode = WAL;")
        conn.execute("PRAGMA synchronous = NORMAL;")
        conn.enable_load_extension(True)
        sqlite_vec.load(conn)
        return conn

    def _init_db(self) -> None:
        """Applies schema and initializes vector tables."""
        self.db_path.parent.mkdir(parents=True, exist_ok=True)
        schema_file = Path(__file__).parent / "schema.sql"
        schema_sql = schema_file.read_text(encoding="utf-8")
        conn = self.get_connection()

        try:
            with conn:
                conn.executescript(schema_sql)
                # Initialize vec0 table for fastembed / item embeddings
                conn.execute(
                    "CREATE VIRTUAL TABLE IF NOT EXISTS item_vec USING vec0(item_id INTEGER PRIMARY KEY, embedding FLOAT[384]);"
                )
                # Seed senders if table is empty
                count = conn.execute("SELECT count(*) as c FROM newsletter_senders").fetchone()["c"]
                if count == 0:
                    senders_cfg = settings.BASE_DIR / "config" / "senders.yaml"
                    if senders_cfg.exists():
                        import yaml

                        with open(senders_cfg, "r", encoding="utf-8") as f:
                            data = yaml.safe_load(f) or {}
                        for s in data.get("senders", []):
                            conn.execute(
                                """
                                INSERT OR IGNORE INTO newsletter_senders (address, name, shape, trust, auto_ingest)
                                VALUES (?, ?, ?, ?, ?)
                                """,
                                (
                                    s.get("address", "").lower(),
                                    s.get("name", ""),
                                    s.get("shape", "single_essay"),
                                    s.get("trust", 0.6),
                                    s.get("auto_ingest", 1),
                                ),
                            )
            logger.info("Database schema initialized", db_path=str(self.db_path))
        finally:
            conn.close()

    # --- Captures ---
    def insert_capture(self, channel: str, external_id: str, raw_json: str) -> int | None:
        """Idempotently insert a capture payload. Returns capture ID or None if already exists."""
        now = datetime.datetime.now(datetime.timezone.utc).isoformat()
        conn = self.get_connection()
        try:
            with conn:
                cursor = conn.execute(
                    """
                    INSERT INTO captures (channel, external_id, received_at, raw_json)
                    VALUES (?, ?, ?, ?)
                    ON CONFLICT(channel, external_id) DO NOTHING
                    RETURNING id
                    """,
                    (channel, str(external_id), now, raw_json),
                )
                row = cursor.fetchone()
                return row["id"] if row else None
        finally:
            conn.close()

    def get_capture(self, capture_id: int) -> dict[str, Any] | None:
        conn = self.get_connection()
        try:
            row = conn.execute("SELECT * FROM captures WHERE id = ?", (capture_id,)).fetchone()
            return dict(row) if row else None
        finally:
            conn.close()

    # --- Items ---
    def insert_item(
        self,
        source_type: str,
        capture_id: int | None = None,
        parent_item_id: int | None = None,
        url: str | None = None,
        canonical_url: str | None = None,
        url_hash: str | None = None,
        title: str | None = None,
        author: str | None = None,
        publisher: str | None = None,
        published_at: str | None = None,
        user_note: str | None = None,
        status: str = "received",
        word_count: int | None = None,
        media_seconds: int | None = None,
        original_minutes: float | None = None,
        language: str | None = None,
        pinned: int = 0,
    ) -> int:
        now = datetime.datetime.now(datetime.timezone.utc).isoformat()
        conn = self.get_connection()
        try:
            with conn:
                cursor = conn.execute(
                    """
                    INSERT INTO items (
                        capture_id, parent_item_id, source_type, url, canonical_url,
                        url_hash, title, author, publisher, published_at, user_note,
                        status, word_count, media_seconds, original_minutes, language,
                        pinned, created_at, updated_at
                    ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                    RETURNING id
                    """,
                    (
                        capture_id,
                        parent_item_id,
                        source_type,
                        url,
                        canonical_url,
                        url_hash,
                        title,
                        author,
                        publisher,
                        published_at,
                        user_note,
                        status,
                        word_count,
                        media_seconds,
                        original_minutes,
                        language,
                        pinned,
                        now,
                        now,
                    ),
                )
                return cursor.fetchone()["id"]
        finally:
            conn.close()

    def get_item(self, item_id: int) -> dict[str, Any] | None:
        conn = self.get_connection()
        try:
            row = conn.execute("SELECT * FROM items WHERE id = ?", (item_id,)).fetchone()
            return dict(row) if row else None
        finally:
            conn.close()

    def find_item_by_url_hash(self, url_hash: str, days: int = 30) -> dict[str, Any] | None:
        """Find an item saved with the same url_hash in the past N days."""
        cutoff = (
            datetime.datetime.now(datetime.timezone.utc) - datetime.timedelta(days=days)
        ).isoformat()
        conn = self.get_connection()
        try:
            row = conn.execute(
                "SELECT * FROM items WHERE url_hash = ? AND created_at >= ? ORDER BY id DESC LIMIT 1",
                (url_hash, cutoff),
            ).fetchone()
            return dict(row) if row else None
        finally:
            conn.close()

    def update_item_status(
        self, item_id: int, status: str, failure_reason: str | None = None
    ) -> None:
        now = datetime.datetime.now(datetime.timezone.utc).isoformat()
        conn = self.get_connection()
        try:
            with conn:
                conn.execute(
                    "UPDATE items SET status = ?, failure_reason = ?, updated_at = ? WHERE id = ?",
                    (status, failure_reason, now, item_id),
                )
        finally:
            conn.close()

    def update_item_metadata(self, item_id: int, **fields: Any) -> None:
        if not fields:
            return
        fields["updated_at"] = datetime.datetime.now(datetime.timezone.utc).isoformat()
        set_clauses = [f"{k} = ?" for k in fields.keys()]
        values = list(fields.values()) + [item_id]
        sql = f"UPDATE items SET {', '.join(set_clauses)} WHERE id = ?"
        conn = self.get_connection()
        try:
            with conn:
                conn.execute(sql, values)
        finally:
            conn.close()

    def save_item_content(
        self,
        item_id: int,
        text_md: str,
        transcript: str | None = None,
        ocr_text: str | None = None,
        media_json: str | None = None,
        extraction_method: str | None = None,
        extraction_meta: str | None = None,
    ) -> None:
        conn = self.get_connection()
        try:
            with conn:
                conn.execute(
                    """
                    INSERT INTO item_content (
                        item_id, text_md, transcript, ocr_text, media_json,
                        extraction_method, extraction_meta
                    ) VALUES (?, ?, ?, ?, ?, ?, ?)
                    ON CONFLICT(item_id) DO UPDATE SET
                        text_md = excluded.text_md,
                        transcript = excluded.transcript,
                        ocr_text = excluded.ocr_text,
                        media_json = excluded.media_json,
                        extraction_method = excluded.extraction_method,
                        extraction_meta = excluded.extraction_meta
                    """,
                    (
                        item_id,
                        text_md,
                        transcript,
                        ocr_text,
                        media_json,
                        extraction_method,
                        extraction_meta,
                    ),
                )
        finally:
            conn.close()

    def get_item_content(self, item_id: int) -> dict[str, Any] | None:
        conn = self.get_connection()
        try:
            row = conn.execute(
                "SELECT * FROM item_content WHERE item_id = ?", (item_id,)
            ).fetchone()
            return dict(row) if row else None
        finally:
            conn.close()

    def save_item_analysis(
        self,
        item_id: int,
        model: str,
        prompt_version: str,
        analysis_json: str,
        substance: float,
        relevance: float,
        novelty: float,
        verdict: str,
    ) -> None:
        now = datetime.datetime.now(datetime.timezone.utc).isoformat()
        conn = self.get_connection()
        try:
            with conn:
                conn.execute(
                    """
                    INSERT INTO item_analysis (
                        item_id, model, prompt_version, analysis_json,
                        substance, relevance, novelty, verdict, created_at
                    ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
                    ON CONFLICT(item_id) DO UPDATE SET
                        model = excluded.model,
                        prompt_version = excluded.prompt_version,
                        analysis_json = excluded.analysis_json,
                        substance = excluded.substance,
                        relevance = excluded.relevance,
                        novelty = excluded.novelty,
                        verdict = excluded.verdict,
                        created_at = excluded.created_at
                    """,
                    (
                        item_id,
                        model,
                        prompt_version,
                        analysis_json,
                        substance,
                        relevance,
                        novelty,
                        verdict,
                        now,
                    ),
                )
        finally:
            conn.close()

    def get_item_analysis(self, item_id: int) -> dict[str, Any] | None:
        conn = self.get_connection()
        try:
            row = conn.execute(
                "SELECT * FROM item_analysis WHERE item_id = ?", (item_id,)
            ).fetchone()
            return dict(row) if row else None
        finally:
            conn.close()

    def list_candidate_items(self) -> list[dict[str, Any]]:
        """List items that are ready or analyzed and have not been digested yet."""
        conn = self.get_connection()
        try:
            rows = conn.execute(
                """
                SELECT i.*, a.substance, a.relevance, a.novelty, a.verdict, a.analysis_json
                FROM items i
                LEFT JOIN item_analysis a ON i.id = a.item_id
                WHERE i.status IN ('ready', 'analyzed')
                  AND i.digested_in IS NULL
                  AND i.skipped = 0
                ORDER BY i.priority DESC, i.id ASC
                """
            ).fetchall()
            return [dict(r) for r in rows]
        finally:
            conn.close()

    def list_today_items(self) -> list[dict[str, Any]]:
        """List all items captured today (UTC)."""
        today = datetime.datetime.now(datetime.timezone.utc).strftime("%Y-%m-%d")
        conn = self.get_connection()
        try:
            rows = conn.execute(
                """
                SELECT * FROM items
                WHERE created_at >= ?
                ORDER BY id DESC
                """,
                (today + "T00:00:00",),
            ).fetchall()
            return [dict(r) for r in rows]
        finally:
            conn.close()

    # --- Digests ---
    def insert_digest(
        self,
        digest_date: str,
        budget_minutes: int,
        kind: str = "daily",
        status: str = "building",
    ) -> int:
        conn = self.get_connection()
        try:
            with conn:
                cursor = conn.execute(
                    """
                    INSERT INTO digests (digest_date, budget_minutes, kind, status)
                    VALUES (?, ?, ?, ?)
                    RETURNING id
                    """,
                    (digest_date, budget_minutes, kind, status),
                )
                return cursor.fetchone()["id"]
        finally:
            conn.close()

    def get_digest_by_date(self, digest_date: str) -> dict[str, Any] | None:
        conn = self.get_connection()
        try:
            row = conn.execute(
                "SELECT * FROM digests WHERE digest_date = ?", (digest_date,)
            ).fetchone()
            return dict(row) if row else None
        finally:
            conn.close()

    def update_digest(self, digest_id: int, **fields: Any) -> None:
        if not fields:
            return
        set_clauses = [f"{k} = ?" for k in fields.keys()]
        values = list(fields.values()) + [digest_id]
        sql = f"UPDATE digests SET {', '.join(set_clauses)} WHERE id = ?"
        conn = self.get_connection()
        try:
            with conn:
                conn.execute(sql, values)
        finally:
            conn.close()

    # --- Jobs Queue ---
    def enqueue_job(
        self,
        kind: str,
        item_id: int | None = None,
        payload: dict[str, Any] | None = None,
        delay_seconds: int = 0,
    ) -> int:
        now = datetime.datetime.now(datetime.timezone.utc)
        run_after = (now + datetime.timedelta(seconds=delay_seconds)).isoformat()
        payload_str = json.dumps(payload or {})
        conn = self.get_connection()
        try:
            with conn:
                cursor = conn.execute(
                    """
                    INSERT INTO jobs (kind, item_id, payload, status, run_after, created_at, updated_at)
                    VALUES (?, ?, ?, 'queued', ?, ?, ?)
                    RETURNING id
                    """,
                    (kind, item_id, payload_str, run_after, now.isoformat(), now.isoformat()),
                )
                return cursor.fetchone()["id"]
        finally:
            conn.close()

    def fetch_next_job(self) -> dict[str, Any] | None:
        """Atomically fetch and lock the next eligible job."""
        now = datetime.datetime.now(datetime.timezone.utc).isoformat()
        conn = self.get_connection()
        try:
            with conn:
                cursor = conn.execute(
                    """
                    SELECT * FROM jobs
                    WHERE status = 'queued' AND run_after <= ?
                    ORDER BY id ASC
                    LIMIT 1
                    """,
                    (now,),
                )
                row = cursor.fetchone()
                if not row:
                    return None
                job = dict(row)
                conn.execute(
                    "UPDATE jobs SET status = 'running', updated_at = ? WHERE id = ?",
                    (now, job["id"]),
                )
                return job
        finally:
            conn.close()

    def reset_stale_running_jobs(self) -> int:
        """Requeues jobs stuck in 'running' from a previous process that crashed or was killed
        mid-job. Called on worker pool startup since fetch_next_job only ever selects
        status='queued', so a job left 'running' would otherwise never be retried."""
        now = datetime.datetime.now(datetime.timezone.utc).isoformat()
        conn = self.get_connection()
        try:
            with conn:
                cursor = conn.execute(
                    "UPDATE jobs SET status = 'queued', updated_at = ? WHERE status = 'running'",
                    (now,),
                )
                return cursor.rowcount
        finally:
            conn.close()

    def complete_job(self, job_id: int) -> None:
        now = datetime.datetime.now(datetime.timezone.utc).isoformat()
        conn = self.get_connection()
        try:
            with conn:
                conn.execute(
                    "UPDATE jobs SET status = 'completed', updated_at = ? WHERE id = ?",
                    (now, job_id),
                )
        finally:
            conn.close()

    def fail_job(self, job_id: int, error: str, retry_delay: int | None = None) -> None:
        now = datetime.datetime.now(datetime.timezone.utc)
        conn = self.get_connection()
        try:
            with conn:
                if retry_delay is not None:
                    run_after = (now + datetime.timedelta(seconds=retry_delay)).isoformat()
                    conn.execute(
                        """
                        UPDATE jobs
                        SET status = 'queued', attempts = attempts + 1,
                            last_error = ?, run_after = ?, updated_at = ?
                        WHERE id = ?
                        """,
                        (error, run_after, now.isoformat(), job_id),
                    )
                else:
                    conn.execute(
                        """
                        UPDATE jobs
                        SET status = 'failed', attempts = attempts + 1,
                            last_error = ?, updated_at = ?
                        WHERE id = ?
                        """,
                        (error, now.isoformat(), job_id),
                    )
        finally:
            conn.close()

    # --- Quota Ledger & LLM Calls ---
    def record_quota_usage(
        self,
        day: str,
        provider: str,
        model: str,
        tokens_in: int,
        tokens_out: int,
        is_429: bool = False,
        exhausted_until: str | None = None,
    ) -> None:
        conn = self.get_connection()
        try:
            with conn:
                conn.execute(
                    """
                    INSERT INTO quota_ledger (day, provider, model, requests, tokens_in, tokens_out, errors_429, exhausted_until)
                    VALUES (?, ?, ?, 1, ?, ?, ?, ?)
                    ON CONFLICT(day, provider, model) DO UPDATE SET
                        requests = requests + 1,
                        tokens_in = tokens_in + excluded.tokens_in,
                        tokens_out = tokens_out + excluded.tokens_out,
                        errors_429 = errors_429 + excluded.errors_429,
                        exhausted_until = COALESCE(excluded.exhausted_until, quota_ledger.exhausted_until)
                    """,
                    (
                        day,
                        provider,
                        model,
                        tokens_in,
                        tokens_out,
                        1 if is_429 else 0,
                        exhausted_until,
                    ),
                )
        finally:
            conn.close()

    def is_model_exhausted(self, day: str, provider: str, model: str) -> bool:
        now = datetime.datetime.now(datetime.timezone.utc).isoformat()
        conn = self.get_connection()
        try:
            row = conn.execute(
                """
                SELECT exhausted_until FROM quota_ledger
                WHERE day = ? AND provider = ? AND model = ?
                """,
                (day, provider, model),
            ).fetchone()
            if row and row["exhausted_until"]:
                return row["exhausted_until"] > now
            return False
        finally:
            conn.close()

    def mark_model_exhausted(self, day: str, provider: str, model: str, until: str) -> None:
        conn = self.get_connection()
        try:
            with conn:
                conn.execute(
                    """
                    INSERT INTO quota_ledger (day, provider, model, requests, exhausted_until)
                    VALUES (?, ?, ?, 0, ?)
                    ON CONFLICT(day, provider, model) DO UPDATE SET
                        exhausted_until = excluded.exhausted_until
                    """,
                    (day, provider, model, until),
                )
        finally:
            conn.close()

    def record_llm_call(
        self,
        task: str,
        provider: str,
        model: str,
        item_id: int | None,
        tokens_in: int,
        tokens_out: int,
        latency_ms: int,
        ok: bool,
        error: str | None = None,
    ) -> None:
        now = datetime.datetime.now(datetime.timezone.utc).isoformat()
        conn = self.get_connection()
        try:
            with conn:
                conn.execute(
                    """
                    INSERT INTO llm_calls (
                        task, provider, model, item_id, tokens_in, tokens_out,
                        latency_ms, ok, error, created_at
                    ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                    """,
                    (
                        task,
                        provider,
                        model,
                        item_id,
                        tokens_in,
                        tokens_out,
                        latency_ms,
                        1 if ok else 0,
                        error,
                        now,
                    ),
                )
        finally:
            conn.close()

    # --- Senders ---
    def get_sender(self, address: str) -> dict[str, Any] | None:
        conn = self.get_connection()
        try:
            row = conn.execute(
                "SELECT * FROM newsletter_senders WHERE address = ?", (address.lower(),)
            ).fetchone()
            return dict(row) if row else None
        finally:
            conn.close()


db = Repository()
