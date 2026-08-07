#!/usr/bin/env python3
"""
Test Script for Price Statistics (Highest / Average / Lowest)
=============================================================
Runs 3 test cases by inserting dummy prices at scheduled times,
then verifies the calculated statistics.

Each case:
  - Fire #1 (T+2min): Insert dummy price value
  - Fire #2 (T+3min): Insert second dummy price
  - Fire #3 (T+4min): Insert third dummy price
  - After fire #3: Verify stats (highest/avg/lowest)

Usage:
    python3 test_price_stats.py              # Run all 3 cases
    python3 test_price_stats.py --case 1     # Run only case 1
"""

import argparse
import sys
import time
from datetime import datetime, timezone, timedelta

from apscheduler.schedulers.blocking import BlockingScheduler

from product_tracker import init_db, get_conn
from price_stats import get_price_stats, get_price_history

IST = timezone(timedelta(hours=5, minutes=30))

# ── Colors ──
GREEN = "\033[92m"
RED = "\033[91m"
YELLOW = "\033[93m"
CYAN = "\033[96m"
BOLD = "\033[1m"
RESET = "\033[0m"


def log(msg, color=""):
    ts = datetime.now(IST).strftime("%H:%M:%S")
    if color:
        print(f"  {color}[{ts}] {msg}{RESET}")
    else:
        print(f"  [{ts}] {msg}")


def insert_dummy_price(product_name: str, price: float, url: str):
    """Insert a dummy price record (bypasses scraping)."""
    conn = get_conn()
    cur = conn.cursor()
    cur.execute("""
        INSERT INTO products (url, domain, product_name, price, currency, source)
        VALUES (%s, %s, %s, %s, %s, %s)
        RETURNING id;
    """, (url, "test.local", product_name, price, "INR", "test-dummy"))
    row_id = cur.fetchone()[0]
    conn.commit()
    cur.close()
    conn.close()
    log(f"Inserted id={row_id}: {product_name} → ₹{price:,.0f}", CYAN)
    return row_id


def clean_test_data():
    """Remove all test dummy data."""
    conn = get_conn()
    cur = conn.cursor()
    cur.execute("DELETE FROM products WHERE source = 'test-dummy';")
    deleted = cur.rowcount
    conn.commit()
    cur.close()
    conn.close()
    if deleted:
        log(f"Cleaned {deleted} test record(s)", YELLOW)


# ══════════════════════════════════════════════════════════════
#  TEST CASES
# ══════════════════════════════════════════════════════════════

TEST_URL = "https://test.example.com/product/123"
TEST_NAME_BASE = "TEST PRODUCT - {case}"

# ── Case 1: Highest Price ──
#   Fire 1: ₹1000
#   Fire 2: ₹2500
#   Fire 3: ₹5000   ← should be the highest
CASE1_PRICES = [1000, 2500, 5000]
CASE1_EXPECTED_HIGHEST = 5000
CASE1_EXPECTED_LOWEST = 1000
CASE1_EXPECTED_AVG = 2833.33

# ── Case 2: Average Price ──
#   Fire 1: ₹6000
#   Fire 2: ₹9000
#   Fire 3: ₹15000  ← avg should be 10000
CASE2_PRICES = [6000, 9000, 15000]
CASE2_EXPECTED_HIGHEST = 15000
CASE2_EXPECTED_LOWEST = 6000
CASE2_EXPECTED_AVG = 10000

# ── Case 3: Lowest Price ──
#   Fire 1: ₹8000
#   Fire 2: ₹3500
#   Fire 3: ₹1200   ← should be the lowest
CASE3_PRICES = [8000, 3500, 1200]
CASE3_EXPECTED_HIGHEST = 8000
CASE3_EXPECTED_LOWEST = 1200
CASE3_EXPECTED_AVG = 4233.33

CASES = {
    1: {
        "name": "HIGHEST PRICE",
        "prices": CASE1_PRICES,
        "expected": {
            "highest": CASE1_EXPECTED_HIGHEST,
            "lowest": CASE1_EXPECTED_LOWEST,
            "avg": CASE1_EXPECTED_AVG,
        },
    },
    2: {
        "name": "AVERAGE PRICE",
        "prices": CASE2_PRICES,
        "expected": {
            "highest": CASE2_EXPECTED_HIGHEST,
            "lowest": CASE2_EXPECTED_LOWEST,
            "avg": CASE2_EXPECTED_AVG,
        },
    },
    3: {
        "name": "LOWEST PRICE",
        "prices": CASE3_PRICES,
        "expected": {
            "highest": CASE3_EXPECTED_HIGHEST,
            "lowest": CASE3_EXPECTED_LOWEST,
            "avg": CASE3_EXPECTED_AVG,
        },
    },
}


# ══════════════════════════════════════════════════════════════
#  TEST RUNNER
# ══════════════════════════════════════════════════════════════

