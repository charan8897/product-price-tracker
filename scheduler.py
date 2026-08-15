#!/usr/bin/env python3
"""
Product Price Scheduler + Price History Graph
==============================================
Rescrapes all registered product URLs at fixed times daily.
After each cycle, generates a price history graph for every product.

Schedule (IST):
    3:00 AM, 8:00 AM, 2:00 PM, 5:00 PM, 9:00 PM

Usage:
    python3 scheduler.py                           # Start production scheduler
    python3 scheduler.py --test-times 11:51 11:52 11:53  # Test at specific times
    python3 scheduler.py --run-now                 # Run one cycle immediately
    python3 scheduler.py --graph                   # Generate graph for a product
"""

import argparse
import logging
import os
import signal
import sys
from datetime import datetime, timezone, timedelta

import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt
import matplotlib.dates as mdates

from apscheduler.schedulers.blocking import BlockingScheduler

from product_tracker import init_db, get_conn, scrape_and_save
from price_stats import get_all_price_stats
from job_state import init_state_table, set_last_cycle_time, is_cycle_due

# ── Paths ──
# Resolve relative to this file so the app works in Docker, Render, etc.
BASE_DIR = os.path.dirname(os.path.abspath(__file__))
GRAPH_DIR = os.path.join(BASE_DIR, "price_graphs")
LOG_FILE = os.path.join(BASE_DIR, "scheduler.log")

# ── Timezone ──
IST = timezone(timedelta(hours=5, minutes=30))

# ── Production schedule (IST) ──
PRODUCTION_TIMES = [
    (3,  0, "morning"),
    (8,  0, "breakfast"),
    (14, 0, "afternoon"),
    (17, 0, "evening"),
    (21, 0, "night"),
]

# ── Logging ──
os.makedirs(GRAPH_DIR, exist_ok=True)

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(message)s",
    datefmt="%Y-%m-%d %H:%M:%S",
    handlers=[
        logging.StreamHandler(sys.stdout),
        logging.FileHandler(LOG_FILE),
    ],
)
log = logging.getLogger("scheduler")


# ──────────────────────────────────────────────────────────────────────────────
# GRAPH GENERATION
# ──────────────────────────────────────────────────────────────────────────────

def get_all_unique_urls() -> list[str]:
    """Get all distinct URLs from the products table."""
    conn = get_conn()
    cur = conn.cursor()
    cur.execute("SELECT DISTINCT url FROM products ORDER BY url;")
    urls = [row[0] for row in cur.fetchall()]
    cur.close()
    conn.close()
    return urls


