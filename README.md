# 📦 Product Price Tracker

Track product prices from **Flipkart**, **Amazon**, **Myntra**, and **AJIO** with automatic scheduling, price history graphs, and a web dashboard.

## Features

- 🔍 **Universal Scraper** — Cloudflare/Akamai bypass, deep-link resolution
- 📊 **Price Statistics** — Lowest, Average, Highest, Change %
- ⏰ **Scheduled Scraping** — 5× daily (3AM, 8AM, 2PM, 5PM, 9PM IST)
- 📈 **Price History Graphs** — Auto-generated with change annotations
- 🌐 **Web Dashboard** — Flask frontend with product cards and detail pages
- 🗄️ **PostgreSQL Storage** — Full price history with timestamps

## Quick Start

```bash
# Clone
git clone https://github.com/YOUR_USERNAME/product-price-tracker.git
cd product-price-tracker

# Setup (installs PostgreSQL + Python deps + Playwright Firefox browser)
chmod +x setup.sh
./setup.sh
# The Playwright Firefox browser is REQUIRED (used to scrape AJIO, which
# blocks plain HTTP with Akamai bot-protection). setup.sh installs it
# automatically; to install manually run:
#   python3 -m playwright install firefox

# Scrape a product
python3 product_tracker.py "https://amzn.in/d/0goi6dbi"

# Start web dashboard
python3 app.py
# Open http://localhost:5000

# Start scheduler (runs forever)
python3 scheduler.py
```

## Usage

### Scrape & Save
```bash
python3 product_tracker.py <URL>
python3 product_tracker.py <URL1> <URL2> <URL3>   # Multiple URLs
```

### View Products
```bash
python3 product_tracker.py --list
python3 product_tracker.py --search "laptop"
python3 product_tracker.py --history <URL>
python3 product_tracker.py --export products.csv
```

### Scheduler
```bash
python3 scheduler.py                # Production: 3AM, 8AM, 2PM, 5PM, 9PM IST
python3 scheduler.py --run-now      # Force one cycle now
python3 scheduler.py --graph        # Generate graphs now
```

## Deployment on Render — why scheduled scrapes may not run

If you host on Render and only see new prices when you click **Refresh All**,
the scheduler is not actually running on the server. There are **two reasons**:

1. **The scheduler process is never started by the Render deploy.**
   `render.yaml` starts only the Flask web app (`app.py`). `scheduler.py` is a
   standalone blocking process that is wired up in `docker-compose.yml` (local)
   but **not** in the Render deployment. The "Refresh All" button works because
   `/refresh` rescrapes inline inside the HTTP request.

2. **Render's free tier hibernates your service.** Free web services spin down
   after **15 minutes without inbound traffic** and only wake on an HTTP request
   (~1 min cold start). So even an in-process scheduler only fires while the
   service happens to be awake (i.e. usually never at 3 AM IST).
   (Render's native cron jobs would fix this, but they are **paid** — minimum
   $1/month per cron job service.)

### Recommended free fix: ping `/cron/refresh` at the 5 schedule times

The web app now has a `/cron/refresh` endpoint that starts a scrape cycle in a
background thread and returns immediately — perfect for free cron pingers.

1. Set a secret on the Render service (Dashboard → your service → Environment):
   ```
   CRON_TOKEN=<random secret>   # e.g. openssl rand -hex 24
   ```
   (Leave it unset if you don't care about the endpoint being public.)

2. Pick **one** trigger option:

   - **GitHub Actions (no third party):** a ready-made workflow is included at
     `.github/workflows/scheduled-refresh.yml` in this repo (add it via the
     GitHub web UI — it can't be pushed by automation without the
     `workflows` permission). It pings `/cron/refresh` at
     03:00, 08:00, 14:00, 17:00, 21:00 IST. Then set two repo settings:
     - Repository **variable** `RENDER_APP_URL` = `https://<your-app>.onrender.com`
     - Repository **secret** `CRON_TOKEN` = the same secret as above

   - **cron-job.org / UptimeRobot (free):** create a cron job / HTTP monitor that
     GETs `https://<your-app>.onrender.com/cron/refresh?token=<CRON_TOKEN>` at the
     five times above. IST → UTC for the cron schedule:
     `21:30, 02:30, 08:30, 11:30, 15:30 UTC`.

   - **Render cron job (paid, $1/mo):** uncomment the `product-tracker-cron`
     service in `render.yaml` and set `ENABLE_SCHEDULER=false` on the web service.
     It runs `python3 scheduler.py --run-now` at the five times, even while the
     web service is asleep.

Each trigger wakes the service (if asleep) and runs one scrape cycle. The app
dedupes cycles within `MINUTES_BETWEEN_CYCLES` (default 60 min), so overlapping
triggers never double-scrape.

### Notes

- `ENABLE_SCHEDULER` (default `true`) turns the in-process APScheduler in
  `app.py` on/off. It works on any always-on host (local, Docker, paid Render);
  on the free tier it only fires while the service is awake, so keep one of the
  external triggers above.
- Free web services also restart at any time and lose their local filesystem —
  the Postgres database is the only durable store, which is why all data lives
  there.

### Tests
```bash
python3 test_price_stats.py              # All 3 cases
python3 test_price_stats.py --case 1     # Highest price test
python3 test_price_stats.py --case 2     # Average price test
python3 test_price_stats.py --case 3     # Lowest price test
```

### Web Dashboard
```bash
python3 app.py              # Start on port 5000
python3 app.py --port 8080  # Custom port
```

## Project Structure

```
├── app.py                # Flask web dashboard (+ in-process scheduler, /cron/refresh)
├── scraper.py            # Universal scraper with Cloudflare bypass
├── product_tracker.py    # CLI tool: scrape & save to PostgreSQL
├── scheduler.py          # APScheduler: auto-rescrape + graphs
├── price_stats.py        # Price statistics calculator
├── test_price_stats.py   # Test suite for price stats
├── setup.sh              # First-time setup script
├── requirements.txt      # Python dependencies
├── render.yaml           # Render blueprint (web + Postgres + optional cron)
└── .github/workflows/    # Scheduled /cron/refresh pings (free, GitHub Actions)
```

## Supported Sites

| Site | Short Links | Status |
|------|-------------|--------|
| Flipkart | `dl.flipkart.com/s/...` | ✅ Full support |
| Amazon | `amzn.in/d/...` | ✅ Full support |
| Myntra | `myntra.com/...` | ⚠️ Site maintenance mode |
| AJIO | `ajioapps.onelink.me/...` | ⚠️ Name from URL slug |

## Tech Stack

- **Python 3.11+**
- **Flask** — Web dashboard
- **PostgreSQL** — Database
- **curl_cffi** — TLS fingerprint impersonation (Cloudflare bypass)
- **APScheduler** — Cron-like scheduling
- **Matplotlib** — Price history graphs
- **BeautifulSoup** — HTML parsing

## License

MIT
