#!/usr/bin/env python3
"""
Universal Web Scraper v3 — Cloudflare Bypass + Deep-link Resolver
==================================================================
Handles: Flipkart, Amazon, Myntra, AJIO, and any generic site.
Features:
  • curl_cffi TLS fingerprint impersonation (best Cloudflare/Akamai bypass)
  • cloudscraper JS challenge solver (fallback)
  • requests with browser-like headers (last resort)
  • Deep-link / short-link resolution (apps.onelink.me, amzn.in, dl.flipkart.com)
  • Flipkart dl-link URL repair (dl.flipkart.com/dlhttp://...)
  • Amazon mobile site fallback (less bot protection)
  • Retry with exponential backoff on 429/529/403
  • Site-specific parsers: Flipkart, Amazon, Myntra, AJIO, generic
  • JSON-LD and meta-tag extraction as universal fallbacks

Usage:
    python3 scraper.py <URL>
    python3 scraper.py <URL> --json
    python3 scraper.py <URL> --verbose
"""

import argparse
import json
import re
import sys
import time
import random
from urllib.parse import urlparse, urljoin, unquote, parse_qs

# ──────────────────────────────────────────────────────────────────────────────
# 1.  HTTP CLIENT LAYER
# ──────────────────────────────────────────────────────────────────────────────

USER_AGENTS = [
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
    "(KHTML, like Gecko) Chrome/131.0.0.0 Safari/537.36",
    "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 "
    "(KHTML, like Gecko) Chrome/131.0.0.0 Safari/537.36",
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64; rv:133.0) Gecko/20100101 Firefox/133.0",
    "Mozilla/5.0 (Linux; Android 13; SM-S918B) AppleWebKit/537.36 "
    "(KHTML, like Gecko) Chrome/131.0.0.0 Mobile Safari/537.36",
    "Mozilla/5.0 (iPhone; CPU iPhone OS 18_2 like Mac OS X) AppleWebKit/605.1.15 "
    "(KHTML, like Gecko) Version/18.2 Mobile/15E148 Safari/604.1",
]

MOBILE_UA = (
    "Mozilla/5.0 (Linux; Android 13; SM-S918B) AppleWebKit/537.36 "
    "(KHTML, like Gecko) Chrome/131.0.0.0 Mobile Safari/537.36"
)

COMMON_HEADERS = {
    "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,"
              "image/avif,image/webp,image/apng,*/*;q=0.8",
    "Accept-Language": "en-IN,en;q=0.9,hi;q=0.8",
    "Accept-Encoding": "gzip, deflate, br",
    "Connection": "keep-alive",
    "Upgrade-Insecure-Requests": "1",
    "Sec-Fetch-Dest": "document",
    "Sec-Fetch-Mode": "navigate",
    "Sec-Fetch-Site": "none",
    "Sec-Fetch-User": "?1",
    "Cache-Control": "max-age=0",
}


def _random_headers(mobile: bool = False) -> dict:
    h = COMMON_HEADERS.copy()
    if mobile:
        h["User-Agent"] = MOBILE_UA
    else:
        h["User-Agent"] = random.choice(USER_AGENTS)
    return h


# ---------- Deep-link resolver ----------

def _repair_flipkart_dl_url(url: str) -> str:
    """Fix malformed Flipkart dl-links: dl.flipkart.com/dlhttp://m.flipkart.com/..."""
    m = re.search(r'dl(https?://(?:m\.|www\.)?flipkart\.com/.+)', url)
    if m:
        return m.group(1).replace("m.flipkart.com", "www.flipkart.com")
    return url


def _clean_amazon_url(url: str) -> str:
    """Strip tracking params from Amazon URLs, keep only /dp/ASIN."""
    m = re.search(r'(amazon\.\w+/dp/[A-Z0-9]+)', url)
    if m:
        return "https://www." + m.group(1)
    m = re.search(r'(amazon\.\w+/gp/aw/d/[A-Z0-9]+)', url)
    if m:
        return "https://www." + m.group(1)
    return url


