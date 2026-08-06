#!/usr/bin/env python3
"""
Price Statistics Calculator
============================
Calculates highest, lowest, average prices and discount % for each product.
Used by the scheduler after each scrape cycle.
"""

from product_tracker import get_conn


def get_price_stats(url: str) -> dict | None:
    """Get min/max/avg price stats for a product URL."""
    conn = get_conn()
    cur = conn.cursor()
    cur.execute("""
        SELECT
            product_name,
            MIN(price)   AS lowest_price,
            MAX(price)   AS highest_price,
            AVG(price)   AS avg_price,
            COUNT(price) AS num_readings,
            (SELECT price FROM products WHERE url = %s AND price IS NOT NULL ORDER BY scraped_at DESC LIMIT 1) AS latest_price,
            (SELECT price FROM products WHERE url = %s AND price IS NOT NULL ORDER BY scraped_at ASC LIMIT 1) AS first_price
        FROM products
        WHERE url = %s AND price IS NOT NULL
        GROUP BY product_name;
    """, (url, url, url))
    row = cur.fetchone()
    cur.close()
    conn.close()

    if not row:
        return None

    name, lowest, highest, avg, count, latest, first = row

    lowest = round(float(lowest), 2) if lowest else None
    highest = round(float(highest), 2) if highest else None
    avg = round(float(avg), 2) if avg else None
    latest = round(float(latest), 2) if latest else None
    first = round(float(first), 2) if first else None

    # Discount: latest vs first (overall change)
    overall_change_pct = 0.0
    if first and latest and first > 0:
        overall_change_pct = round(((latest - first) / first) * 100, 2)

    return {
        "name": name,
        "lowest_price": lowest,
        "highest_price": highest,
        "avg_price": avg,
        "latest_price": latest,
        "first_price": first,
        "overall_change_pct": overall_change_pct,
        "num_readings": count,
    }


def get_price_history(url: str) -> list[dict]:
    """Get full price history with change % between consecutive readings."""
    conn = get_conn()
    cur = conn.cursor()
    cur.execute("""
        SELECT id, price, scraped_at
        FROM products
        WHERE url = %s AND price IS NOT NULL
        ORDER BY scraped_at ASC;
    """, (url,))
    rows = cur.fetchall()
    cur.close()
    conn.close()

    if not rows:
        return []

    history = []
    prev_price = None
    for row_id, price, ts in rows:
        price_f = float(price)
        # Calculate change from previous reading
        if prev_price is not None and prev_price > 0:
            change_pct = round(((price_f - prev_price) / prev_price) * 100, 2)
        else:
            change_pct = 0.0  # First reading = baseline

        history.append({
            "id": row_id,
            "price": price_f,
            "change_pct": change_pct,
            "scraped_at": ts,
        })
        prev_price = price_f

    return history


def get_latest_change(url: str) -> dict | None:
    """Get the most recent price change (between last 2 readings)."""
    conn = get_conn()
    cur = conn.cursor()
    cur.execute("""
        SELECT price, scraped_at FROM products
        WHERE url = %s AND price IS NOT NULL
        ORDER BY scraped_at DESC
        LIMIT 2;
    """, (url,))
    rows = cur.fetchall()
    cur.close()
    conn.close()

    if len(rows) < 2:
        return None

    latest_price, latest_ts = rows[0]
    prev_price, prev_ts = rows[1]
    latest_f = float(latest_price)
    prev_f = float(prev_price)

    if prev_f > 0:
        change_pct = round(((latest_f - prev_f) / prev_f) * 100, 2)
    else:
        change_pct = 0.0

    return {
        "latest_price": latest_f,
        "previous_price": prev_f,
        "change_pct": change_pct,
        "latest_ts": latest_ts,
        "previous_ts": prev_ts,
    }


def get_all_price_stats() -> list[dict]:
    """Get price stats for all products."""
    conn = get_conn()
    cur = conn.cursor()
    cur.execute("SELECT DISTINCT url FROM products ORDER BY url;")
    urls = [row[0] for row in cur.fetchall()]
    cur.close()
    conn.close()

    stats = []
    for url in urls:
        s = get_price_stats(url)
        if s:
            s["url"] = url
            # Get latest change
            change = get_latest_change(url)
            s["latest_change_pct"] = change["change_pct"] if change else 0.0
            stats.append(s)
    return stats


def print_price_stats(stats: list[dict]):
    """Pretty-print price statistics."""
    if not stats:
        print("  No price data available.")
        return

    print(f"\n{'='*100}")
    print(f"  PRICE STATISTICS")
    print(f"{'='*100}")
    print(f"  {'Product':<35} {'Lowest':>10} {'Average':>10} {'Highest':>10} {'Latest':>10} {'Change':>10}")
    print(f"  {'-'*35} {'-'*10} {'-'*10} {'-'*10} {'-'*10} {'-'*10}")

    for s in stats:
        name = (s["name"] or "?")[:34]
        lo = f"₹{s['lowest_price']:,.0f}" if s["lowest_price"] else "-"
        hi = f"₹{s['highest_price']:,.0f}" if s["highest_price"] else "-"
        avg = f"₹{s['avg_price']:,.0f}" if s["avg_price"] else "-"
        latest = f"₹{s['latest_price']:,.0f}" if s["latest_price"] else "-"
        chg = s.get("latest_change_pct", 0)
        chg_str = f"{chg:+.2f}%"
        print(f"  {name:<35} {lo:>10} {avg:>10} {hi:>10} {latest:>10} {chg_str:>10}")

    print(f"{'='*100}\n")
