#!/usr/bin/env python3
"""
Product Tracker — Web Frontend
================================
Flask-based dashboard for viewing tracked products, prices, and history.

Usage:
    python3 app.py                  # Start on port 5000
    python3 app.py --port 8080      # Custom port
"""

import argparse
import base64
import io
import os
import sys
from datetime import datetime, timezone, timedelta

from flask import Flask, render_template_string, request, redirect, url_for, flash

from product_tracker import init_db, get_conn, scrape_and_save
from price_stats import get_price_stats, get_all_price_stats, get_price_history, get_latest_change

IST = timezone(timedelta(hours=5, minutes=30))
GRAPH_DIR = "/home/user/price_graphs"

app = Flask(__name__)
app.secret_key = "product-tracker-secret-key"
app.jinja_env.globals.update(float=float)

# Auto-create table on first request
_db_initialized = False

@app.before_request
def ensure_db():
    global _db_initialized
    if not _db_initialized:
        try:
            init_db()
            _db_initialized = True
            print("✅ DB table ensured on first request")
        except Exception as e:
            print(f"⚠️ DB init error: {e}")


# ──────────────────────────────────────────────────────────────────────────────
# HELPERS
# ──────────────────────────────────────────────────────────────────────────────

def get_all_products(limit=100):
    conn = get_conn()
    cur = conn.cursor()
    cur.execute("""
        SELECT DISTINCT ON (url)
            id, url, domain, product_name, price, currency, source, scraped_at
        FROM products
        ORDER BY url, scraped_at DESC;
    """)
    cols = [d[0] for d in cur.description]
    rows = []
    for row in cur.fetchall():
        d = dict(zip(cols, row))
        # Convert price to float for template
        if d.get("price"):
            d["price"] = float(d["price"])
        rows.append(d)
    cur.close()
    conn.close()
    return rows


def get_recent_changes(limit=10):
    conn = get_conn()
    cur = conn.cursor()
    cur.execute("""
        SELECT p1.url, p1.product_name, p1.price AS current_price,
               p2.price AS previous_price, p1.scraped_at
        FROM products p1
        JOIN LATERAL (
            SELECT price FROM products p2
            WHERE p2.url = p1.url AND p2.scraped_at < p1.scraped_at AND p2.price IS NOT NULL
            ORDER BY p2.scraped_at DESC LIMIT 1
        ) p2 ON TRUE
        WHERE p1.price IS NOT NULL
        ORDER BY p1.scraped_at DESC
        LIMIT %s;
    """, (limit,))
    rows = []
    for row in cur.fetchall():
        url, name, curr, prev, ts = row
        curr_f, prev_f = float(curr), float(prev)
        change_pct = round(((curr_f - prev_f) / prev_f) * 100, 2) if prev_f > 0 else 0
        rows.append({
            "url": url, "name": name, "current_price": curr_f,
            "previous_price": prev_f, "change_pct": change_pct, "scraped_at": ts,
        })
    cur.close()
    conn.close()
    return rows


# ──────────────────────────────────────────────────────────────────────────────
# ROUTES
# ──────────────────────────────────────────────────────────────────────────────

@app.route("/")
def index():
    products = get_all_products()
    stats_map = {}
    for p in products:
        s = get_price_stats(p["url"])
        if s:
            stats_map[p["url"]] = s
    changes = get_recent_changes()
    return render_template_string(INDEX_HTML, products=products, stats=stats_map, changes=changes, now=datetime.now(IST))


@app.route("/add", methods=["POST"])
def add_url():
    url = request.form.get("url", "").strip()
    if not url:
        flash("Please enter a URL", "error")
        return redirect(url_for("index"))
    try:
        result = scrape_and_save(url)
        if result.get("error"):
            flash(f"Scrape failed: {result['error']}", "error")
        else:
            flash(f"Saved: {result.get('name', '?')} — ₹{result.get('price', '?')}", "success")
    except Exception as e:
        flash(f"Error: {e}", "error")
    return redirect(url_for("index"))


