# Code Review — Product Price Tracker

Reviewed branch `arena/019fda90-product-price-tracker` at commit `c1dfa6a`.

**Verdict:** Solid structure and a genuinely thoughtful scraper (layered HTTP strategies + site-specific parsers + fallbacks). The main issues are one **critical CLI bug**, a few **correctness bugs around graph file paths**, **non-portable hardcoded paths** that break the Docker/Render deployment, **N+1 query patterns**, and some **security hygiene gaps**. Nothing here blocks the app from working in local dev, but several things will bite on deployment.

---

## ✅ Fixes applied (follow-up)

These changes are committed on this branch:

1. **`--delete <url>` fixed** — `args.deleted` → `args.delete` in `product_tracker.py` (was raising `AttributeError`).
2. **Portable paths** — `scheduler.py` and `app.py` now derive `BASE_DIR`/`GRAPH_DIR`/`LOG_FILE` from `__file__` instead of hardcoded `/home/user`; `app.py` also `makedirs` the graph dir at startup. Works in Docker/Render now.
3. **Dead `graph_exists` logic removed** — `app.product_detail` no longer computes a graph path that never matched the actual filename scheme.
4. **`get_all_products(limit)` honored** — `LIMIT` added to the SQL so the index page stops fetching the whole table.
5. **`ensure_db` now retries** — `init_db()` re-raises on failure so `app.ensure_db` leaves `_db_initialized` unset and retries on the next request.
6. **`secret_key` from env** — falls back to the old value only when `SECRET_KEY` isn't set.
7. **Server-side guard on `/delete-all`** — now requires a `confirm=yes` form field in addition to the JS confirmation.
8. **Unused imports / dead code removed** — `json`/`time`/`random`/`datetime` in `product_tracker.py`, `time` + unused stats imports + dead `get_price_history_for_url` in `scheduler.py`, `urljoin` in `scraper.py`, `io`/`sys`/`get_all_price_stats` in `app.py`, `getpass`/`sys` in `pg_setup.py`, unused `expected_chg` in `test_price_stats.py`.
9. **CI runs all 3 test cases** — `.github/workflows/ci.yml` now runs `test_price_stats.py` (all cases), matching the README.

Still **not** addressed (larger refactors / scope): N+1 stats queries (batch aggregate), keying routes by product `id` instead of full URL, CSRF tokens, default `changeme123` credentials, and dedup of unchanged-price readings.

---

## 🔴 Critical bug

