#!/usr/bin/env python3
"""
AJIO Scraper using Playwright (Firefox) to bypass Akamai bot protection.

Usage:
    python3 playwright_ajio.py <URL>
    python3 playwright_ajio.py <URL> --json
    python3 playwright_ajio.py <URL> --headful
"""
import argparse
import json
import re
import sys
from playwright.sync_api import sync_playwright


def scrape_ajio(url: str, headful: bool = False, timeout_ms: int = 60000) -> dict:
    with sync_playwright() as p:
        browser = p.firefox.launch(headless=not headful)
        context = browser.new_context(
            viewport={"width": 1920, "height": 1080},
            locale="en-IN",
            timezone_id="Asia/Kolkata",
            user_agent=(
                "Mozilla/5.0 (Windows NT 10.0; Win64; x64; rv:133.0) "
                "Gecko/20100101 Firefox/133.0"
            ),
            extra_http_headers={
                "Accept-Language": "en-IN,en;q=0.9,hi;q=0.8",
            },
        )

        page = context.new_page()

        try:
            resp = page.goto(url, wait_until="domcontentloaded", timeout=timeout_ms)
        except Exception as e:
            browser.close()
            raise RuntimeError(f"Failed to load page: {e}")

        # Wait for JS rendering
        page.wait_for_timeout(5000)

        html = page.content()
        final_url = page.url

        # --- Extract product name ---
        name = None
        h1 = page.query_selector("h1")
        if h1:
            name = h1.inner_text().strip()
        if not name:
            title_el = page.query_selector("title")
            if title_el:
                raw_title = title_el.inner_text().strip()
                name = re.sub(r"\s*(online|buy|ajio).*$", "", raw_title, flags=re.I).strip()
        if not name:
            el = page.query_selector(".item-name, .brand-and-name")
            if el:
                name = el.inner_text().strip()

        # --- Extract brand ---
        brand = None
        for sel in [".brand-name", "strong[itemprop='brand']", ".brand"]:
            el = page.query_selector(sel)
            if el:
                brand = el.inner_text().strip()
                break
        if brand and name and brand not in name:
            name = f"{brand} {name}"

        # --- Extract price ---
        price = None
        # Look for MRP / price in visible text
        body_text = page.inner_text("body")
        prices = re.findall(r"₹\s?([\d,]+(?:\.\d+)?)", body_text)
        if prices:
            # AJIO shows MRP first, then discounted. Grab all for user.
            price = prices[0].replace(",", "")

        # Also try structured data
        if not price:
            ld_scripts = page.query_selector_all("script[type='application/ld+json']")
            for s in ld_scripts:
                try:
                    data = json.loads(s.inner_text())
                    if isinstance(data, list):
                        data = data[0] if data else {}
                    offers = data.get("offers", {})
                    if isinstance(offers, list):
                        offers = offers[0] if offers else {}
                    price = offers.get("price") or offers.get("lowPrice")
                    if price:
                        price = str(price).replace(",", "")
                        break
                except Exception:
                    continue

        browser.close()

    result = {
        "name": name,
        "price": price,
        "currency": "INR",
        "source": "playwright-ajio",
        "url": final_url,
    }
    return result


def main():
    parser = argparse.ArgumentParser(description="AJIO Playwright scraper (Firefox)")
    parser.add_argument("url", help="AJIO product URL")
    parser.add_argument("--json", dest="as_json", action="store_true", help="JSON output")
    parser.add_argument("--headful", action="store_true", help="Run with visible browser")
    args = parser.parse_args()

    try:
        result = scrape_ajio(args.url, headful=args.headful)
    except Exception as e:
        print(f"ERROR: {e}", file=sys.stderr)
        sys.exit(1)

    if args.as_json:
        print(json.dumps(result, indent=2, ensure_ascii=False))
    else:
        print("=" * 60)
        print("  AJIO PRODUCT INFO (Playwright/Firefox)")
        print("=" * 60)
        print(f"  Name  : {result.get('name') or '(not found)'}")
        p = result.get("price")
        if p:
            p_str = f"₹{int(float(p)):,}" if str(p).replace(".", "").isdigit() else f"₹{p}"
        else:
            p_str = "(not found)"
        print(f"  Price : {p_str}")
        print(f"  URL   : {result.get('url')}")
        print("=" * 60)


if __name__ == "__main__":
    main()