class TestRunner:
    def __init__(self, case_num: int):
        self.case_num = case_num
        self.case = CASES[case_num]
        self.fire_count = 0
        self.test_name = TEST_NAME_BASE.format(case=self.case["name"])
        self.passed = None

    def fire(self):
        """Called by scheduler at each scheduled time."""
        self.fire_count += 1
        price = self.case["prices"][self.fire_count - 1]

        log(f"{'='*60}")
        log(f"  FIRE #{self.fire_count}/3 — Case {self.case_num}: {self.case['name']}", BOLD)
        log(f"{'='*60}")

        # Insert dummy price
        insert_dummy_price(self.test_name, price, TEST_URL)

        # If this is the last fire, verify stats
        if self.fire_count == 3:
            time.sleep(1)  # let DB settle
            self.verify()

    def verify(self):
        """Verify the calculated stats match expected values."""
        log(f"\n{'='*60}")
        log(f"  VERIFYING: Case {self.case_num} — {self.case['name']}", BOLD)
        log(f"{'='*60}")

        stats = get_price_stats(TEST_URL)
        if not stats:
            log("  ❌ No stats found!", RED)
            self.passed = False
            return

        expected = self.case["expected"]
        checks = [
            ("Highest", stats["highest_price"], expected["highest"]),
            ("Lowest", stats["lowest_price"], expected["lowest"]),
            ("Average", stats["avg_price"], expected["avg"]),
        ]

        self.passed = True
        for label, actual, exp in checks:
            ok = abs(actual - exp) < 1.0  # allow tiny float rounding
            status = f"{GREEN}✅ PASS{RESET}" if ok else f"{RED}❌ FAIL{RESET}"
            if not ok:
                self.passed = False
            log(f"  {label:>8}: actual=₹{actual:,.2f}  expected=₹{exp:,.2f}  {status}")

        # Verify change percentages
        log(f"\n  --- Discount / Change % ---")
        history = get_price_history(TEST_URL)
        for i, h in enumerate(history):
            price = h["price"]
            chg = h["change_pct"]
            ts = h["scraped_at"].strftime("%H:%M:%S")
            if i == 0:
                log(f"  Reading {i+1}: ₹{price:,.0f}  change=0.00% (baseline)  [{ts}]")
            else:
                arrow = "▲" if chg > 0 else ("▼" if chg < 0 else "➡️")
                log(f"  Reading {i+1}: ₹{price:,.0f}  change={chg:+.2f}% {arrow}  [{ts}]")

        log(f"\n  Readings: {stats['num_readings']}")
        result = f"{GREEN}✅ PASSED{RESET}" if self.passed else f"{RED}❌ FAILED{RESET}"
        log(f"\n  {'='*60}")
        log(f"  CASE {self.case_num} ({self.case['name']}): {result}", BOLD if self.passed else RED)
        log(f"  {'='*60}\n")


def run_test_case(case_num: int, offset: int = 2):
    """Run a single test case with 3 scheduled fires."""
    runner = TestRunner(case_num)
    now = datetime.now(IST)

    scheduler = BlockingScheduler(timezone="Asia/Kolkata")

    for i in range(3):
        target = now + timedelta(minutes=offset + i)
        scheduler.add_job(
            runner.fire,
            trigger="date",
            run_date=target,
            id=f"test_fire_{i+1}",
            name=f"Fire #{i+1}",
            misfire_grace_time=120,
        )
        log(f"Scheduled fire #{i+1} at {target.strftime('%H:%M:%S IST')}", CYAN)

    # Auto-shutdown after last fire
    shutdown_time = now + timedelta(minutes=offset + 3, seconds=10)
    scheduler.add_job(
        lambda: scheduler.shutdown(wait=False),
        trigger="date",
        run_date=shutdown_time,
        id="auto_shutdown",
    )

    log(f"\n  Running Case {case_num}: {runner.case['name']}...", BOLD)
    log(f"  Prices: {runner.case['prices']}")
    log(f"  Expected → Highest: ₹{runner.case['expected']['highest']:,}  "
        f"Average: ₹{runner.case['expected']['avg']:,.2f}  "
        f"Lowest: ₹{runner.case['expected']['lowest']:,}")
    log("")

    try:
        scheduler.start()
    except (KeyboardInterrupt, SystemExit):
        pass

    return runner.passed


# ══════════════════════════════════════════════════════════════
#  MAIN
# ══════════════════════════════════════════════════════════════

def main():
    parser = argparse.ArgumentParser(description="Test Price Statistics")
    parser.add_argument("--case", type=int, choices=[1, 2, 3],
                        help="Run specific case only (1=highest, 2=avg, 3=lowest)")
    parser.add_argument("--offset", type=int, default=2,
                        help="Minutes from now for first fire (default: 2)")
    args = parser.parse_args()

    init_db()

    print(f"\n{'='*60}")
    print(f"  PRICE STATISTICS TEST SUITE")
    print(f"  Time: {datetime.now(IST).strftime('%Y-%m-%d %H:%M:%S IST')}")
    print(f"{'='*60}\n")

    # Clean previous test data
    clean_test_data()

    cases_to_run = [args.case] if args.case else [1, 2, 3]
    results = {}

    for case_num in cases_to_run:
        passed = run_test_case(case_num, offset=args.offset)
        results[case_num] = passed
        if case_num != cases_to_run[-1]:
            clean_test_data()
            time.sleep(2)

    # Final summary
    print(f"\n{'='*60}")
    print(f"  FINAL RESULTS")
    print(f"{'='*60}")
    for case_num, passed in results.items():
        status = f"{GREEN}✅ PASSED{RESET}" if passed else f"{RED}❌ FAILED{RESET}"
        print(f"  Case {case_num} ({CASES[case_num]['name']:>15}): {status}")

    all_passed = all(results.values())
    print(f"\n  Overall: {f'{GREEN}ALL PASSED{RESET}' if all_passed else f'{RED}SOME FAILED{RESET}'}")
    print(f"{'='*60}\n")

    # Cleanup
    clean_test_data()

    sys.exit(0 if all_passed else 1)


if __name__ == "__main__":
    main()