@app.route("/product/<path:url>")
def product_detail(url):
    stats = get_price_stats(url)
    history = get_price_history(url)
    change = get_latest_change(url)
    graph_path = os.path.join(GRAPH_DIR, f"price_history_{url.split('/')[-1][:40]}.png")
    graph_exists = os.path.exists(graph_path)
    return render_template_string(DETAIL_HTML, url=url, stats=stats, history=history,
                                  change=change, graph_exists=graph_exists, now=datetime.now(IST))


@app.route("/graph/<path:url>")
def product_graph(url):
    """Generate and serve graph image."""
    from scheduler import generate_graph
    filepath = generate_graph(url)
    if filepath and os.path.exists(filepath):
        with open(filepath, "rb") as f:
            img_data = base64.b64encode(f.read()).decode()
        return f'<img src="data:image/png;base64,{img_data}" style="max-width:100%;border-radius:12px;">'
    return '<p style="color:#94a3b8;">No price data yet — graph will appear after 2+ readings.</p>'


@app.route("/refresh", methods=["POST"])
def refresh_all():
    """Rescrape all registered URLs."""
    conn = get_conn()
    cur = conn.cursor()
    cur.execute("SELECT DISTINCT url FROM products;")
    urls = [row[0] for row in cur.fetchall()]
    cur.close()
    conn.close()

    for u in urls:
        try:
            scrape_and_save(u)
        except Exception:
            pass
    flash(f"Refreshed {len(urls)} product(s)", "success")
    return redirect(url_for("index"))


# ──────────────────────────────────────────────────────────────────────────────
# TEMPLATES
# ──────────────────────────────────────────────────────────────────────────────

STYLE = """
<style>
  * { margin: 0; padding: 0; box-sizing: border-box; }
  body { font-family: -apple-system, BlinkMacSystemFont, 'Segoe UI', Roboto, sans-serif;
         background: #0f172a; color: #e2e8f0; min-height: 100vh; }
  .container { max-width: 1200px; margin: 0 auto; padding: 24px; }
  h1 { font-size: 28px; margin-bottom: 8px; }
  h2 { font-size: 20px; margin-bottom: 16px; color: #94a3b8; }
  h3 { font-size: 16px; margin-bottom: 12px; color: #64748b; }

  .header { display: flex; justify-content: space-between; align-items: center;
            margin-bottom: 32px; padding-bottom: 16px; border-bottom: 1px solid #1e293b; }
  .header a { color: #60a5fa; text-decoration: none; }

  .card { background: #1e293b; border-radius: 16px; padding: 24px; margin-bottom: 20px;
          border: 1px solid #334155; }
  .card:hover { border-color: #475569; }

  .grid { display: grid; grid-template-columns: repeat(auto-fill, minmax(350px, 1fr)); gap: 16px; }

  .stat-row { display: flex; justify-content: space-between; padding: 8px 0;
              border-bottom: 1px solid #334155; }
  .stat-row:last-child { border-bottom: none; }
  .stat-label { color: #94a3b8; font-size: 14px; }
  .stat-value { font-weight: 600; font-size: 15px; }

  .badge { display: inline-block; padding: 2px 10px; border-radius: 20px;
           font-size: 12px; font-weight: 600; }
  .badge-green { background: #064e3b; color: #6ee7b7; }
  .badge-red { background: #7f1d1d; color: #fca5a5; }
  .badge-yellow { background: #78350f; color: #fcd34d; }
  .badge-blue { background: #1e3a5f; color: #93c5fd; }

  .btn { display: inline-block; padding: 10px 20px; border-radius: 10px;
         font-size: 14px; font-weight: 600; cursor: pointer; border: none;
         transition: all 0.2s; text-decoration: none; }
  .btn-primary { background: #2563eb; color: white; }
  .btn-primary:hover { background: #1d4ed8; }
  .btn-secondary { background: #334155; color: #e2e8f0; }
  .btn-secondary:hover { background: #475569; }

  input[type="text"] { width: 100%; padding: 12px 16px; border-radius: 10px;
                        border: 1px solid #334155; background: #0f172a; color: #e2e8f0;
                        font-size: 14px; margin-bottom: 12px; }
  input:focus { outline: none; border-color: #2563eb; }

  table { width: 100%; border-collapse: collapse; }
  th { text-align: left; padding: 12px 16px; color: #64748b; font-size: 12px;
       text-transform: uppercase; letter-spacing: 1px; border-bottom: 1px solid #334155; }
  td { padding: 12px 16px; border-bottom: 1px solid #1e293b; font-size: 14px; }
  tr:hover td { background: #1e293b; }

  .flash { padding: 12px 16px; border-radius: 10px; margin-bottom: 16px; font-size: 14px; }
  .flash-success { background: #064e3b; color: #6ee7b7; }
  .flash-error { background: #7f1d1d; color: #fca5a5; }

  .price-big { font-size: 24px; font-weight: 700; }
  .change-up { color: #f87171; }
  .change-down { color: #4ade80; }
  .change-zero { color: #94a3b8; }

  .product-link { color: #60a5fa; text-decoration: none; font-weight: 600; }
  .product-link:hover { text-decoration: underline; }

  .empty { text-align: center; padding: 60px 20px; color: #475569; }
  .empty p { font-size: 18px; margin-bottom: 8px; }
</style>
"""

