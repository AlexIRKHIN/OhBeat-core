"""Storage of the mock: SQLite in a docker volume, so payments survive a restart.

One connection guarded by a lock: the mock is small, simplicity matters more than speed.
"""

import json
import os
import sqlite3
import threading
from datetime import UTC, datetime

_lock = threading.RLock()
_conn: sqlite3.Connection | None = None

SCHEMA = """
CREATE TABLE IF NOT EXISTS payments (
    id TEXT PRIMARY KEY,
    data TEXT NOT NULL,
    created_at TEXT NOT NULL
);
-- Idempotence-Key -> the stored answer (YooKassa keeps them for 24 hours)
CREATE TABLE IF NOT EXISTS idempotency (
    key TEXT NOT NULL,
    operation TEXT NOT NULL,
    status_code INTEGER NOT NULL,
    body TEXT NOT NULL,
    PRIMARY KEY (key, operation)
);
-- "Break the next N requests" switches of the control panel
CREATE TABLE IF NOT EXISTS faults (
    operation TEXT PRIMARY KEY,
    kind TEXT NOT NULL,
    remaining INTEGER NOT NULL
);
CREATE TABLE IF NOT EXISTS settings (
    key TEXT PRIMARY KEY,
    value TEXT NOT NULL
);
-- Every webhook delivery attempt, for the control panel
CREATE TABLE IF NOT EXISTS deliveries (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    payment_id TEXT NOT NULL,
    event TEXT NOT NULL,
    attempt INTEGER NOT NULL,
    result TEXT NOT NULL,
    at TEXT NOT NULL
);
"""


def now_iso() -> str:
    """UTC time as YooKassa writes it: 2026-11-03T10:15:00.123Z."""
    return datetime.now(UTC).isoformat(timespec="milliseconds").replace("+00:00", "Z")


def connect(path: str | None = None) -> None:
    global _conn
    with _lock:
        path = path or os.environ.get("MOCK_DB_PATH", "/data/yookassa.sqlite3")
        if path != ":memory:":
            os.makedirs(os.path.dirname(path), exist_ok=True)
        _conn = sqlite3.connect(path, check_same_thread=False, isolation_level=None)
        _conn.executescript(SCHEMA)


def ensure_connected() -> None:
    if _conn is None:
        connect()


def _db() -> sqlite3.Connection:
    if _conn is None:
        connect()
    return _conn  # type: ignore[return-value]


# --- Payments ---

def save_payment(payment: dict) -> None:
    with _lock:
        _db().execute(
            "INSERT INTO payments (id, data, created_at) VALUES (?, ?, ?) "
            "ON CONFLICT (id) DO UPDATE SET data = excluded.data",
            (payment["id"], json.dumps(payment, ensure_ascii=False), payment["created_at"]),
        )


def get_payment(payment_id: str) -> dict | None:
    with _lock:
        row = _db().execute("SELECT data FROM payments WHERE id = ?", (payment_id,)).fetchone()
    return json.loads(row[0]) if row else None


def list_payments(limit: int = 50) -> list[dict]:
    with _lock:
        rows = _db().execute("SELECT data FROM payments ORDER BY created_at DESC LIMIT ?", (limit,)).fetchall()
    return [json.loads(r[0]) for r in rows]


def locked():
    """For read-modify-write of one payment: `with store.locked(): ...`."""
    return _lock


# --- Idempotency ---

def stored_answer(key: str, operation: str) -> tuple[int, dict] | None:
    with _lock:
        row = _db().execute("SELECT status_code, body FROM idempotency WHERE key = ? AND operation = ?",
                            (key, operation)).fetchone()
    return (row[0], json.loads(row[1])) if row else None


def store_answer(key: str, operation: str, status_code: int, body: dict) -> None:
    with _lock:
        _db().execute("INSERT OR IGNORE INTO idempotency (key, operation, status_code, body) VALUES (?, ?, ?, ?)",
                      (key, operation, status_code, json.dumps(body, ensure_ascii=False)))


# --- Faults and settings ---

def set_fault(operation: str, kind: str, count: int) -> None:
    with _lock:
        if kind == "none" or count <= 0:
            _db().execute("DELETE FROM faults WHERE operation = ?", (operation,))
        else:
            _db().execute("INSERT INTO faults (operation, kind, remaining) VALUES (?, ?, ?) "
                          "ON CONFLICT (operation) DO UPDATE SET kind = excluded.kind, remaining = excluded.remaining",
                          (operation, kind, count))


def take_fault(operation: str) -> str | None:
    """The fault for this request, if one is armed; each request uses one of the N."""
    with _lock:
        row = _db().execute("SELECT kind, remaining FROM faults WHERE operation = ?", (operation,)).fetchone()
        if not row:
            return None
        if row[1] <= 1:
            _db().execute("DELETE FROM faults WHERE operation = ?", (operation,))
        else:
            _db().execute("UPDATE faults SET remaining = remaining - 1 WHERE operation = ?", (operation,))
        return row[0]


def list_faults() -> dict[str, tuple[str, int]]:
    with _lock:
        return {r[0]: (r[1], r[2]) for r in _db().execute("SELECT operation, kind, remaining FROM faults")}


def get_setting(key: str, default: str) -> str:
    with _lock:
        row = _db().execute("SELECT value FROM settings WHERE key = ?", (key,)).fetchone()
    return row[0] if row else default


def set_setting(key: str, value: str) -> None:
    with _lock:
        _db().execute("INSERT INTO settings (key, value) VALUES (?, ?) "
                      "ON CONFLICT (key) DO UPDATE SET value = excluded.value", (key, value))


# --- Webhook deliveries ---

def log_delivery(payment_id: str, event: str, attempt: int, result: str) -> None:
    with _lock:
        _db().execute("INSERT INTO deliveries (payment_id, event, attempt, result, at) VALUES (?, ?, ?, ?, ?)",
                      (payment_id, event, attempt, result, now_iso()))


def list_deliveries(limit: int = 30) -> list[dict]:
    with _lock:
        rows = _db().execute("SELECT payment_id, event, attempt, result, at FROM deliveries ORDER BY id DESC LIMIT ?",
                             (limit,)).fetchall()
    return [dict(zip(("payment_id", "event", "attempt", "result", "at"), r)) for r in rows]


def last_event(payment_id: str) -> str | None:
    with _lock:
        row = _db().execute("SELECT event FROM deliveries WHERE payment_id = ? ORDER BY id DESC LIMIT 1",
                            (payment_id,)).fetchone()
    return row[0] if row else None