def resolve_deep_link(url: str, verbose: bool = False) -> str:
    """Follow redirects, extract real URL from deep-link params, repair malformed URLs."""
    from curl_cffi import requests as cffi_requests
    if verbose:
        print(f"[*] Resolving deep link: {url}")

    try:
        resp = cffi_requests.get(
            url, headers=_random_headers(), impersonate="chrome131",
            timeout=20, allow_redirects=False,
        )
    except Exception as e:
        if verbose:
            print(f"  [!] Initial request failed: {e}")
        return url

    final_url = url
    for _ in range(10):
        loc = resp.headers.get("Location", "")
        if not loc:
            break

        parsed = urlparse(loc)
        qs = parse_qs(parsed.query)

        if "deep_link_value" in qs:
            real = unquote(qs["deep_link_value"][0])
            if verbose:
                print(f"  [+] Found deep_link_value: {real}")
            return real
        if "af_dp" in qs:
            real = unquote(qs["af_dp"][0])
            if real.startswith("http"):
                if verbose:
                    print(f"  [+] Found af_dp: {real}")
                return real

        final_url = loc
        if verbose:
            print(f"  [→] Following: {loc[:120]}...")

        try:
            resp = cffi_requests.get(
                loc, headers=_random_headers(), impersonate="chrome131",
                timeout=20, allow_redirects=False,
            )
        except Exception:
            break

    final_url = _repair_flipkart_dl_url(final_url)
    final_url = _clean_amazon_url(final_url)

    if verbose and final_url != url:
        print(f"  [✓] Resolved to: {final_url[:150]}")
    return final_url


# ---------- Fetch strategies ----------

def fetch_with_curl_cffi(url: str, verbose: bool = False, mobile: bool = False) -> tuple[str, str]:
    from curl_cffi import requests as cffi_requests
    if verbose:
        print("[*] Trying curl_cffi (Chrome TLS fingerprint)...")
    resp = cffi_requests.get(
        url, headers=_random_headers(mobile=mobile), impersonate="chrome131",
        timeout=30, allow_redirects=True,
    )
    resp.raise_for_status()
    text = resp.text
    # Handle gzip-compressed responses
    if len(text) < 200 and resp.content[:2] == b'\x1f\x8b':
        import gzip
        text = gzip.decompress(resp.content).decode("utf-8", errors="replace")
    return text, resp.url


def fetch_with_cloudscraper(url: str, verbose: bool = False) -> tuple[str, str]:
    import cloudscraper
    if verbose:
        print("[*] Trying cloudscraper (JS challenge solver)...")
    scraper = cloudscraper.create_scraper(
        browser={"browser": "chrome", "platform": "windows", "mobile": False},
        delay=5,
    )
    resp = scraper.get(url, timeout=30)
    resp.raise_for_status()
    return resp.text, resp.url


def fetch_with_requests(url: str, verbose: bool = False) -> tuple[str, str]:
    import requests
    if verbose:
        print("[*] Trying plain requests (browser-like headers)...")
    session = requests.Session()
    resp = session.get(url, headers=_random_headers(), timeout=30, allow_redirects=True)
    resp.raise_for_status()
    return resp.text, resp.url


def _is_error_page(html: str, domain: str = "") -> bool:
    """Detect bot-detection, maintenance, or error pages."""
    lower = html.lower()
    size = len(html)

    # Obvious error pages (only check when page is suspiciously small)
    if size < 10000:
        if any(kw in lower for kw in [
            "oops", "site maintenance", "something went wrong",
            "access denied",
        ]):
            return True

    # Amazon-specific: bot-detection page is ~3-5KB with captcha reference
    if "amazon" in domain:
        if size < 50000:
            # Small Amazon page = bot detection (real product pages are 300KB+)
            if "captcha" in lower or "automated access" in lower or "producttitle" not in lower:
                return True
        # Check for explicit bot-detection markers regardless of size
        if "captcha" in lower and "producttitle" not in lower:
            return True

    # Myntra/AJIO maintenance pages
    if size < 600 and any(s in domain for s in ["myntra", "ajio"]):
        if "site maintenance" in lower or "access denied" in lower:
            return True

    return False