INDEX_HTML = """
<!DOCTYPE html>
<html><head><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1">
<title>Product Tracker</title>""" + STYLE + """</head>
<body>
<div class="container">
  <div class="header">
    <div>
      <h1>📦 Product Tracker</h1>
      <p style="color:#64748b;">{{ now.strftime('%Y-%m-%d %H:%M:%S IST') }}</p>
    </div>
    <div style="display:flex;gap:10px;">
      <form method="POST" action="/refresh"><button class="btn btn-secondary">🔄 Refresh All</button></form>
    </div>
  </div>

  {% with messages = get_flashed_messages(with_categories=true) %}
  {% for cat, msg in messages %}
  <div class="flash flash-{{ cat }}">{{ msg }}</div>
  {% endfor %}{% endwith %}

  <!-- Add URL -->
  <div class="card">
    <h3>Add Product URL</h3>
    <form method="POST" action="/add" style="display:flex;gap:12px;">
      <input type="text" name="url" placeholder="https://amzn.in/d/... or https://dl.flipkart.com/s/..." style="margin-bottom:0;flex:1;">
      <button class="btn btn-primary" type="submit">🔍 Scrape & Save</button>
    </form>
  </div>

  {% if products %}
  <!-- Products Grid -->
  <h2>Tracked Products ({{ products|length }})</h2>
  <div class="grid">
    {% for p in products %}
    {% set s = stats.get(p.url, {}) %}
    <div class="card">
      <a href="/product/{{ p.url }}" class="product-link" style="font-size:16px;display:block;margin-bottom:12px;">
        {{ (p.product_name or 'Unknown')[:60] }}
      </a>
      <div style="display:flex;justify-content:space-between;align-items:baseline;margin-bottom:16px;">
        <span class="price-big">₹{{ '{:,.0f}'.format(p.price) if p.price else '—' }}</span>
        {% set chg = s.get('latest_change_pct', 0) %}
        {% if chg > 0 %}
        <span class="badge badge-red">▲ {{ '{:+.1f}'.format(chg) }}%</span>
        {% elif chg < 0 %}
        <span class="badge badge-green">▼ {{ '{:+.1f}'.format(chg) }}%</span>
        {% else %}
        <span class="badge badge-blue">— 0%</span>
        {% endif %}
      </div>
      <div>
        <div class="stat-row">
          <span class="stat-label">Lowest</span>
          <span class="stat-value" style="color:#4ade80;">₹{{ '{:,.0f}'.format(s.get('lowest_price',0)) if s.get('lowest_price') else '—' }}</span>
        </div>
        <div class="stat-row">
          <span class="stat-label">Average</span>
          <span class="stat-value" style="color:#fbbf24;">₹{{ '{:,.0f}'.format(s.get('avg_price',0)) if s.get('avg_price') else '—' }}</span>
        </div>
        <div class="stat-row">
          <span class="stat-label">Highest</span>
          <span class="stat-value" style="color:#f87171;">₹{{ '{:,.0f}'.format(s.get('highest_price',0)) if s.get('highest_price') else '—' }}</span>
        </div>
        <div class="stat-row">
          <span class="stat-label">Readings</span>
          <span class="stat-value">{{ s.get('num_readings', 0) }}</span>
        </div>
      </div>
      <div style="margin-top:12px;font-size:12px;color:#475569;">
        {{ p.domain }} · {{ p.scraped_at.strftime('%b %d, %H:%M') if p.scraped_at else '—' }}
      </div>
    </div>
    {% endfor %}
  </div>

  {% if changes %}
  <!-- Recent Price Changes -->
  <h2 style="margin-top:32px;">Recent Price Changes</h2>
  <div class="card">
    <table>
      <tr><th>Product</th><th>Previous</th><th>Current</th><th>Change</th><th>Time</th></tr>
      {% for c in changes %}
      <tr>
        <td><a href="/product/{{ c.url }}" class="product-link">{{ (c.name or '?')[:50] }}</a></td>
        <td>₹{{ '{:,.0f}'.format(c.previous_price) }}</td>
        <td>₹{{ '{:,.0f}'.format(c.current_price) }}</td>
        <td>
          {% if c.change_pct > 0 %}
          <span class="badge badge-red">▲ {{ '{:+.1f}'.format(c.change_pct) }}%</span>
          {% elif c.change_pct < 0 %}
          <span class="badge badge-green">▼ {{ '{:+.1f}'.format(c.change_pct) }}%</span>
          {% else %}
          <span class="badge badge-blue">0%</span>
          {% endif %}
        </td>
        <td style="color:#64748b;">{{ c.scraped_at.strftime('%b %d, %H:%M') }}</td>
      </tr>
      {% endfor %}
    </table>
  </div>
  {% endif %}

  {% else %}
  <div class="empty card">
    <p>No products tracked yet</p>
    <p style="font-size:14px;">Paste a URL above to start tracking prices</p>
  </div>
  {% endif %}
</div>
</body></html>
"""

