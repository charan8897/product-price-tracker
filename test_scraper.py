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
    _extract_from_embedded_json,
    extract_product_info,
    resolve_deep_link,
    _strip_tracking_params,
    _ajio_api_fallback,
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



class TestAJIOEmbeddedJSON(unittest.TestCase):
    AJIO_PRELOADED = """<html><head><title>Buy brown Jackets &amp; Coats for Men by The Indian Garage Co Online | Ajio.com</title></head><body>
<script>window.__PRELOADED_STATE__ = {"product":{"productDetails":{"name":"Men Regular Fit Printed Winter Jacket","price":{"discounted":1299,"current":1299,"offerPrice":1199,"currency":"INR"}}}};</script>
</body></html>"""

    def test_ajio_preloaded_state_price(self):
        r = _extract_ajio(self.AJIO_PRELOADED)
        self.assertEqual(r["price"], 1299)  # discounted selling price
        self.assertEqual(r["name"], "Men Regular Fit Printed Winter Jacket")

    def test_next_data_price(self):
        html = ('<script id="__NEXT_DATA__" type="application/json">'
                '{"props":{"pageProps":{"product":{"name":"Unisex Sneakers",'
                '"price":{"current":5599,"currency":"INR"}}}}}</script>')
        r = _extract_from_embedded_json(html)
        self.assertEqual(r["price"], 5599)


class TestMyntraEmbeddedJSON(unittest.TestCase):
    MYN = """<html><body><script>window.__INITIAL_DATA__ = {"pdpData":{"name":"Formal Leather Derbys","brand":{"name":"Teakwood Leathers"},"price":{"discounted":2099,"mrp":3999,"currency":"INR"}}};</script></body></html>"""

    def test_myntra_init_data_price(self):
        r = _extract_myntra(self.MYN)
        self.assertEqual(r["price"], 2099)
        self.assertEqual(r["name"], "Formal Leather Derbys")


class TestURLCleaning(unittest.TestCase):
    def test_strips_trailing_question_mark(self):
        self.assertEqual(
            _strip_tracking_params("https://www.ajio.com/a/b/p/123_brown?"),
            "https://www.ajio.com/a/b/p/123_brown")

    def test_strips_tracking_params(self):
        self.assertEqual(
            _strip_tracking_params("https://www.myntra.com/x/1/buy?shared=true&utm_campaign=oGs"),
            "https://www.myntra.com/x/1/buy")

    def test_keeps_amazon_dp(self):
        self.assertEqual(
            _strip_tracking_params("https://www.amazon.in/dp/B0CFXYZABC"),
            "https://www.amazon.in/dp/B0CFXYZABC")



class TestAJIOAPIFallback(unittest.TestCase):
    def test_api_backfills_price(self):
        import sys, types, json
        API = "https://www.ajio.com/api/p/443627735_brown"
        class FakeResp:
            def __init__(self, payload):
                self.status_code = 200
                self.text = json.dumps(payload)
                self._p = payload
            def json(self):
                return self._p
        def fake_get(url, **kw):
            if url == API:
                return FakeResp({
                    "name": "The Indian Garage Co Men Regular Fit Printed Winter Jacket",
                    "price": {"formattedValue": "Rs. 1,299", "value": 1299},
                })
            return FakeResp({})
        pkg = types.ModuleType("curl_cffi"); req = types.ModuleType("curl_cffi.requests")
        req.get = fake_get
        sys.modules["curl_cffi"] = pkg; sys.modules["curl_cffi.requests"] = req

        r = _ajio_api_fallback("https://www.ajio.com/x/p/443627735_brown")
        self.assertEqual(r["price"], "1299")
        self.assertEqual(r["name"], "The Indian Garage Co Men Regular Fit Printed Winter Jacket")
        self.assertEqual(r["source"], "ajio-api")


if __name__ == "__main__":
    unittest.main(verbosity=2)
