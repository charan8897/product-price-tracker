#!/usr/bin/env python3
"""
Diagnose why AJIO prices aren't being fetched.
Run this on a machine that CAN reach the internet (e.g. where Amazon works):
    python3 diagnose_ajio.py "<AJIO product URL>"
It prints exactly what the AJIO server returns at each step so we can see
whether the problem is:
  (1) the fetch is blocked (bot-protection / TLS)  -> network issue
  (2) the price is/ isn't in the HTML              -> parser issue
  (3) the internal API /api/p/... returns price    -> should be backfilled
"""
import sys
import re
import json
URL = (sys.argv[1] if len(sys.argv) > 1
       else "https://www.ajio.com/the-indian-garage-co-men-regular-fit-printed-winter-jacket/p/443627735_brown")
def section(t):
    print("\n" + "=" * 60)
    print("  " + t)
    print("=" * 60)
# 1) Plain fetch
section("STEP 1: Fetch product HTML")
try:
    import requests
    r = requests.get(URL, headers={
        "User-Agent": ("Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
                       "AppleWebKit/537.36 (KHTML, like Gecko) "
                       "Chrome/131.0.0.0 Safari/537.36"),
        "Accept-Language": "en-IN,en;q=0.9",
    }, timeout=30)
    print(f"HTTP {r.status_code}  bytes={len(r.text)}")
    html = r.text
except Exception as e:
    print(f"FETCH FAILED: {type(e).__name__}: {e}")
    print(">> This is a network / bot-protection / TLS issue, NOT a parser bug.")
    sys.exit(1)
# 2) Price in HTML?
section("STEP 2: Is there a price visible in the raw HTML?")
found_price = re.findall(r"₹\s?([\d,]+)", html) or re.findall(r"Rs\.\s?([\d,]+)", html)
if found_price:
    print("Found price text in HTML:", found_price[:10])
else:
    print("No ₹/Rs price text in raw HTML -> price is JS-rendered (expected for AJIO).")
# 3) Embedded JSON blobs?
section("STEP 3: Embedded JS state blobs")
for marker in ("__PRELOADED_STATE__", "__INITIAL_DATA__", "__NEXT_DATA__", "__myx"):
    print(f"  {marker}: {'present' if marker in html else 'absent'}")
# 4) Product code from URL
section("STEP 4: Internal API /api/p/{code}")
m = re.search(r"/p/([^/?#]+)", URL)
code = m.group(1) if m else None
print("product code:", code)
if code:
    api_url = f"https://www.ajio.com/api/p/{code}"
    try:
        ar = requests.get(api_url, headers={
            "User-Agent": ("Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
                           "AppleWebKit/537.36 (KHTML, like Gecko) "
                           "Chrome/131.0.0.0 Safari/537.36"),
            "Accept": "application/json",
        }, timeout=30)
        print(f"API HTTP {ar.status_code}")
        ct = ar.headers.get("Content-Type", "")
        print(f"Content-Type: {ct}")
        if "json" in ct and ar.text.strip().startswith("{"):
            data = ar.json()
            print("  name   =", data.get("name"))
            print("  brand  =", data.get("brandName"))
            price = data.get("price")
            print("  price  =", json.dumps(price))
            if isinstance(price, dict):
                print("    formattedValue =", price.get("formattedValue"))
        else:
            print(">> API returned non-JSON (HTML). First 200 chars:")
            print(ar.text[:200])
    except Exception as e:
        print(f"API FAILED: {type(e).__name__}: {e}")
        print(">> The /api/p/ endpoint itself is blocked (bot-protection from this IP).")
else:
    print("Could not extract a product code from the URL.")
print("\nDONE. Paste this full output back so we can fix the right layer.")