DETAIL_HTML = """
<!DOCTYPE html>
<html><head><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1">
<title>{{ (stats.name if stats else 'Product')[:60] }}</title>""" + STYLE + """</head>
<body>
<div class="container">
  <div class="header">
    <div>
      <a href="/">← Back to Dashboard</a>
      <h1 style="margin-top:8px;">{{ (stats.name if stats else 'Product')[:80] }}</h1>
      <p style="color:#64748b;">{{ now.strftime('%Y-%m-%d %H:%M:%S IST') }}</p>
    </div>
  </div>

  {% if stats %}
  <!-- Stats Cards -->
  <div style="display:grid;grid-template-columns:repeat(auto-fill,minmax(200px,1fr));gap:16px;margin-bottom:24px;">
    <div class="card" style="text-align:center;">
      <h3>Latest Price</h3>
      <div class="price-big">₹{{ '{:,.0f}'.format(stats.latest_price) }}</div>
      {% if change %}
      <div style="margin-top:8px;">
        {% if change.change_pct > 0 %}
        <span class="badge badge-red">▲ {{ '{:+.1f}'.format(change.change_pct) }}% vs prev</span>
        {% elif change.change_pct < 0 %}
        <span class="badge badge-green">▼ {{ '{:+.1f}'.format(change.change_pct) }}% vs prev</span>
        {% else %}
        <span class="badge badge-blue">No change</span>
        {% endif %}
      </div>
      {% endif %}
    </div>
    <div class="card" style="text-align:center;">
      <h3>Lowest Price</h3>
      <div class="price-big" style="color:#4ade80;">₹{{ '{:,.0f}'.format(stats.lowest_price) }}</div>
    </div>
    <div class="card" style="text-align:center;">
      <h3>Average Price</h3>
      <div class="price-big" style="color:#fbbf24;">₹{{ '{:,.0f}'.format(stats.avg_price) }}</div>
    </div>
    <div class="card" style="text-align:center;">
      <h3>Highest Price</h3>
      <div class="price-big" style="color:#f87171;">₹{{ '{:,.0f}'.format(stats.highest_price) }}</div>
    </div>
  </div>

  <!-- Overall Change -->
  <div class="card" style="text-align:center;">
    <h3>Overall Change (First → Latest)</h3>
    {% set overall = stats.overall_change_pct %}
    <div style="font-size:32px;font-weight:700;margin-top:8px;">
      {% if overall > 0 %}
      <span class="change-up">▲ {{ '{:+.2f}'.format(overall) }}%</span>
      {% elif overall < 0 %}
      <span class="change-down">▼ {{ '{:+.2f}'.format(overall) }}%</span>
      {% else %}
      <span class="change-zero">0.00%</span>
      {% endif %}
    </div>
    <div style="color:#64748b;margin-top:4px;">
      ₹{{ '{:,.0f}'.format(stats.first_price) }} → ₹{{ '{:,.0f}'.format(stats.latest_price) }}
    </div>
  </div>

  <!-- Graph -->
  <div class="card">
    <h3>📈 Price History Graph</h3>
    <div id="graph-container" style="text-align:center;padding:20px 0;">
      <div id="/graph/{{ url }}">Loading graph...</div>
    </div>
  </div>
  <script>
    fetch("/graph/{{ url }}")
      .then(r => r.text())
      .then(html => { document.getElementById("/graph/{{ url }}").innerHTML = html; });
  </script>

  <!-- History Table -->
  <div class="card">
    <h3>📊 Price History ({{ history|length }} readings)</h3>
    <table>
      <tr><th>#</th><th>Price</th><th>Change %</th><th>Time</th></tr>
      {% for h in history %}
      <tr>
        <td>{{ loop.index }}</td>
        <td style="font-weight:600;">₹{{ '{:,.0f}'.format(h.price) }}</td>
        <td>
          {% if h.change_pct > 0 %}
          <span class="badge badge-red">▲ {{ '{:+.2f}'.format(h.change_pct) }}%</span>
          {% elif h.change_pct < 0 %}
          <span class="badge badge-green">▼ {{ '{:+.2f}'.format(h.change_pct) }}%</span>
          {% else %}
          <span class="badge badge-blue">0.00%</span>
          {% endif %}
        </td>
        <td style="color:#64748b;">{{ h.scraped_at.strftime('%Y-%m-%d %H:%M:%S') }}</td>
      </tr>
      {% endfor %}
    </table>
  </div>

  {% else %}
  <div class="empty card">
    <p>No price data yet</p>
    <p style="font-size:14px;">This product hasn't been scraped yet.</p>
  </div>
  {% endif %}
</div>
</body></html>
"""


# ──────────────────────────────────────────────────────────────────────────────
# MAIN
# ──────────────────────────────────────────────────────────────────────────────

if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Product Tracker Web Frontend")
    parser.add_argument("--port", type=int, default=5000)
    parser.add_argument("--host", default="0.0.0.0")
    args = parser.parse_args()

    init_db()
    print(f"\n🚀 Product Tracker running at http://{args.host}:{args.port}\n")
    app.run(host=args.host, port=args.port, debug=False)