def generate_graph(url: str) -> str | None:
    """Generate a price history graph for a product. Returns file path."""
    from price_stats import get_price_history

    history_raw = get_price_history(url)
    if len(history_raw) < 1:
        return None

    # Get product name
    conn = get_conn()
    cur = conn.cursor()
    cur.execute("SELECT product_name FROM products WHERE url = %s LIMIT 1;", (url,))
    row = cur.fetchone()
    cur.close()
    conn.close()
    name = row[0] if row else "Unknown Product"

    prices = [h["price"] for h in history_raw]
    times = [h["scraped_at"] for h in history_raw]
    changes = [h["change_pct"] for h in history_raw]

    if not prices:
        return None

    # ── Create figure ──
    fig, ax = plt.subplots(figsize=(10, 5))

    # Plot line + markers
    ax.plot(times, prices, color="#2563eb", linewidth=2, marker="o",
            markersize=8, markerfacecolor="#ffffff", markeredgecolor="#2563eb",
            markeredgewidth=2, zorder=5)

    # Fill area under curve
    ax.fill_between(times, prices, alpha=0.08, color="#2563eb")

    # Annotate each point with price + change %
    for i, (t, p) in enumerate(zip(times, prices)):
        chg = changes[i] if i < len(changes) else 0
        if i == 0 or chg == 0:
            label = f"₹{p:,.0f}"
        else:
            arrow = "▲" if chg > 0 else "▼"
            label = f"₹{p:,.0f}\n{arrow}{abs(chg):.1f}%"

        ax.annotate(label,
                    xy=(t, p),
                    xytext=(0, 14),
                    textcoords="offset points",
                    ha="center", fontsize=9, fontweight="bold",
                    color="#1e40af",
                    bbox=dict(boxstyle="round,pad=0.3", facecolor="#dbeafe",
                              edgecolor="#93c5fd", alpha=0.9))

    # Mark min/max + average line
    min_p, max_p = min(prices), max(prices)
    avg_p = sum(prices) / len(prices)

    if min_p != max_p:
        min_idx = prices.index(min_p)
        max_idx = prices.index(max_p)
        ax.scatter([times[min_idx]], [min_p], color="#16a34a", s=120, zorder=6,
                   edgecolors="#15803d", linewidths=2, label=f"Low: ₹{min_p:,.0f}")
        ax.scatter([times[max_idx]], [max_p], color="#dc2626", s=120, zorder=6,
                   edgecolors="#991b1b", linewidths=2, label=f"High: ₹{max_p:,.0f}")

    # Average line
    ax.axhline(y=avg_p, color="#f59e0b", linestyle="--", linewidth=1.5, alpha=0.7,
               label=f"Avg: ₹{avg_p:,.0f}")

    ax.legend(loc="upper right", fontsize=9)

    # Show latest price + change as a big annotation
    latest_price = prices[-1]
    latest_change = changes[-1] if changes else 0
    if latest_change == 0:
        info_text = f"Latest: ₹{latest_price:,.0f}"
    else:
        arrow = "▲" if latest_change > 0 else "▼"
        info_text = f"Latest: ₹{latest_price:,.0f}  ({arrow}{abs(latest_change):.1f}%)"
    ax.text(0.02, 0.95, info_text,
            transform=ax.transAxes, fontsize=12, fontweight="bold",
            color="#1e40af", verticalalignment="top",
            bbox=dict(boxstyle="round,pad=0.5", facecolor="#eff6ff",
                      edgecolor="#2563eb", alpha=0.95))

    # Formatting
    title = name if len(name) <= 60 else name[:57] + "..."
    ax.set_title(f"📈 Price History — {title}", fontsize=13, fontweight="bold",
                 pad=15, color="#1e293b")
    ax.set_xlabel("Time (IST)", fontsize=10, color="#475569")
    ax.set_ylabel("Price (₹)", fontsize=10, color="#475569")

    ax.xaxis.set_major_formatter(mdates.DateFormatter("%b %d\n%H:%M"))
    ax.xaxis.set_major_locator(mdates.AutoDateLocator())
    fig.autofmt_xdate(rotation=30)

    ax.grid(True, alpha=0.3, linestyle="--")
    ax.set_axisbelow(True)
    ax.spines["top"].set_visible(False)
    ax.spines["right"].set_visible(False)

    # Y-axis padding
    y_range = max_p - min_p if max_p != min_p else max_p * 0.1
    ax.set_ylim(min_p - y_range * 0.15, max_p + y_range * 0.25)

    plt.tight_layout()

    # Save
    safe_name = "".join(c if c.isalnum() or c in " -_" else "" for c in name)[:40].strip()
    safe_name = safe_name.replace(" ", "_")
    filepath = os.path.join(GRAPH_DIR, f"price_history_{safe_name}.png")
    fig.savefig(filepath, dpi=150, bbox_inches="tight", facecolor="white")
    plt.close(fig)

    log.info(f"  📊 Graph saved: {filepath}")
    return filepath


def generate_all_graphs():
    """Generate price history graphs for all products."""
    urls = get_all_unique_urls()
    if not urls:
        log.info("  No products to graph.")
        return

    log.info(f"  📊 Generating graphs for {len(urls)} product(s)...")
    for url in urls:
        try:
            generate_graph(url)
        except Exception as e:
            log.error(f"  ❌ Graph failed for {url}: {e}")


# ──────────────────────────────────────────────────────────────────────────────
# SCRAPE CYCLE
# ──────────────────────────────────────────────────────────────────────────────