def fetch_page(url: str, verbose: bool = False, retries: int = 3,
               mobile: bool = False) -> tuple[str, str]:
    """Try each strategy with retry + exponential backoff."""
    domain = urlparse(url).netloc.lower()
    strategies = [
        ("curl_cffi", lambda u, verbose=False: fetch_with_curl_cffi(u, verbose=verbose, mobile=mobile)),
        ("cloudscraper", fetch_with_cloudscraper),
        ("requests", fetch_with_requests),
    ]

    last_err = None
    for attempt in range(retries):
        if attempt > 0:
            wait = 2 ** attempt + random.uniform(0.5, 2.0)
            if verbose:
                print(f"  [⟳] Retry {attempt + 1}/{retries} — waiting {wait:.1f}s...")
            time.sleep(wait)

        for name, fn in strategies:
            try:
                html, final_url = fn(url, verbose=verbose)
                if _is_error_page(html, domain):
                    raise RuntimeError(f"Got error/maintenance page ({len(html)} bytes)")
                if verbose:
                    print(f"  [+] Success with {name}  ({len(html):,} bytes)")
                return html, final_url
            except Exception as e:
                last_err = e
                if verbose:
                    print(f"  [-] {name} failed: {e}")
                if any(code in str(e) for code in ["529", "429", "403"]):
                    break
                time.sleep(0.5)

    raise RuntimeError(f"All strategies failed after {retries} retries. Last: {last_err}")


# ──────────────────────────────────────────────────────────────────────────────
# 2.  EXTRACTION LAYER
# ──────────────────────────────────────────────────────────────────────────────

def _find_jsonld(html: str) -> list[dict]:
    from bs4 import BeautifulSoup
    soup = BeautifulSoup(html, "lxml")
    blocks = []
    for tag in soup.find_all("script", type="application/ld+json"):
        try:
            data = json.loads(tag.string or "")
            if isinstance(data, list):
                blocks.extend(data)
            elif isinstance(data, dict):
                blocks.append(data)
        except (json.JSONDecodeError, TypeError):
            continue
    return blocks


def _extract_from_jsonld(html: str) -> dict | None:
    for block in _find_jsonld(html):
        btype = block.get("@type", "")
        if btype == "Product" or (isinstance(btype, list) and "Product" in btype):
            name = block.get("name")
            offers = block.get("offers", {})
            price, currency = None, None
            if isinstance(offers, list):
                offers = offers[0] if offers else {}
            if isinstance(offers, dict):
                price = offers.get("price") or offers.get("lowPrice")
                currency = offers.get("priceCurrency", "INR")
            return {"name": name, "price": price, "currency": currency, "source": "json-ld"}
    return None


def _extract_from_meta(html: str) -> dict | None:
    from bs4 import BeautifulSoup
    soup = BeautifulSoup(html, "lxml")
    name = soup.find("meta", property="og:title")
    price = soup.find("meta", property="product:price:amount")
    currency = soup.find("meta", property="product:price:currency")
    result = {
        "name": name.get("content") if name else None,
        "price": price.get("content") if price else None,
        "currency": currency.get("content") if currency else None,
        "source": "meta-tags",
    }
    return result if (result["name"] or result["price"]) else None


# ---------- Site-specific parsers ----------

def _extract_flipkart(html: str) -> dict | None:
    from bs4 import BeautifulSoup
    soup = BeautifulSoup(html, "lxml")
    name = None
    h1 = soup.find("h1")
    if h1:
        name = h1.get_text(strip=True)
    if not name:
        t = soup.find("title")
        if t:
            name = re.sub(r"\s*(Online at Best Price.*|Buy.*Flipkart.*)$", "",
                          t.get_text(strip=True), flags=re.I)
    price = None
    text = soup.get_text(" ", strip=True)
    prices = re.findall(r"₹\s?([\d,]+(?:\.\d+)?)", text)
    if prices:
        price = prices[0].replace(",", "")
    if name or price:
        return {"name": name, "price": price, "currency": "INR", "source": "flipkart-specific"}
    return None


