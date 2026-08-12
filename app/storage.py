import json
import sqlite3
import time
from pathlib import Path
from typing import Optional

DB_PATH = Path(__file__).resolve().parent.parent / "runs.db"


def _connect() -> sqlite3.Connection:
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    return conn


def init_db() -> None:
    """Create the runs table if it does not exist. Flat columns are the things
    we filter and sort on; the full nested result is kept as JSON in `payload`."""
    with _connect() as conn:
        conn.execute(
            """
            CREATE TABLE IF NOT EXISTS runs (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                ticker TEXT NOT NULL,
                kind TEXT NOT NULL,            -- 'summary' | 'debate'
                tier TEXT NOT NULL,            -- confident | partial | blocked
                created_at REAL NOT NULL,      -- unix seconds
                cost_usd REAL NOT NULL,
                total_tokens INTEGER NOT NULL,
                payload TEXT NOT NULL          -- full result as JSON
            )
            """
        )


def save_run(
    ticker: str,
    kind: str,
    tier: str,
    cost_usd: float,
    total_tokens: int,
    payload: dict,
) -> int:
    with _connect() as conn:
        cur = conn.execute(
            """
            INSERT INTO runs (ticker, kind, tier, created_at, cost_usd,
                              total_tokens, payload)
            VALUES (?, ?, ?, ?, ?, ?, ?)
            """,
            (
                ticker.upper(),
                kind,
                tier,
                time.time(),
                cost_usd,
                total_tokens,
                json.dumps(payload),
            ),
        )
        return cur.lastrowid


def list_runs(limit: int = 50) -> list[dict]:
    """Recent runs, newest first, without the heavy payload."""
    with _connect() as conn:
        rows = conn.execute(
            """
            SELECT id, ticker, kind, tier, created_at, cost_usd, total_tokens
            FROM runs ORDER BY created_at DESC LIMIT ?
            """,
            (limit,),
        ).fetchall()
    return [dict(r) for r in rows]


def get_run(run_id: int) -> Optional[dict]:
    with _connect() as conn:
        row = conn.execute(
            "SELECT * FROM runs WHERE id = ?", (run_id,)
        ).fetchone()
    if row is None:
        return None
    d = dict(row)
    d["payload"] = json.loads(d["payload"])
    return d