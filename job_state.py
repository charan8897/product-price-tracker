#!/usr/bin/env python3
"""
Durable scheduler state (PostgreSQL-backed)
===========================================
On hosts that hibernate the web service (Render/Railway/Fly free tiers), the
process — and therefore any in-process APScheduler — dies between requests.
Anything kept in memory or on the local disk is lost.

The Postgres database is the only durable store, so the scheduler's bookkeeping
lives there:

  * ``scheduler_state``      — last time a scrape cycle finished (survives restarts)
  * ``pg_try_advisory_lock`` — cross-process/worker mutex so two gunicorn workers
                               (or the web app and an external cron ping) can
                               never run the same cycle twice.

This module is deliberately dependency-free apart from ``product_tracker.get_conn``.
"""

from __future__ import annotations

import contextlib
from datetime import datetime, timedelta, timezone

from product_tracker import get_conn

IST = timezone(timedelta(hours=5, minutes=30))

# Arbitrary but stable key for the Postgres advisory lock guarding scrape cycles.
CYCLE_LOCK_KEY = 728_411_903

_STATE_KEY_LAST_CYCLE = "last_cycle_finished"


# ──────────────────────────────────────────────────────────────────────────────
# SCHEMA
# ──────────────────────────────────────────────────────────────────────────────

def init_state_table() -> None:
    """Create the scheduler_state table if it doesn't exist."""
    conn = get_conn()
    try:
        cur = conn.cursor()
        cur.execute("""
            CREATE TABLE IF NOT EXISTS scheduler_state (
                key        TEXT PRIMARY KEY,
                value_ts   TIMESTAMPTZ,
                updated_at TIMESTAMPTZ DEFAULT NOW()
            );
        """)
        conn.commit()
        cur.close()
    finally:
        with contextlib.suppress(Exception):
            conn.close()


# ──────────────────────────────────────────────────────────────────────────────
# LAST-RUN BOOKKEEPING
# ──────────────────────────────────────────────────────────────────────────────

def get_last_cycle_time() -> datetime | None:
    """Return when the last scrape cycle finished (UTC), or None if never."""
    try:
        conn = get_conn()
    except Exception:
        return None
    try:
        cur = conn.cursor()
        cur.execute(
            "SELECT value_ts FROM scheduler_state WHERE key = %s;",
            (_STATE_KEY_LAST_CYCLE,),
        )
        row = cur.fetchone()
        cur.close()
    except Exception:
        return None
    finally:
        with contextlib.suppress(Exception):
            conn.close()

    if not row or not row[0]:
        return None
    ts = row[0]
    if ts.tzinfo is None:  # defensive: column should be TIMESTAMPTZ
        ts = ts.replace(tzinfo=timezone.utc)
    return ts.astimezone(timezone.utc)


def set_last_cycle_time(when: datetime | None = None) -> None:
    """Record that a scrape cycle just finished."""
    when = when or datetime.now(timezone.utc)
    try:
        conn = get_conn()
    except Exception:
        return
    try:
        cur = conn.cursor()
        cur.execute("""
            INSERT INTO scheduler_state (key, value_ts, updated_at)
            VALUES (%s, %s, NOW())
            ON CONFLICT (key) DO UPDATE
                SET value_ts = EXCLUDED.value_ts, updated_at = NOW();
        """, (_STATE_KEY_LAST_CYCLE, when))
        conn.commit()
        cur.close()
    except Exception:
        pass
    finally:
        with contextlib.suppress(Exception):
            conn.close()


# ──────────────────────────────────────────────────────────────────────────────
# SLOT MATH
# ──────────────────────────────────────────────────────────────────────────────

def previous_slot(schedule_ist: list[tuple[int, int]],
                  now: datetime | None = None) -> datetime:
    """Most recent scheduled slot at/or before `now`, as an aware UTC datetime."""
    now_ist = (now or datetime.now(timezone.utc)).astimezone(IST)
    todays = [
        now_ist.replace(hour=h, minute=m, second=0, microsecond=0)
        for h, m in sorted(schedule_ist)
    ]
    past = [t for t in todays if t <= now_ist]
    slot = past[-1] if past else todays[-1] - timedelta(days=1)
    return slot.astimezone(timezone.utc)


def is_cycle_due(schedule_ist: list[tuple[int, int]],
                 grace_minutes: int = 0,
                 now: datetime | None = None) -> tuple[bool, str]:
    """Has a scheduled slot passed that we haven't scraped for yet?

    Returns (due, human-readable reason). ``grace_minutes`` ignores slots that
    are still very fresh, which keeps a cold-starting instance from scraping
    before the in-process scheduler would have.
    """
    now = now or datetime.now(timezone.utc)
    slot = previous_slot(schedule_ist, now=now)

    if grace_minutes and (now - slot) < timedelta(minutes=grace_minutes):
        return False, "slot too fresh (within grace period)"

    last = get_last_cycle_time()
    if last is None:
        return True, "no cycle has ever run"
    if last < slot:
        missed = slot.astimezone(IST).strftime("%Y-%m-%d %H:%M IST")
        return True, f"missed the {missed} slot (last cycle {last.astimezone(IST):%Y-%m-%d %H:%M IST})"
    return False, "already scraped for the latest slot"


# ──────────────────────────────────────────────────────────────────────────────
# CROSS-PROCESS LOCK
# ──────────────────────────────────────────────────────────────────────────────

class cycle_lock:
    """Context manager around a Postgres session advisory lock.

    ``with cycle_lock() as acquired:`` — ``acquired`` is False when another
    process/worker already holds the lock, in which case do nothing.
    Falls back to "acquired" if the DB is unreachable, so a database blip can
    never permanently wedge the scheduler (the in-process lock still applies).
    """

    def __init__(self, key: int = CYCLE_LOCK_KEY):
        self.key = key
        self.conn = None
        self.acquired = False

    def __enter__(self) -> bool:
        try:
            self.conn = get_conn()
            cur = self.conn.cursor()
            cur.execute("SELECT pg_try_advisory_lock(%s);", (self.key,))
            self.acquired = bool(cur.fetchone()[0])
            cur.close()
        except Exception:
            self.conn = None
            self.acquired = True  # fail open
        return self.acquired

    def __exit__(self, exc_type, exc, tb) -> bool:
        if self.conn is not None:
            with contextlib.suppress(Exception):
                cur = self.conn.cursor()
                cur.execute("SELECT pg_advisory_unlock(%s);", (self.key,))
                cur.close()
            with contextlib.suppress(Exception):
                self.conn.close()
        self.conn = None
        return False