def _extract_amazon(html: str) -> dict | None:
    from bs4 import BeautifulSoup
    soup = BeautifulSoup(html, "lxml")
    name = None
    # Try standard selectors
    title_el = soup.find("span", id="productTitle")
    if title_el:
        name = title_el.get_text(strip=True)
    # Fallback: h1 tag (mobile site)
    if not name:
        h1 = soup.find("h1")
        if h1:
            name = h1.get_text(strip=True)
    # Fallback: title tag
    if not name:
        t = soup.find("title")
        if t:
            txt = t.get_text(strip=True)
            if txt and "amazon.in" not in txt.lower():
                name = txt

    price = None
    # 1) Best: priceAmount in JSON data (always the actual selling price)
    m = re.search(r'"priceAmount"\s*:\s*([\d.]+)', html)
    if m:
        price = str(int(float(m.group(1))))

    # 2) priceToPay class (the actual price, not MRP)
    if not price:
        ptp = soup.find(class_=re.compile(r"priceToPay|apex-price"))
        if ptp:
            m = re.search(r"[\d,]+(?:\.\d+)?", ptp.get_text())
            if m:
                price = m.group().replace(",", "").rstrip(".")

    # 3) Fallback: first ₹ in text (skip MRP if we can)
    if not price:
        text = soup.get_text(" ", strip=True)
        prices = re.findall(r"₹\s?([\d,]+(?:\.\d+)?)", text)
        if prices:
            price = prices[0].replace(",", "")

    # 4) Last resort: a-offscreen spans
    if not price:
        for el in soup.find_all("span", class_="a-offscreen"):
            m = re.search(r"[\d,]+(?:\.\d+)?", el.get_text())
            if m:
                price = m.group().replace(",", "")
                break

    if name or price:
        return {"name": name, "price": price, "currency": "INR", "source": "amazon-specific"}
    return None


def _extract_myntra(html: str) -> dict | None:
    name, price = None, None
    m = re.search(r'window\.__INITIAL_DATA__\s*=\s*({.+?})\s*;?\s*</script>', html, re.S)
    if m:
        try:
            data = json.loads(m.group(1))
            pdp = data.get("pdpData") or data.get("product") or data
            name = pdp.get("name") or pdp.get("productName")
            brand = pdp.get("brand", {})
            brand_name = brand.get("name") if isinstance(brand, dict) else brand
            if brand_name and name:
                name = f"{brand_name} {name}"
            pi = pdp.get("price") or pdp.get("discountedPrice") or {}
            if isinstance(pi, dict):
                price = pi.get("discounted") or pi.get("value")
            elif isinstance(pi, (int, float, str)):
                price = pi
        except (json.JSONDecodeError, KeyError, TypeError):
            pass
    if not name:
        m = re.search(r'"productName"\s*:\s*"([^"]+)"', html)
        if m:
            name = m.group(1)
    if not price:
        m = re.search(r'"discountedPrice"\s*:\s*"?(\d+)"?', html)
        if m:
            price = m.group(1)
    if not price:
        m = re.search(r'"price"\s*:\s*"?(\d+)"?', html)
        if m:
            price = m.group(1)
    if name or price:
        return {"name": name, "price": price, "currency": "INR", "source": "myntra-specific"}
    return None


def _extract_ajio(html: str) -> dict | None:
    from bs4 import BeautifulSoup
    soup = BeautifulSoup(html, "lxml")
    name = None
    h1 = soup.find("h1")
    if h1:
        name = h1.get_text(strip=True)
    if not name:
        t = soup.find("title")
        if t:
            name = re.sub(r"\s*(online|buy|ajio).*$", "", t.get_text(strip=True), flags=re.I)
    price = None
    text = soup.get_text(" ", strip=True)
    prices = re.findall(r"₹\s?([\d,]+(?:\.\d+)?)", text)
    if prices:
        price = prices[0].replace(",", "")
    if name or price:
        return {"name": name, "price": price, "currency": "INR", "source": "ajio-specific"}
    return None


def _extract_generic(html: str) -> dict:
    from bs4 import BeautifulSoup
    soup = BeautifulSoup(html, "lxml")
    name = None
    h1 = soup.find("h1")
    if h1:
        name = h1.get_text(strip=True)
    if not name:
        t = soup.find("title")
        if t:
            name = t.get_text(strip=True)
    price = None
    text = soup.get_text(" ", strip=True)
    for pat in [r"₹\s?([\d,]+(?:\.\d+)?)", r"\$\s?([\d,]+(?:\.\d+)?)",
                r"€\s?([\d,]+(?:\.\d+)?)", r"£\s?([\d,]+(?:\.\d+)?)"]:
        m = re.search(pat, text)
        if m:
            price = m.group(1).replace(",", "")
            break
    return {"name": name, "price": price, "currency": None, "source": "generic-fallback"}


SITE_PARSERS = {
    "flipkart": _extract_flipkart,
    "amazon":   _extract_amazon,
    "myntra":   _extract_myntra,
    "ajio":     _extract_ajio,
}