def run_scrape_cycle():
    """Rescrape all registered product URLs and generate graphs."""
    now = datetime.now(IST).strftime("%Y-%m-%d %H:%M:%S IST")
    log.info(f"{'='*60}")
    log.info(f"  SCHEDULED SCRAPE CYCLE — {now}")
    log.info(f"{'='*60}")

    urls = get_all_unique_urls()
    if not urls:
        log.info("  No URLs in database. Nothing to scrape.")
        return

    log.info(f"  Found {len(urls)} unique URL(s) to rescrape\n")

    success = 0
    failed = 0
    price_changes = []

    for url in urls:
        try:
            # Get previous price for comparison
            conn = get_conn()
            cur = conn.cursor()
            cur.execute("""
                SELECT price FROM products
                WHERE url = %s ORDER BY scraped_at DESC LIMIT 1;
            """, (url,))
            row = cur.fetchone()
            old_price = float(row[0]) if row and row[0] else None
            cur.close()
            conn.close()

            # Scrape
            result = scrape_and_save(url)

            # Calculate change % from previous reading
            new_price = result.get("price")
            if old_price and new_price and old_price > 0:
                change_pct = ((new_price - old_price) / old_price) * 100
                result["change_pct"] = round(change_pct, 2)
            else:
                result["change_pct"] = 0.0

            if "error" in result:
                failed += 1
                continue

            success += 1
            new_price = result.get("price")

            # Check for price change
            if old_price and new_price and old_price != new_price:
                diff = new_price - old_price
                direction = "📈" if diff > 0 else "📉"
                price_changes.append({
                    "name": result.get("name", "?"),
                    "old": old_price,
                    "new": new_price,
                    "diff": diff,
                    "direction": direction,
                })

        except Exception as e:
            log.error(f"  ❌ Failed: {url} — {e}")
            failed += 1

    # Summary
    log.info(f"\n{'='*60}")
    log.info(f"  CYCLE COMPLETE — {success} OK, {failed} failed")

    if price_changes:
        log.info(f"\n  💰 PRICE CHANGES DETECTED:")
        for pc in price_changes:
            log.info(f"     {pc['direction']} {pc['name'][:50]}")
            log.info(f"        ₹{pc['old']:,.0f} → ₹{pc['new']:,.0f}  ({pc['diff']:+,.0f})")
    else:
        log.info("  No price changes detected.")

    # Generate graphs after every cycle
    log.info("")
    generate_all_graphs()

    # Print price statistics
    log.info("")
    stats = get_all_price_stats()
    if stats:
        for s in stats:
            change_pct = s.get("latest_change_pct", 0)
            change_icon = "📈" if change_pct > 0 else ("📉" if change_pct < 0 else "➡️")
            log.info(f"  📊 {s['name'][:50]}")
            log.info(f"     Lowest:    ₹{s['lowest_price']:,.0f}" if s['lowest_price'] else "     Lowest:    -")
            log.info(f"     Average:   ₹{s['avg_price']:,.0f}" if s['avg_price'] else "     Average:   -")
            log.info(f"     Highest:   ₹{s['highest_price']:,.0f}" if s['highest_price'] else "     Highest:   -")
            log.info(f"     Latest:    ₹{s['latest_price']:,.0f}" if s['latest_price'] else "     Latest:    -")
            log.info(f"     Change:    {change_icon} {change_pct:+.2f}%  (vs previous reading)")
            log.info(f"     Readings:  {s['num_readings']}")

    # Record the run durably so the web app (and the next cold start) knows a
    # cycle completed and doesn't re-run this slot.
    set_last_cycle_time()

    log.info(f"{'='*60}\n")


# ──────────────────────────────────────────────────────────────────────────────
# SCHEDULER
# ──────────────────────────────────────────────────────────────────────────────

