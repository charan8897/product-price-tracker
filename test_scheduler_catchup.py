#!/usr/bin/env python3
"""
Tests for the wake-up catch-up scheduler logic (no database required).

    python3 test_scheduler_catchup.py

Verifies that after a hibernation gap the app decides to re-run the scrape
cycle for the slot it slept through, and that it does NOT re-run a slot that
was already scraped.
"""

import sys
from datetime import datetime, timedelta, timezone

import job_state
from job_state import IST, previous_slot, is_cycle_due

SCHEDULE = [(3, 0), (8, 0), (14, 0), (17, 0), (21, 0)]

_failures = []


def check(label, got, want):
    ok = got == want
    print(f"  {'✅' if ok else '❌'} {label}: got={got!r} want={want!r}")
    if not ok:
        _failures.append(label)


def ist(y, mo, d, h, mi):
    return datetime(y, mo, d, h, mi, tzinfo=IST)


def with_last_cycle(value):
    """Stub the durable last-run marker."""
    job_state.get_last_cycle_time = lambda: (value.astimezone(timezone.utc) if value else None)


print("\n── previous_slot ──")
check("14:30 IST → 14:00 slot",
      previous_slot(SCHEDULE, now=ist(2026, 8, 15, 14, 30)).astimezone(IST),
      ist(2026, 8, 15, 14, 0))
check("02:00 IST → previous day 21:00 slot",
      previous_slot(SCHEDULE, now=ist(2026, 8, 15, 2, 0)).astimezone(IST),
      ist(2026, 8, 14, 21, 0))
check("exactly 08:00 IST → 08:00 slot",
      previous_slot(SCHEDULE, now=ist(2026, 8, 15, 8, 0)).astimezone(IST),
      ist(2026, 8, 15, 8, 0))

print("\n── is_cycle_due ──")
# Service hibernated at 13:00, woken by a request at 14:20 → 14:00 slot missed.
with_last_cycle(ist(2026, 8, 15, 8, 5))
due, reason = is_cycle_due(SCHEDULE, now=ist(2026, 8, 15, 14, 20))
check("missed 14:00 slot while asleep → due", due, True)
print(f"     reason: {reason}")

# Cycle already ran for the 14:00 slot; further requests must not re-trigger.
with_last_cycle(ist(2026, 8, 15, 14, 3))
due, _ = is_cycle_due(SCHEDULE, now=ist(2026, 8, 15, 14, 20))
check("slot already scraped → not due", due, False)

# Long nap across several slots: still exactly one catch-up run.
with_last_cycle(ist(2026, 8, 13, 21, 2))
due, _ = is_cycle_due(SCHEDULE, now=ist(2026, 8, 15, 9, 0))
check("two-day nap → due", due, True)

# Grace period: right after a slot, leave it to the in-process scheduler.
with_last_cycle(ist(2026, 8, 15, 8, 5))
due, _ = is_cycle_due(SCHEDULE, grace_minutes=5, now=ist(2026, 8, 15, 14, 1))
check("1 min past slot with 5 min grace → not due", due, False)
due, _ = is_cycle_due(SCHEDULE, grace_minutes=5, now=ist(2026, 8, 15, 14, 6))
check("6 min past slot with 5 min grace → due", due, True)

# Brand-new deployment with no history.
with_last_cycle(None)
due, reason = is_cycle_due(SCHEDULE, now=ist(2026, 8, 15, 14, 20))
check("never run before → due", due, True)

# Requests between slots must not trigger anything.
with_last_cycle(ist(2026, 8, 15, 14, 2))
for hh, mm in [(15, 0), (16, 59), (14, 59)]:
    due, _ = is_cycle_due(SCHEDULE, now=ist(2026, 8, 15, hh, mm))
    check(f"request at {hh:02d}:{mm:02d} between slots → not due", due, False)

print()
if _failures:
    print(f"❌ {len(_failures)} check(s) failed: {', '.join(_failures)}\n")
    sys.exit(1)
print("✅ All catch-up scheduler checks passed\n")