def extract_product_info(html: str, final_url: str) -> dict:
    domain = urlparse(final_url).netloc.lower()

    r = _extract_from_jsonld(html)
    if r and r.get("name") and r.get("price"):
        return r

    r = _extract_from_meta(html)
    if r and r.get("name") and r.get("price"):
        return r

    for key, parser in SITE_PARSERS.items():
        if key in domain:
            r = parser(html)
            if r and (r.get("name") or r.get("price")):
                return r

    return _extract_generic(html)


# ──────────────────────────────────────────────────────────────────────────────
# 3.  SITE-SPECIFIC FALLBACKS
# ──────────────────────────────────────────────────────────────────────────────

def _amazon_mobile_fallback(url: str, verbose: bool = False) -> dict | None:
    """Amazon desktop often blocks bots; try mobile site which is less protected."""
    asin_m = re.search(r'(?:dp|aw/d)/([A-Z0-9]{10})', url)
    if not asin_m:
        return None
    asin = asin_m.group(1)
    mobile_url = f"https://www.amazon.in/gp/aw/d/{asin}"
    if verbose:
        print(f"[*] Trying Amazon mobile fallback: {mobile_url}")
    try:
        html, _ = fetch_with_curl_cffi(mobile_url, verbose=False, mobile=True)
        if not _is_error_page(html, "amazon") and len(html) > 5000:
            r = _extract_amazon(html)
            if r and r.get("name"):
                r["source"] = "amazon-mobile"
                return r
    except Exception as e:
        if verbose:
            print(f"  [-] Amazon mobile failed: {e}")
    return None


def _myntra_api_fallback(url: str, verbose: bool = False) -> dict | None:
    """Try Myntra's internal API endpoints."""
    m = re.search(r"/(\d+)(?:\?|$)", url)
    if not m:
        return None
    pid = m.group(1)
    if verbose:
        print(f"[*] Trying Myntra API for product {pid}...")

    headers = _random_headers()
    headers.update({
        "Accept": "application/json",
        "x-location-context": "pincode=560001;source=IP",
        "x-meta-app": "channel=web",
    })

    api_urls = [
        f"https://www.myntra.com/gateway/v2/product/detail/{pid}",
        f"https://www.myntra.com/gateway/v3/product/{pid}",
    ]

    for api_url in api_urls:
        try:
            from curl_cffi import requests as cffi_requests
            resp = cffi_requests.get(api_url, headers=headers, impersonate="chrome131", timeout=20)
            if resp.status_code != 200:
                continue
            # Check if it's actually JSON (not maintenance HTML)
            if resp.text.strip().startswith("<"):
                if verbose:
                    print(f"  [-] {api_url} returned HTML (maintenance mode)")
                continue
            data = resp.json()
            pdp = data.get("pdpData") or data.get("product") or data
            name = pdp.get("name") or pdp.get("productName")
            brand = pdp.get("brand", {})
            brand_name = brand.get("name") if isinstance(brand, dict) else brand
            if brand_name and name:
                name = f"{brand_name} {name}"
            pi = pdp.get("price") or {}
            if isinstance(pi, dict):
                price = pi.get("discounted") or pi.get("value")
            else:
                price = pi
            if name or price:
                return {"name": name, "price": price, "currency": "INR", "source": "myntra-api"}
        except Exception as e:
            if verbose:
                print(f"  [-] {api_url} failed: {e}")
    return None


def _ajio_fallback(url: str, verbose: bool = False) -> dict | None:
    """Extract product info from the resolved AJIO URL path."""
    # AJIO blocks all server-side requests via Akamai.
    # As a best-effort, parse the URL slug for product name.
    m = re.search(r'ajio\.com/([^/]+)/p/\d+', url)
    if m:
        slug = m.group(1).replace("-", " ").title()
        pid_m = re.search(r'/p/(\d+)', url)
        result = {"name": slug, "price": None, "currency": "INR", "source": "ajio-url-slug"}
        if verbose:
            print(f"[*] Extracted from AJIO URL slug: {slug}")
        return result
    return None


