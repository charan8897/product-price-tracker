#!/usr/bin/env python3
"""
URL → Product Scraper + PostgreSQL Storage
===========================================
Scrapes product name & price from any URL and saves to PostgreSQL.

Usage:
    python3 product_tracker.py <URL>                     # Scrape & save
    python3 product_tracker.py <URL> <URL2> ...          # Multiple URLs
    python3 product_tracker.py --list                    # View all saved products
    python3 product_tracker.py --list --recent 10        # Last 10 entries
    python3 product_tracker.py --search "laptop"         # Search by name
    python3 product_tracker.py --history <URL>           # Price history for a URL
    python3 product_tracker.py --export products.csv     # Export to CSV
"""

import argparse
import json
import os
import sys
import time
import random
from datetime import datetime

# ─── DB Config ───
import urllib.parse

DATABASE_URL = os.environ.get("DATABASE_URL", "")
if DATABASE_URL:
    # Parse DATABASE_URL (Render/Heroku format: postgresql://user:pass@host:port/dbname)
    url = urllib.parse.urlparse(DATABASE_URL)
    DB_CONFIG = {
        "host": url.hostname,
        "port": url.port or 5432,
        "dbname": url.path[1:],
        "user": url.username,
        "password": url.password,
    }
else:
    DB_CONFIG = {
        "host": os.environ.get("DB_HOST", "localhost"),
        "port": int(os.environ.get("DB_PORT", 5432)),
        "dbname": os.environ.get("DB_NAME", "myapp"),
        "user": os.environ.get("DB_USER", "myuser"),
        "password": os.environ.get("DB_PASS", "changeme123"),
    }

# Import the scraper we built earlier
from scraper import scrape as scraper_scrape


# ──────────────────────────────────────────────────────────────────────────────
# DATABASE LAYER
# ──────────────────────────────────────────────────────────────────────────────

def get_conn():
    """Get a psycopg2 or psycopg connection."""
    try:
        import psycopg2
        return psycopg2.connect(**DB_CONFIG)
    except ImportError:
        import psycopg
        return psycopg.connect(
            f"postgresql://{DB_CONFIG['user']}:{DB_CONFIG['password']}"
            f"@{DB_CONFIG['host']}:{DB_CONFIG['port']}/{DB_CONFIG['dbname']}"
        )


def init_db():
    """Create the products table if it doesn't exist."""
    try:
        conn = get_conn()
        cur = conn.cursor()
        cur.execute("""
            CREATE TABLE IF NOT EXISTS products (
                id          SERIAL PRIMARY KEY,
                url         TEXT NOT NULL,
                domain      TEXT,
                product_name TEXT,
                price       NUMERIC(12,2),
                currency    TEXT DEFAULT 'INR',
                source      TEXT,
                scraped_at  TIMESTAMP DEFAULT NOW()
            );

            CREATE INDEX IF NOT EXISTS idx_products_url ON products(url);
            CREATE INDEX IF NOT EXISTS idx_products_name ON products(product_name);
            CREATE INDEX IF NOT EXISTS idx_products_scraped ON products(scraped_at DESC);
        """)
        conn.commit()
        cur.close()
        conn.close()
        print("✅ Database initialized (products table ready)")
    except Exception as e:
        print(f"⚠️  init_db error: {e}")


def save_product(url: str, product_name: str, price, currency: str = "INR",
                 domain: str = "", source: str = "") -> int:
    """Insert a scraped product into the database. Returns the row ID."""
    conn = get_conn()
    cur = conn.cursor()
    cur.execute("""
        INSERT INTO products (url, domain, product_name, price, currency, source)
        VALUES (%s, %s, %s, %s, %s, %s)
        RETURNING id;
    """, (url, domain, product_name, price, currency, source))
    row_id = cur.fetchone()[0]
    conn.commit()
    cur.close()
    conn.close()
    return row_id


def get_all_products(limit: int = 50) -> list[dict]:
    """Fetch all saved products."""
    conn = get_conn()
    cur = conn.cursor()
    cur.execute("""
        SELECT id, url, domain, product_name, price, currency, source, scraped_at
        FROM products
        ORDER BY scraped_at DESC
        LIMIT %s;
    """, (limit,))
    cols = [d[0] for d in cur.description]
    rows = [dict(zip(cols, row)) for row in cur.fetchall()]
    cur.close()
    conn.close()
    return rows


def search_products(query: str) -> list[dict]:
    """Search products by name."""
    conn = get_conn()
    cur = conn.cursor()
    cur.execute("""
        SELECT id, url, domain, product_name, price, currency, source, scraped_at
        FROM products
        WHERE product_name ILIKE %s
        ORDER BY scraped_at DESC;
    """, (f"%{query}%",))
    cols = [d[0] for d in cur.description]
    rows = [dict(zip(cols, row)) for row in cur.fetchall()]
    cur.close()
    conn.close()
    return rows


def get_price_history(url: str) -> list[dict]:
    """Get price history for a specific URL."""
    conn = get_conn()
    cur = conn.cursor()
    cur.execute("""
        SELECT id, product_name, price, currency, scraped_at
        FROM products
        WHERE url = %s
        ORDER BY scraped_at ASC;
    """, (url,))
    cols = [d[0] for d in cur.description]
    rows = [dict(zip(cols, row)) for row in cur.fetchall()]
    cur.close()
    conn.close()
    return rows


