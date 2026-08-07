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
├── app.py                # Flask web dashboard
├── scraper.py            # Universal scraper with Cloudflare bypass
├── product_tracker.py    # CLI tool: scrape & save to PostgreSQL
├── scheduler.py          # APScheduler: auto-rescrape + graphs
├── price_stats.py        # Price statistics calculator
├── test_price_stats.py   # Test suite for price stats
├── setup.sh              # First-time setup script
├── requirements.txt      # Python dependencies
└── README.md
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