def _amazon_web_search_fallback(url: str, verbose: bool = False) -> dict | None:
    """Last resort: use Google search to find Amazon product name & price."""
    asin_m = re.search(r'(?:dp|aw/d)/([A-Z0-9]{10})', url)
    if not asin_m:
        return None
    asin = asin_m.group(1)
    if verbose:
        print(f"[*] Trying web search fallback for ASIN: {asin}")

    try:
        import subprocess
        # Use curl to hit a search engine
        query = f"amazon.in {asin} price"
        search_url = f"https://www.google.com/search?q={query.replace(' ', '+')}"
        result = subprocess.run(
            ["curl", "-sL", "-H", "User-Agent: Mozilla/5.0", search_url],
            capture_output=True, text=True, timeout=10,
        )
        html = result.stdout

        # Extract price from search results
        # Look for ₹ pattern near the ASIN
        prices = re.findall(r'₹\s?([\d,]+(?:\.\d+)?)', html)
        if prices:
            # Take the most common price (likely the selling price)
            from collections import Counter
            clean_prices = [p.replace(",", "") for p in prices]
            most_common = Counter(clean_prices).most_common(1)[0][0]
            return {"name": None, "price": most_common, "currency": "INR", "source": "web-search"}
    except Exception as e:
        if verbose:
            print(f"  [-] Web search fallback failed: {e}")
    return None


# ──────────────────────────────────────────────────────────────────────────────
# 4.  MAIN ENTRY POINT
# ──────────────────────────────────────────────────────────────────────────────

def scrape(url: str, verbose: bool = False) -> dict:
    """High-level: resolve → fetch → extract → fallback → return."""
    resolved_url = resolve_deep_link(url, verbose=verbose)
    domain = urlparse(resolved_url).netloc.lower()

    html, final_url = None, resolved_url

    # Step 1: Fetch (with Amazon mobile fallback baked in)
    try:
        html, final_url = fetch_page(resolved_url, verbose=verbose)
    except Exception as e:
        if verbose:
            print(f"[!] Primary fetch failed: {e}")

    # Step 2: Extract
    info = None
    if html:
        info = extract_product_info(html, final_url)
        # Detect error pages masquerading as results
        if info.get("name") and any(kw in info["name"].lower()
                                     for kw in ["oops", "error", "not found",
                                                 "something went wrong", "access denied",
                                                 "site maintenance"]):
            info = None

    # Step 3: Site-specific fallbacks
    if not info or (not info.get("name") and not info.get("price")):
        if "amazon" in domain:
            fb = _amazon_mobile_fallback(resolved_url, verbose=verbose)
            if fb and fb.get("name"):
                info = fb

    # Step 4: Web search fallback for Amazon (last resort)
    if not info or (not info.get("name") and not info.get("price")):
        if "amazon" in domain:
            fb = _amazon_web_search_fallback(resolved_url, verbose=verbose)
            if fb and fb.get("name"):
                info = fb

        if ("myntra" in domain) and (not info or not info.get("name")):
            fb = _myntra_api_fallback(resolved_url, verbose=verbose)
            if fb:
                info = fb

        if ("ajio" in domain) and (not info or not info.get("name")):
            fb = _ajio_fallback(resolved_url, verbose=verbose)
            if fb:
                info = fb

    if info:
        info["url"] = final_url if html else resolved_url
        info["domain"] = urlparse(info["url"]).netloc
        return info

    raise RuntimeError(f"Could not extract product info from {url}")


def main():
    parser = argparse.ArgumentParser(
        description="Universal web scraper with Cloudflare bypass & deep-link resolver",
    )
    parser.add_argument("url", help="URL to scrape")
    parser.add_argument("--json", dest="as_json", action="store_true", help="JSON output")
    parser.add_argument("--verbose", "-v", action="store_true", help="Debug logging")
    args = parser.parse_args()

    try:
        result = scrape(args.url, verbose=args.verbose)
    except Exception as e:
        print(f"ERROR: {e}", file=sys.stderr)
        sys.exit(1)

    if args.as_json:
        print(json.dumps(result, indent=2, ensure_ascii=False))
    else:
        print("=" * 60)
        print("  PRODUCT INFO")
        print("=" * 60)
        print(f"  Name     : {result.get('name') or '(not found)'}")
        p = result.get("price")
        if p:
            p_str = f"₹{int(float(p)):,}" if str(p).replace(".","").isdigit() else f"₹{p}"
        else:
            p_str = "(not found)"
        cur = f"  ({result.get('currency')})" if result.get("currency") else ""
        print(f"  Price    : {p_str}{cur}")
        print(f"  Source   : {result.get('source')}")
        print(f"  Domain   : {result.get('domain')}")
        print(f"  Final URL: {result.get('url')}")
        print("=" * 60)


if __name__ == "__main__":
    main()