def create_scheduler(test_times: list[tuple[int, int]] | None = None) -> BlockingScheduler:
    """Create and configure the APScheduler instance."""
    scheduler = BlockingScheduler(timezone="Asia/Kolkata")
    now = datetime.now(IST)

    if test_times:
        # TEST MODE: fire at each specified time
        for i, (h, m) in enumerate(test_times, 1):
            target = now.replace(hour=h, minute=m, second=0, microsecond=0)
            if target <= now:
                target += timedelta(days=1)

            log.info(f"  🧪 Test #{i}: will fire at {target.strftime('%Y-%m-%d %H:%M:%S IST')}")

            scheduler.add_job(
                run_scrape_cycle,
                trigger="date",
                run_date=target,
                id=f"test_scrape_{i}",
                name=f"Test Scrape #{i} ({h:02d}:{m:02d} IST)",
                misfire_grace_time=600,
            )
    else:
        # PRODUCTION SCHEDULE: 3 AM, 8 AM, 2 PM, 5 PM, 9 PM
        for hour, minute, label in PRODUCTION_TIMES:
            scheduler.add_job(
                run_scrape_cycle,
                "cron",
                hour=hour, minute=minute,
                id=f"scrape_{label}",
                name=f"Scrape ({hour:02d}:{minute:02d} IST — {label})",
                misfire_grace_time=300,
            )
            log.info(f"  ⏰ Scheduled: {hour:02d}:{minute:02d} IST ({label})")

    return scheduler


# ──────────────────────────────────────────────────────────────────────────────
# MAIN
# ──────────────────────────────────────────────────────────────────────────────

def main():
    parser = argparse.ArgumentParser(description="Product Price Scheduler + Graphs")
    parser.add_argument("--test-times", nargs="+", metavar="HH:MM",
                        help="Test fire times in HH:MM IST (e.g. --test-times 11:51 11:52 11:53)")
    parser.add_argument("--run-now", action="store_true", help="Run one cycle immediately")
    parser.add_argument("--graph", action="store_true", help="Generate graphs now")
    parser.add_argument("--status", action="store_true", help="Show status")
    parser.add_argument("--if-due", action="store_true",
                        help="Run a cycle only if a scheduled slot was missed "
                             "(safe to call from a frequent external cron)")
    args = parser.parse_args()

    init_db()
    try:
        init_state_table()
    except Exception as e:
        log.warning(f"scheduler_state table unavailable: {e}")

    if args.graph:
        generate_all_graphs()
        return

    if args.status:
        urls = get_all_unique_urls()
        print(f"\n  📋 Registered URLs: {len(urls)}")
        for u in urls:
            print(f"     • {u}")
        print()
        return

    if args.if_due:
        schedule = [(h, m) for h, m, _ in PRODUCTION_TIMES]
        due, reason = is_cycle_due(schedule)
        if not due:
            log.info(f"⏭️  Nothing due — {reason}")
            return
        log.info(f"⚡ Catch-up run — {reason}")
        run_scrape_cycle()
        return

    if args.run_now:
        log.info("⚡ Manual run triggered")
        run_scrape_cycle()
        return

    # Parse test times
    test_times = None
    if args.test_times:
        test_times = []
        for t in args.test_times:
            h, m = t.split(":")
            test_times.append((int(h), int(m)))

    # Start scheduler
    scheduler = create_scheduler(test_times=test_times)

    # Graceful shutdown
    def shutdown(signum, frame):
        log.info("\n🛑 Shutting down scheduler...")
        scheduler.shutdown(wait=False)
        sys.exit(0)

    signal.signal(signal.SIGINT, shutdown)
    signal.signal(signal.SIGTERM, shutdown)

    now = datetime.now(IST).strftime("%Y-%m-%d %H:%M:%S IST")
    log.info(f"\n{'='*60}")
    log.info(f"  🚀 Scheduler started at {now}")
    log.info(f"  📋 Registered URLs: {len(get_all_unique_urls())}")
    log.info(f"  📊 Graphs will be saved to: {GRAPH_DIR}")
    log.info(f"{'='*60}\n")

    try:
        scheduler.start()
    except (KeyboardInterrupt, SystemExit):
        log.info("Scheduler stopped.")


if __name__ == "__main__":
    main()