### 1. `--delete <url>` is completely broken — `product_tracker.py:363`
```python
if args.delete:
    deleted = delete_product(url=args.deleted)   # <-- args.deleted
```
argparse exposes the `--delete` flag as `args.delete`, but the code reads `args.deleted`. Confirmed at runtime:
```
AttributeError: 'Namespace' object has no attribute 'deleted'. Did you mean: 'delete'?
```
The print line right below it correctly uses `args.delete`, so this is a typo. **Fix: use `args.delete`.** (Note `--delete-id` and `--delete-all` work correctly, and `app.py`'s `delete_product` callers are fine.)

---

## 🟠 Bugs / correctness

### 2. Graph filename mismatch — `app.py` vs `scheduler.py`
- `scheduler.generate_graph()` saves files named `price_history_{product_name}.png` (sanitized from the *product name*).
- `app.product_detail()` checks for `price_history_{url.split('/')[-1][:40]}.png` (built from the *URL slug*).

These almost never match, so the `graph_exists` pre-check is effectively dead (the "No price data yet" state won't reflect reality). The `/graph/<url>` route works around it by regenerating on demand, but the dead pre-check should either be removed or use the same naming scheme. Bonus fragility: `url.split('/')[-1]` breaks for URLs ending in `/`.

### 3. Hardcoded absolute paths break Docker & Render — `scheduler.py`, `app.py`
`scheduler.py` has `BASE_DIR = "/home/user"`, `GRAPH_DIR = "/home/user/price_graphs"`, `LOG_FILE = "/home/user/scheduler.log"`, and `app.py` has `GRAPH_DIR = "/home/user/price_graphs"`. These are machine-specific and won't resolve in:
- **Docker** (`WORKDIR /app`, runs as root — writes end up in `/home/user` which the image never mounts).
- **Render free** (no guaranteed `/home/user`).

Use paths relative to the module (`os.path.dirname(__file__)`) or an env var, and create the dir at startup in both apps consistently.

### 4. `get_all_products(limit)` ignores `limit` — `app.py`
The signature accepts `limit=100` but the SQL has **no `LIMIT` clause**, so the parameter does nothing (and the index page can pull the entire table).

### 5. `ensure_db` never retries DB failures — `app.py`
`init_db()` in `product_tracker.py` swallows its own exceptions and always returns normally. `ensure_db()` then sets `_db_initialized = True` unconditionally. If the DB is unreachable on the first request, the app silently proceeds with no table and every later query errors out, with no retry.

### 6. N+1 query patterns — `app.py index`, `price_stats.get_all_price_stats`
- `index()` calls `get_price_stats()` once per product, each opening a fresh DB connection.
- `get_all_price_stats()` loops URLs calling `get_price_stats()` **and** `get_latest_change()` per URL, each opening its own connection.

For a handful of products this is fine, but it multiplies connections as the list grows. Worth a single aggregate query.

### 7. URLs-as-path-parameters are fragile
`/product/<path:url>`, `/delete/<path:url>`, `/graph/<path:url>`, and the form `action`s embed the full URL into the path. If a stored URL contains `?`, `&`, or `#` (e.g. a Flipkart/generic deep link that wasn't cleaned), these links and form submissions will break. Consider keying routes by product `id` instead.

---

## 🟡 Security / hygiene

### 8. Hardcoded `secret_key` — `app.py`
`app.secret_key = "product-tracker-secret-key"`. Fine for a local toy, but should come from an env var for anything shared.

### 9. No CSRF protection on state-changing endpoints
`/add`, `/refresh`, `/delete`, `/delete-id`, `/delete-all` are unauthenticated `POST`s with no CSRF token. `/delete-all` wipes the entire table and is protected only by a `confirm()` JS dialog on the button — not by the server. For a personal tool this is low risk, but worth a CSRF token if exposed beyond localhost.

### 10. Default credentials everywhere
`changeme123` appears as the DB password default in `product_tracker.py`, `setup.sh`, `pg_setup.py`, `docker-compose.yml`, and the CI workflow. Anyone cloning the repo knows the default password; fine for local, but a risk if the docker-compose ever gets deployed as-is.

### 11. Silent exception swallowing
`/refresh` catches per-URL exceptions with a bare `pass` (no log), and `init_db` logs but continues. Errors are invisible to operators.

---

## ⚪ Code quality / dead code

- **Dead functions:** `scheduler.get_price_history_for_url()` (defined, never called — `generate_graph` uses `price_stats.get_price_history`), and `app.py /delete-id` route (no UI links to it).
- **Unused imports** (from pyflakes): `io`, `sys`, `get_all_price_stats` in `app.py`; `json`, `time`, `random`, `datetime` in `product_tracker.py`; `time`, `get_price_stats`, `get_latest_change`, `print_price_stats` in `scheduler.py`; `urljoin` in `scraper.py`; `getpass`, `sys` in `pg_setup.py`.
- **F-strings with no placeholders** (`f"..."`) in `pg_setup.py`, `price_stats.py`, `product_tracker.py`, `scheduler.py`, `test_price_stats.py` — harmless but should be plain strings.
- **`test_price_stats.py`:** `expected_chg` is assigned but never used; the code checks for `"expected_changes"` which never exists in the expected dicts, so the change-% verification path is dead.
- **CI vs README mismatch:** README says "All 3 cases", but `.github/workflows/ci.yml` runs only `--case 1`.
- **`scraper._extract_generic`** returns `currency=None` even when it matched `$`/`€`/`£`, so non-INR prices are still saved as `"INR"` in the DB.
- **Duplicate readings accumulate:** every scrape inserts a new row even when the price is unchanged; there's no unique constraint on `(url, scraped_at)` and no dedup. History tables grow with redundant rows over time.

---

## ✅ What's good

- **Scraper architecture is genuinely well layered:** curl_cffi → cloudscraper → plain requests, with retries/backoff, error-page detection, deep-link resolution, and per-site parsers with sensible fallbacks (Amazon mobile site, Myntra API, URL-slug). This is the strongest part of the codebase.
- **Clean module separation:** `scraper` (fetch/extract) / `product_tracker` (DB+CLI) / `price_stats` (statistics) / `scheduler` (cron+graphs) / `app` (web).
- **Good CLI ergonomics:** positional URLs plus `--list`, `--search`, `--history`, `--export`, `--delete*`.
- **Auto-created tables/indexes** on startup, dual `psycopg2`/`psycopg` fallback in `get_conn`.
- **README** is clear and complete; template escaping is handled by Jinja autoescape.

---

## Priority fix list

1. Fix the `args.deleted` → `args.delete` typo (line 363). *(one-line, unblocks `--delete`)*
2. Make `GRAPH_DIR`/`BASE_DIR`/`LOG_FILE` portable and shared between `app.py` and `scheduler.py`.
3. Align (or remove) the dead `graph_exists` pre-check with the actual graph naming.
4. Respect `limit` in `get_all_products`; reduce the N+1 stats queries.
5. Move `secret_key` and DB password to env vars; add a server-side guard on `/delete-all`.

---

## 🔍 Follow-up: Myntra / AJIO / Flipkart prices not fetching (investigation + fix)

**Report:** "Only Amazon fetches the price; Myntra, AJIO and Flipkart don't."

**Important caveat:** This sandbox has **no outbound internet** (even `google.com`/`wikipedia.org` return HTTP 000), so I could **not live-verify** against the real sites here. I diagnosed the parsers from the code + the current, confirmed DOM/JSON structures of each site (found via web research) and verified the fixes against realistic HTML samples. Please re-test on a machine that can reach these sites.

### Root causes found in `scraper.py`

1. **Myntra parser was stale.** `_extract_myntra` only hunted for a `window.__INITIAL_DATA__ = {...}` blob and raw-HTML regexes. Myntra no longer ships that blob on product pages, and the parser **never used Myntra's real DOM classes** (`h1.pdp-title`, `h2.pdp-brand`, `span.pdp-price`) — so it routinely failed to find the price.

2. **Structural bug in `extract_product_info` (affects all sites).** It returned on the *first* parser result that had `name OR price`. So when a site parser extracted the name but missed the price, it returned immediately and the generic `₹`-regex fallback — which *would* have found the price — never ran. This is the most likely reason you saw "name but no price."

3. **Flipkart price regex grabbed the wrong number.** `_extract_flipkart` used "first `₹` in the whole page text," which can pick up an EMI/MRP/other figure instead of the selling price. Flipkart's selling price is in `div._30jeq3`; the title is in `span.B_NuCI`.

4. **AJIO parser was generic-only.** `_extract_ajio` had no AJIO-specific price selector (just "first ₹"), so it relied on luck / the generic fallback.

### Fixes applied (in `scraper.py`)

- **`_extract_myntra`**: now reads brand from `h2.pdp-brand`, name from `h1.pdp-title`/`pdp-name`, and the **discounted selling price** from `span.pdp-price..._discount` (falls back to any `span.pdp-price`, then the old regexes). Verified: name "Roadster Striped Oversized Casual Shirt" + price ₹593 (not MRP ₹1,799).
- **`_extract_flipkart`**: now reads title from `span.B_NuCI` and the selling price from `div._30jeq3`. Verified: ₹329 (not MRP ₹499).
- **`_extract_ajio`**: added AJIO price selectors (`span.prod-price`, `div.prod-price`, `span.price`, `div.offer-price`, etc.). Verified: ₹599.
- **`extract_product_info`**: rewritten to **merge** the best name/price/currency across JSON-LD, meta, the site parser, *and* generic, instead of short-circuiting. Verified: name from one parser + price from generic now merge correctly.
- **Myntra API fallback** in `scrape()` now also triggers when the *price* is missing (not just the name), so it can backfill the price.

### Still worth checking on your machine (fetch-level, not verifiable here)
Myntra/AJIO/Flipkart all sit behind aggressive bot protection (Akamai / Myntra & AJIO custom JS challenges). Even with correct parsing, the initial fetch can return a bot/maintenance shell. If a particular URL still returns nothing, run:
```bash
python3 scraper.py "https://www.myntra.com/..." --verbose
```
and check whether the failure is `All strategies failed` (network/bot-block = not a parser issue) vs. a parse result with `price=None` (now much rarer after the fixes).

---

## 🔍 Follow-up 2: Your specific URLs (Myntra / AJIO / Amazon)

You gave four URLs. I ran the scraper on all of them, but **this sandbox blocks every shopping domain** — its network allowlist only permits PyPI/GitHub. I proved it:
- `google.com`, `wikipedia.org`, `httpbin.org` → HTTP `000`
- `amzn.in`, `ajioapps.onelink.me`, `www.myntra.com`, `www.ajio.com`, `www.amazon.in`, `www.flipkart.com` → HTTP `000`
- Every strategy (`curl_cffi`, `cloudscraper`, `requests`) fails at the TLS handshake: `BoringSSL SSL_connect: Connection closed abruptly (SSL_ERROR_SYSCALL)`.

So I could not live-verify these exact URLs. **Please run these on your machine** (which can reach Amazon):
```bash
python3 scraper.py "https://www.myntra.com/mailers/shoes/teakwood-leathers/teakwood-leathers-men-black-solid-formal-leather-derbys/19318248/buy" --json
python3 scraper.py "https://www.myntra.com/mailers/shoes/converse/converse-unisex-cons-as-1-pro-low-top-sneakers/37374578/buy" --json
python3 scraper.py "https://ajioapps.onelink.me/ybtf/gyth7lgx" --json
python3 scraper.py "https://amzn.in/d/08AYC9b5" --json
```

### What I did add/verify (offline)
1. **New offline test suite** `test_scraper.py` (7 tests, all passing) covering the exact URL shapes you sent:
   - Myntra `/mailers/.../19318248/buy` → parser selects by `myntra` in domain, extracts **discounted** price (e.g. ₹2,099 not ₹3,999 MRP).
   - `ajioapps.onelink.me` deep link → resolves cleanly to `www.ajio.com/.../p/...` (now extracts OneLink's `af_web_dp` param).
   - `amzn.in/d/...` short link → follows redirect and cleans to `https://www.amazon.in/dp/ASIN`.
   - Merge-fix regression test (name from site parser + price from generic).
2. **Improvement:** `resolve_deep_link` now also reads `af_web_dp` (AppsFlyer/OneLink web fallback). Previously it only handled `deep_link_value` and `af_dp` (http-only), so AJIO onelink links kept `?af_dp=ajio://...&af_web_dp=...` tracking params. Since the URL is used as the DB key, that would have fragmented price history. Now it resolves to the clean product URL.
