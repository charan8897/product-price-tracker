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

## Deployment on a sleeping host — why scheduled scrapes stop

If your host prints something like this in the logs…

```
Incoming HTTP request detected ...
Service waking up ...
Allocating compute resources ...
```

…then your web service **hibernates**. Free tiers on Render/Railway/Fly spin the
container down after ~15 minutes without traffic and only start it again when an
HTTP request arrives (~1 min cold start).

While the service is asleep **no process exists**, so:

- the in-process APScheduler in `app.py` isn't running and can't fire at 3 AM;
- anything remembered in memory or on the local disk is wiped on every restart.

That's why prices only updated when you clicked **Refresh All** — `/refresh`
scrapes inline inside the HTTP request, which is the one code path that always
has a live process.

### How this repo fixes it

**1. Durable scheduler state in Postgres (`job_state.py`).**
The time of the last completed cycle is stored in a `scheduler_state` table
instead of in memory, so it survives spin-down, restarts and redeploys.

**2. Catch-up on wake.**
Every incoming request — *including the very request that woke the service* —
does a cheap check: "has a scheduled slot passed since the last completed
cycle?" If yes, one scrape cycle runs in a background thread and the request
returns immediately. So the 3 AM slot is scraped the next time anyone (a user,
an uptime pinger, a cron ping) touches the app. The check itself is throttled to
once per minute per process.

**3. Duplicate protection at three levels.**
A Postgres advisory lock (across workers/instances), an in-process lock, and the
`MINUTES_BETWEEN_CYCLES` window (default 60) mean overlapping triggers can never
double-scrape.

**4. Observability.** `GET /scheduler/status` returns JSON with the last cycle
time, the latest slot, whether a cycle is due, and the next run of each job.

With this in place scheduling works *without* any paid cron service — but the
scrape happens **at the next request after the slot**, not exactly at 3 AM. To
get exact times, keep the service awake or trigger it externally:

### Optional: hit the slots exactly on time

Pick **one**:

- **Uptime pinger on `/healthz` (free, simplest).** Point UptimeRobot /
  cron-job.org / BetterStack at `https://<your-app>/healthz` every 10 minutes.
  The service never sleeps, so the in-process scheduler fires exactly at
  03:00, 08:00, 14:00, 17:00, 21:00 IST. (Note: this burns free instance hours.)

- **Cron pinger on `/cron/refresh` (free).** Schedule a GET of
  `https://<your-app>/cron/refresh?token=<CRON_TOKEN>` at the five slot times.
  IST → UTC: `30 21,2,8,11,15 * * *`. Each hit wakes the service and starts one
  cycle. A ready-made GitHub Actions workflow can live at
  `.github/workflows/scheduled-refresh.yml` (add it via the GitHub web UI —
  automation can't push workflow files without the `workflows` permission).
  Then set repo **variable** `RENDER_APP_URL` and repo **secret** `CRON_TOKEN`.

- **Render cron job (paid, ~$1/mo).** Uncomment `product-tracker-cron` in
  `render.yaml` and set `ENABLE_SCHEDULER=false` on the web service. Use
  `python3 scheduler.py --run-now`, or `--if-due` if you want it to skip slots
  that were already covered by a catch-up run.

### Environment variables

| Variable | Default | Purpose |
| --- | --- | --- |
| `ENABLE_SCHEDULER` | `true` | In-process APScheduler (fires only while awake). |
| `CATCH_UP_ON_WAKE` | `true` | Run missed slots on the next incoming request. |
| `CATCH_UP_GRACE_MINUTES` | `2` | Ignore a slot this long after it passes, letting the in-process scheduler take it first. |
| `MINUTES_BETWEEN_CYCLES` | `60` | Minimum gap between cycles; dedupes overlapping triggers. |
| `CRON_TOKEN` | *(unset)* | If set, `/cron/refresh` requires `?token=<value>`. |

### Endpoints

| Route | Purpose |
| --- | --- |
| `GET /healthz` | Liveness probe / keep-alive target. Also runs the catch-up check. |
| `GET /scheduler/status` | JSON scheduler diagnostics. |
| `GET|POST /cron/refresh` | Start a scrape cycle now (token-protected). |
| `POST /refresh` | Manual "Refresh All" — scrapes inline. |

### Notes

- Free web services restart at any time and lose their local filesystem — the
  Postgres database is the only durable store, which is why all scheduler state
  lives there alongside the price history.

### Tests
```bash
python3 test_price_stats.py              # All 3 cases
python3 test_price_stats.py --case 1     # Highest price test
python3 test_price_stats.py --case 2     # Average price test
python3 test_scheduler_catchup.py        # Wake-up catch-up scheduler logic (no DB needed)
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
├── scheduler.py          # APScheduler: auto-rescrape + graphs (--if-due for cron)
├── job_state.py          # Durable scheduler state in Postgres + advisory lock
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