def export_csv(filepath: str):
    """Export all products to CSV."""
    import csv
    rows = get_all_products(limit=10000)
    if not rows:
        print("No data to export.")
        return
    with open(filepath, "w", newline="") as f:
        writer = csv.DictWriter(f, fieldnames=rows[0].keys())
        writer.writeheader()
        writer.writerows(rows)
    print(f"✅ Exported {len(rows)} rows to {filepath}")


# ──────────────────────────────────────────────────────────────────────────────
# SCRAPE + SAVE
# ──────────────────────────────────────────────────────────────────────────────

def scrape_and_save(url: str) -> dict:
    """Scrape a URL and save results to DB."""
    print(f"\n🔍 Scraping: {url}")

    try:
        result = scraper_scrape(url, verbose=False)
    except Exception as e:
        print(f"   ❌ Failed: {e}")
        return {"url": url, "error": str(e)}

    name = result.get("name")
    price = result.get("price")
    currency = result.get("currency", "INR")
    domain = result.get("domain", "")
    source = result.get("source", "")

    # Convert price to float if it's a string
    if price and isinstance(price, str):
        try:
            price = float(price.replace(",", ""))
        except ValueError:
            price = None

    # Save to DB
    row_id = save_product(
        url=url,
        product_name=name,
        price=price,
        currency=currency,
        domain=domain,
        source=source,
    )

    # Pretty print
    price_display = f"₹{price:,.0f}" if price else "(not found)"
    print(f"   ✅ Saved (id={row_id})")
    print(f"   📦 {name or '(name not found)'}")
    print(f"   💰 {price_display}")

    return {
        "id": row_id,
        "url": url,
        "name": name,
        "price": price,
        "currency": currency,
    }


# ──────────────────────────────────────────────────────────────────────────────
# DISPLAY HELPERS
# ──────────────────────────────────────────────────────────────────────────────

def print_table(rows: list[dict], title: str = "Products"):
    """Print rows as a formatted table."""
    if not rows:
        print(f"\n  No results found.\n")
        return

    print(f"\n{'='*90}")
    print(f"  {title} ({len(rows)} entries)")
    print(f"{'='*90}")
    print(f"  {'ID':<5} {'Product Name':<45} {'Price':>12} {'Domain':<15} {'Scraped At'}")
    print(f"  {'-'*5} {'-'*45} {'-'*12} {'-'*15} {'-'*19}")

    for r in rows:
        name = (r["product_name"] or "?")[:44]
        price = f"₹{r['price']:,.0f}" if r["price"] else "-"
        domain = (r["domain"] or "?")[:14]
        ts = r["scraped_at"].strftime("%Y-%m-%d %H:%M") if r["scraped_at"] else "-"
        print(f"  {r['id']:<5} {name:<45} {price:>12} {domain:<15} {ts}")

    print(f"{'='*90}\n")


def print_history(rows: list[dict]):
    """Print price history."""
    if not rows:
        print("\n  No history found.\n")
        return

    print(f"\n{'='*60}")
    print(f"  Price History: {rows[0]['product_name']}")
    print(f"{'='*60}")
    for r in rows:
        price = f"₹{r['price']:,.0f}" if r["price"] else "-"
        ts = r["scraped_at"].strftime("%Y-%m-%d %H:%M")
        print(f"  {ts}  →  {price}")
    print(f"{'='*60}\n")


# ──────────────────────────────────────────────────────────────────────────────
# MAIN
# ──────────────────────────────────────────────────────────────────────────────

def main():
    parser = argparse.ArgumentParser(
        description="Scrape product info from URLs and save to PostgreSQL",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
Examples:
  python3 product_tracker.py https://dl.flipkart.com/s/FRvi9SuuuN
  python3 product_tracker.py https://amzn.in/d/0fq8HQ49
  python3 product_tracker.py --list
  python3 product_tracker.py --search "laptop"
  python3 product_tracker.py --history "https://amzn.in/d/0fq8HQ49"
  python3 product_tracker.py --export products.csv
        """,
    )
    parser.add_argument("urls", nargs="*", help="URL(s) to scrape")
    parser.add_argument("--list", action="store_true", help="List all saved products")
    parser.add_argument("--recent", type=int, default=50, help="Limit for --list (default: 50)")
    parser.add_argument("--search", type=str, help="Search products by name")
    parser.add_argument("--history", type=str, help="Show price history for a URL")
    parser.add_argument("--export", type=str, help="Export to CSV file")
    args = parser.parse_args()

    # Init DB
    init_db()

    # List mode
    if args.list:
        rows = get_all_products(limit=args.recent)
        print_table(rows, title="Saved Products")
        return

    # Search mode
    if args.search:
        rows = search_products(args.search)
        print_table(rows, title=f"Search: '{args.search}'")
        return

    # History mode
    if args.history:
        rows = get_price_history(args.history)
        print_history(rows)
        return

    # Export mode
    if args.export:
        export_csv(args.export)
        return

    # Scrape mode
    if not args.urls:
        parser.print_help()
        sys.exit(1)

    print(f"\n{'='*60}")
    print(f"  Product Tracker — {len(args.urls)} URL(s)")
    print(f"{'='*60}")

    results = []
    for url in args.urls:
        result = scrape_and_save(url)
        results.append(result)

    # Summary
    success = sum(1 for r in results if "error" not in r)
    print(f"\n{'='*60}")
    print(f"  Done! {success}/{len(results)} scraped and saved.")
    print(f"{'='*60}\n")


if __name__ == "__main__":
    main()
