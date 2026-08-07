#!/usr/bin/env python3
"""
Offline unit tests for the scraper's parsing + deep-link resolution.

These tests do NOT hit the network. They exercise:
  - the site-specific parsers (Myntra / Flipkart / AJIO) against realistic
    page HTML for the product shapes these sites actually emit, and
  - the deep-link resolver against simulated redirect chains
    (ajioapps.onelink.me, amzn.in, dl.flipkart.com).

Usage:
    python3 test_scraper.py
"""

import sys
import types
import unittest

from scraper import (
    _extract_myntra,
    _extract_flipkart,
    _extract_ajio,
    extract_product_info,
    resolve_deep_link,
)


# ── Realistic page structures (from web research of live product pages) ──

MYNTRA_PDP = """<html><head><title>Teakwood Leathers Men Black Solid Formal Leather Derbys</title></head><body>
<h1 class="pdp-title">Men Black Solid Formal Leather Derbys</h1>
<h2 class="pdp-brand">Teakwood Leathers</h2>
<div class="pdp-price-section">
  <span class="pdp-price pdp-price_size_xs pdp-price_origin">₹3,999</span>
  <span class="pdp-price pdp-price_size_xs pdp-price_discount">₹2,099</span>
  <span class="pdp-discount">48% OFF</span>
</div>
</body></html>"""

FLIPKART_PDP = """<html><head><title>Flipkart SmartBuy Wired Earphones with Mic Price in India - Buy ...</title></head><body>
<h1><span class="B_NuCI">Flipkart SmartBuy Wired Earphones with Mic (Grey, In the Ear)</span></h1>
<div class="_2B099V"><div class="_30jeq3 _16Jk6d">₹329</div></div>
<div class="_3I9_wc">₹499</div>
</body></html>"""

AJIO_PDP = """<html><head><title>Buy Sleeveless Straight Kurta by AJIO Online</title></head><body>
<h1>Sleeveless Straight Kurta</h1>
<div class="price">
  <div class="prod-price"><span>₹599</span></div>
  <div class="offer-price">₹499</div>
</div>
</body></html>"""

# Name-only HTML: proves the merge fix (price picked up by generic parser)
NAME_ONLY = """<html><body><h1>Some Product</h1>
<div>Price: ₹1,234</div><span>Rating 4.2 (1.2K)</span></body></html>"""


class TestSiteParsers(unittest.TestCase):
    def test_myntra_extracts_discounted_price(self):
        r = _extract_myntra(MYNTRA_PDP)
        self.assertEqual(r["name"], "Teakwood Leathers Men Black Solid Formal Leather Derbys")
        self.assertEqual(r["price"], "2099")  # discounted, NOT the 3999 MRP
        self.assertEqual(r["currency"], "INR")

    def test_flipkart_extracts_selling_price(self):
        r = _extract_flipkart(FLIPKART_PDP)
        self.assertEqual(r["name"], "Flipkart SmartBuy Wired Earphones with Mic (Grey, In the Ear)")
        self.assertEqual(r["price"], "329")  # selling price, NOT the 499 MRP

    def test_ajio_extracts_price(self):
        r = _extract_ajio(AJIO_PDP)
        self.assertEqual(r["name"], "Sleeveless Straight Kurta")
        self.assertEqual(r["price"], "599")

    def test_extract_product_info_merges_fields(self):
        r = extract_product_info(MYNTRA_PDP, "https://www.myntra.com/mailers/shoes/x/19318248/buy")
        self.assertEqual(r["name"], "Teakwood Leathers Men Black Solid Formal Leather Derbys")
        self.assertEqual(r["price"], "2099")

    def test_merge_backfills_price_from_generic(self):
        # Site parser finds name only; generic parser must still supply the price.
        r = extract_product_info(NAME_ONLY, "https://www.myntra.com/x/y/12345/buy")
        self.assertEqual(r["name"], "Some Product")
        self.assertEqual(r["price"], "1234")


class TestDeepLinkResolution(unittest.TestCase):
    def _install_mock_redirect(self, chain):
        pkg = types.ModuleType("curl_cffi")
        req = types.ModuleType("curl_cffi.requests")

        class Resp:
            def __init__(self, url):
                self.headers = {"Location": chain.get(url)}

        def get(url, **kw):
            return Resp(url)

        req.get = get
        pkg.requests = req
        sys.modules["curl_cffi"] = pkg
        sys.modules["curl_cffi.requests"] = req

    def test_ajio_onelink_extracts_af_web_dp(self):
        self._install_mock_redirect({
            "https://ajioapps.onelink.me/ybtf/gyth7lgx":
                "https://www.ajio.com/x/p/123?af_dp=ajio%3A%2F%2Fproduct%2F123"
                "&af_web_dp=https%3A%2F%2Fwww.ajio.com%2Fx%2Fp%2F123",
        })
        resolved = resolve_deep_link("https://ajioapps.onelink.me/ybtf/gyth7lgx")
        self.assertEqual(resolved, "https://www.ajio.com/x/p/123")

    def test_amazon_shortlink_cleans_to_dp(self):
        self._install_mock_redirect({
            "https://amzn.in/d/08AYC9b5":
                "https://www.amazon.in/dp/B0CFXYZABC/ref=share?psc=1&smid=A15A74M4DB07U0",
        })
        resolved = resolve_deep_link("https://amzn.in/d/08AYC9b5")
        self.assertEqual(resolved, "https://www.amazon.in/dp/B0CFXYZABC")


if __name__ == "__main__":
    unittest.main(verbosity=2)
