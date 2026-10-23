"""Engine tests: spec PART L cases, run through the real parser (backend.main.parse_page) and the real engine.

Run:  .venv\\Scripts\\python.exe -m unittest tests.test_seo_engine -v
"""
from __future__ import annotations

import copy
import importlib.util
import json
import logging
import random
import subprocess
import sys
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
logging.disable(logging.CRITICAL)

from backend.main import parse_page  # noqa: E402  (the crawler's own HTML parser)
from backend.seo_engine import run_engine  # noqa: E402
from backend.seo_engine.gate import fabrication_hits, run_gate  # noqa: E402
from backend.seo_engine.narrative import clean_prose  # noqa: E402
from backend.seo_engine.scoring import (WEIGHTS, CheckResult, band, project_potential, round_half_up,  # noqa: E402
                                        score_category, score_site)

BASE = "https://www.example-pumps.lk"
REF_PATH = ROOT / "tests" / "reference" / "seo_scoring_engine.py"
WORDS = ("Our industrial water pumps are built for reliable pressure and flow in factories, farms and buildings across Sri Lanka. " * 40)


def doc(title="Industrial Water Pumps Supplier in Colombo | Example Pumps", desc=None, h1=("Industrial Water Pumps",), h2=("Pump range", "Applications"),
        body=WORDS, head="", imgs=(), lang="en", canonical=True, url=BASE + "/", jsonld=None, extra=""):
    desc = desc if desc is not None else "Industrial water pumps for factories and buildings in Sri Lanka. Specifications, applications and quotes from Example Pumps in Colombo."
    parts = [f'<!doctype html><html lang="{lang}"><head><meta charset="utf-8"><meta name="viewport" content="width=device-width, initial-scale=1">']
    if title is not None:
        parts.append(f"<title>{title}</title>")
    if desc:
        parts.append(f'<meta name="description" content="{desc}">')
    if canonical:
        parts.append(f'<link rel="canonical" href="{url}">')
    if jsonld:
        parts.append(f'<script type="application/ld+json">{json.dumps(jsonld)}</script>')
    parts.append(head + "</head><body><header><nav><a href='/'>Home</a><a href='/water-pumps'>Water Pumps</a><a href='/contact-us'>Contact</a></nav></header><main>")
    parts += [f"<h1>{h}</h1>" for h in h1]
    parts += [f"<h2>{h}</h2><p>{body}</p>" for h in h2] or [f"<p>{body}</p>"]
    parts += [f'<img src="{s}" alt="{a}" width="400" height="300">' if a is not None else f'<img src="{s}" width="400" height="300">' for s, a in imgs]
    parts.append(extra + "</main><footer>Example Pumps</footer></body></html>")
    return "".join(parts)


def page(path: str, html: str, status: int = 200, headers=None) -> dict:
    url = BASE + path
    p = parse_page(url, {"ok": True, "status": status, "url": url, "content_type": "text/html; charset=utf-8", "body": html.encode("utf-8"),
                         "headers": headers or {}, "elapsed_ms": 120, "history": []})
    p["depth"] = 0 if path == "/" else 1
    return p


def probes(hosts="redirect", control=404, http_status=301, missing=(), mobile_words=None, home_title="t", home_h1="h"):
    apex = {"requested": "https://example-pumps.lk/", "status": 200, "final_url": BASE + "/", "first_hop": {"status": 301, "location": BASE + "/"}, "title": home_title, "h1": home_h1, "canonical": ""}
    www = {"requested": BASE + "/", "status": 200, "final_url": BASE + "/", "first_hop": {}, "title": home_title, "h1": home_h1, "canonical": ""}
    if hosts == "dual_same":
        apex = {**apex, "final_url": "https://example-pumps.lk/", "first_hop": {}}
    rows = [{"path": p, "url": BASE + p, "status": 404 if p in missing else 200, "final_url": BASE + p, "redirected": False, "redirected_home": False, "control": False}
            for p in ("/about", "/contact", "/products", "/services", "/blog", "/privacy", "/terms")]
    rows.append({"path": "/x", "url": BASE + "/this-page-does-not-exist-seo-test-55512", "status": control, "final_url": BASE + "/x", "redirected": False,
                 "redirected_home": control == "home", "control": True})
    return {"hosts": {"apex": apex, "www": www},
            "http_redirect": {"requested": "http://www.example-pumps.lk/", "status": 200, "final_url": BASE + "/", "first_hop": {"status": http_status}},
            "probes": rows, "mobile": {"status": 200, "word_count": mobile_words}}


def audit(pages, link_checks=(), real_data=None, robots_content="User-agent: *\nDisallow: /cart\nSitemap: https://www.example-pumps.lk/sitemap.xml"):
    urls = [p["url"] for p in pages]
    return {
        "target": BASE + "/", "created_at": "2026-10-07T00:00:00+00:00", "pages": pages, "link_checks": list(link_checks),
        "real_data": real_data or {},
        "_robots": {"url": BASE + "/robots.txt", "status": 200, "found": True, "content": robots_content, "sitemaps": [BASE + "/sitemap.xml"],
                    "googlebot_allows_root": "Disallow: /\n" not in robots_content + "\n", "googlebot_allows_start": True},
        "_sitemap": {"files": [{"url": BASE + "/sitemap.xml", "status": 200, "type": "urlset", "url_count": len(urls)}], "urls": urls,
                     "lastmod": {u: f"2026-0{1 + i % 9}-1{i % 9}" for i, u in enumerate(urls)}, "detected": ""},
    }


def run(a, **kw):
    a = copy.deepcopy(a)
    rb, sm = a.pop("_robots"), a.pop("_sitemap")
    for p in a["pages"]:
        if "ev" in p and kw.get("text_extraction"):
            p["ev"]["fetch_method"] = "text_extraction"
    kw.pop("text_extraction", None)
    return run_engine(a, robots_full=rb, sitemap_full=sm, **kw)


def chk(payload, cid):
    return next(c for c in payload["checks"] if c["id"] == cid)


def good_site(n=3):
    org = {"@context": "https://schema.org", "@type": "LocalBusiness", "name": "Example Pumps", "url": BASE,
           "address": {"@type": "PostalAddress", "streetAddress": "12 Main St", "addressLocality": "Colombo", "postalCode": "00100", "addressCountry": "LK"},
           "telephone": "+94 11 234 5678", "openingHours": "Mo-Fr 08:30-17:30"}
    pages = [page("/", doc(jsonld=org, extra="<p>Call <a href='tel:+94112345678'>+94 11 234 5678</a></p><address>12 Main St, Colombo 00100, Sri Lanka</address>"))]
    for i in range(1, n):
        path = f"/water-pumps-{i}"
        pages.append(page(path, doc(title=f"Water Pumps Model {i} for Factories in Colombo | Example", url=BASE + path, h1=(f"Water Pumps Model {i}",),
                                    desc=f"Model {i} water pumps for factories in Sri Lanka: flow, pressure and power specifications with a quote from Example Pumps.",
                                    extra="<p>Call <a href='tel:+94112345678'>+94 11 234 5678</a> <a href='/water-pumps'>see all water pumps</a></p>")))
    return pages


class ReferenceRegression(unittest.TestCase):
    def test_reference_script_all_pass(self):
        out = subprocess.run([sys.executable, str(REF_PATH)], capture_output=True, text=True, encoding="utf-8", errors="replace")
        self.assertIn("RESULT: ALL PASS", (out.stdout or "") + (out.stderr or ""))
        for site, score in (("dreamceylonvibetours.com", 16), ("ranjithautocables.com", 33), ("voltedgepower-solutions.com", 47), ("gkips.com", 29)):
            self.assertRegex(out.stdout, rf"{site}\s+sum\(W\*S\)=\s*\d+\s+->\s*{score}\s+expected\s+{score}\s+OK")

    def test_port_matches_reference_on_corpus(self):
        spec = importlib.util.spec_from_file_location("refeng", REF_PATH)
        ref = importlib.util.module_from_spec(spec); spec.loader.exec_module(ref)
        self.assertEqual(ref.WEIGHTS, WEIGHTS)
        for site, d in ref.CORPUS.items():
            ws = sum(WEIGHTS[c] * s for c, s in d["scores"].items())
            self.assertEqual(round_half_up(ws / 100), d["overall"], site)
            self.assertEqual(project_potential(d["potentials"], d["overall"])["overall"], d["potential"], site)

    def test_port_matches_reference_on_random_checks(self):
        spec = importlib.util.spec_from_file_location("refeng", REF_PATH)
        ref = importlib.util.module_from_spec(spec); spec.loader.exec_module(ref)
        rnd = random.Random(1234)
        for _ in range(300):
            cat = rnd.choice(list(WEIGHTS))
            pts = [10] * 10
            rows = []
            for i, p in enumerate(pts):
                st = rnd.choice(["PASS", "WARN", "FAIL", "UNMEASURED", "NOT_APPLICABLE"])
                cov = round(rnd.random(), 3) if st in ("PASS", "WARN", "FAIL") and rnd.random() < 0.4 else None
                rows.append((f"X{i}", cat, p, st, cov))
            mine = score_category(cat, [CheckResult(*r[:4], coverage=r[4]) for r in rows])
            theirs = ref.score_category(cat, [ref.CheckResult(*r[:4], coverage=r[4]) for r in rows])
            self.assertEqual((mine.score, mine.provisional, mine.measured_points), (theirs.score, theirs.provisional, theirs.measured_points))


class Arithmetic(unittest.TestCase):
    def test_round_half_up_not_bankers(self):
        self.assertEqual(round_half_up(28.98), 29)
        self.assertEqual(round_half_up(2.5), 3)       # Python's round(2.5) == 2
        self.assertEqual(round_half_up(47.5), 48)
        self.assertEqual(round_half_up(32.65), 33)

    def test_band_boundaries(self):
        for s, g in ((100, "Excellent"), (90, "Excellent"), (89, "Very Good"), (80, "Very Good"), (79, "Good"), (70, "Good"),
                     (69, "Needs Improvement"), (60, "Needs Improvement"), (59, "Poor"), (40, "Poor"), (39, "Critical"), (0, "Critical")):
            self.assertEqual(band(s), g, s)

    def test_zero_measurable_category_is_unscorable_and_weight_redistributed(self):
        results = [CheckResult("A", c, 100, "PASS") for c in WEIGHTS if c != "image"] + [CheckResult("I", "image", 100, "UNMEASURED")]
        site = score_site(results)
        self.assertIsNone(site["categories"]["image"].score)
        self.assertTrue(site["weight_redistributed"])
        self.assertEqual(site["overall"], 100)

    def test_unmeasured_caps_but_never_fails(self):
        c = score_category("page_experience", [CheckResult("P01", "page_experience", 70, "UNMEASURED"), CheckResult("P05", "page_experience", 30, "PASS")])
        self.assertEqual(c.score, 65)  # cap = 100 - 0.5 * 70
        self.assertTrue(c.provisional)

    def test_no_global_critical_penalty(self):
        # A failing critical check only costs its own points inside its category.
        base = [CheckResult(f"C{i}", c, 50, "PASS") for i, c in enumerate(WEIGHTS) for _ in range(2)]
        with_fail = list(base)
        with_fail[0] = CheckResult("T11", "technical", 50, "FAIL")
        a, b = score_site(base), score_site(with_fail)
        self.assertEqual(a["overall"], 100)
        self.assertEqual(b["overall"], round_half_up((100 * 100 - 15 * 50) / 100))  # technical 50 -> -7.5 -> 92.5 -> 93


class Checks(unittest.TestCase):
    def test_missing_title_is_coverage_not_zero(self):
        pages = good_site(5)
        pages[2] = page("/water-pumps-2", doc(title=None, url=BASE + "/water-pumps-2"))
        c = chk(run(audit(pages)), "O01")
        self.assertEqual(c["points_earned"], 8.0)
        self.assertNotEqual(c["status"], "PASS")

    def test_duplicate_title(self):
        pages = good_site(3)
        pages[2] = page("/water-pumps-2", doc(title="Water Pumps Model 1 for Factories in Colombo | Example", url=BASE + "/water-pumps-2"))
        p = run(audit(pages))
        self.assertEqual(chk(p, "O03")["status"], "FAIL")
        self.assertEqual(chk(p, "O01")["status"], "PASS")
        self.assertEqual(next(i for i in p["issues"] if i["check_id"] == "O03")["severity"], "high")

    def test_missing_meta_description(self):
        pages = good_site(8)
        for i in (3, 5):
            pages[i] = page(f"/water-pumps-{i}", doc(desc="", url=BASE + f"/water-pumps-{i}", title=f"Water Pumps Model {i} for Factories in Colombo | Example"))
        p = run(audit(pages))
        self.assertAlmostEqual(chk(p, "O06")["coverage"], 0.75)
        self.assertEqual(chk(p, "O06")["points_earned"], 7.5)
        self.assertEqual(chk(p, "O08")["status"], "PASS")

    def test_wrong_title_length(self):
        p = run(audit([page("/", doc(title="X" * 72))]))
        self.assertEqual(chk(p, "O02")["status"], "FAIL")
        p = run(audit([page("/", doc(title="Industrial Water Pumps Supplier in Colombo | Example Pumps LK"[:61].ljust(61, "s")))]))
        self.assertEqual(chk(p, "O02")["status"], "WARN")

    def test_multiple_h1_and_skipped_levels_are_independent(self):
        p = run(audit([page("/", doc(h1=("Water Pumps", "Welcome")))]))
        self.assertEqual(chk(p, "O09")["status"], "FAIL")
        html = doc(h1=("Industrial Water Pumps",), h2=()).replace("</main>", "<h4>Deep heading</h4><h4>Another</h4><h4>Third</h4></main>")
        p = run(audit([page("/", html)]))
        self.assertEqual(chk(p, "O11")["status"], "FAIL")
        self.assertEqual(chk(p, "O09")["status"], "PASS")

    def test_heading_artefact_preserved_raw(self):
        html = doc(h1=("INDUSTRIAL AIR COMPRESSORS ---",)).replace("</main>", "<h3>---</h3></main>")
        p = run(audit([page("/", html)]))
        c = chk(p, "O12")
        self.assertEqual(c["status"], "FAIL")
        artefacts = json.dumps(c["evidence"]["values"]["artefacts"])
        self.assertIn("INDUSTRIAL AIR COMPRESSORS ---", artefacts)
        self.assertIn('"---"', artefacts)

    def test_missing_canonical_single_host(self):
        pages = [page("/", doc(canonical=False)), page("/water-pumps-1", doc(canonical=False, url=BASE + "/water-pumps-1"))]
        p = run(audit(pages), probes=probes())
        self.assertEqual(chk(p, "T04")["status"], "FAIL")
        self.assertEqual(chk(p, "T03")["status"], "PASS")
        self.assertEqual(next(i for i in p["issues"] if i["check_id"] == "T04")["severity"], "high")

    def test_dual_host_exposure(self):
        pages = [page("/", doc(canonical=False))]
        p = run(audit(pages), probes=probes(hosts="dual_same"))
        self.assertEqual(chk(p, "T03")["status"], "FAIL")
        issue = next(i for i in p["issues"] if i["check_id"] == "T03")
        self.assertEqual((issue["severity"], issue["priority"]), ("critical", "P1"))
        p = run(audit(pages))  # no header/host access -> at risk, not failed
        self.assertEqual(chk(p, "T03")["status"], "UNMEASURED")

    def test_noindex_on_commercial_page(self):
        pages = good_site(3)
        pages[1] = page("/water-pumps-1", doc(head='<meta name="robots" content="noindex">', url=BASE + "/water-pumps-1", title="Water Pumps Model 1 for Factories in Colombo | Example"))
        p = run(audit(pages))
        self.assertEqual(chk(p, "T11")["status"], "FAIL")
        self.assertEqual(next(i for i in p["issues"] if i["check_id"] == "T11")["severity"], "critical")
        self.assertIsNotNone(p["score"]["overall"])

    def test_broken_nav_links(self):
        p = run(audit(good_site(3), link_checks=[{"url": BASE + "/water-pumps", "status": 404}, {"url": BASE + "/contact-us", "status": 404}]))
        self.assertEqual(chk(p, "L01")["status"], "FAIL")

    def test_missing_pages_are_not_broken_links(self):
        p = run(audit(good_site(3)), probes=probes(missing=("/about", "/contact")))
        self.assertEqual({m["url"] for m in p["missing_pages"]}, {BASE + "/about", BASE + "/contact"})
        self.assertNotEqual(chk(p, "L01")["status"], "FAIL")
        self.assertFalse(any(i["check_id"] == "L01" for i in p["issues"]))

    def test_missing_alt_with_product_info_in_images(self):
        imgs = [(f"/img/pump-model-{i}.jpg", None) for i in range(8)]
        pages = [page("/", doc()), page("/water-pumps-1", doc(body="Pumps.", h2=(), imgs=imgs, url=BASE + "/water-pumps-1", title="Water Pumps Model 1 for Factories in Colombo | Example"))]
        p = run(audit(pages))
        for cid in ("I01", "I03", "C10"):
            self.assertEqual(chk(p, cid)["status"], "FAIL", cid)

    def test_schema_unavailable_is_unmeasured_not_absent(self):
        p = run(audit([page("/", doc())]), text_extraction=True)
        for cid in ("S01", "S02", "S03", "S04"):
            self.assertIn(chk(p, cid)["status"], ("UNMEASURED", "NOT_APPLICABLE"), cid)
        self.assertEqual(chk(p, "S01")["status"], "UNMEASURED")
        dump = json.dumps(p).lower()
        for phrase in ("no schema", "schema absent", "no structured data found"):
            self.assertNotIn(phrase, dump)

    def test_schema_genuinely_absent_with_raw_html(self):
        p = run(audit([page("/", doc())]))
        self.assertEqual(chk(p, "S01")["status"], "FAIL")

    def test_no_psi_means_unmeasured_and_no_numbers(self):
        p = run(audit(good_site(2)))
        for cid in ("P01", "P02", "P03", "P04"):
            c = chk(p, cid)
            self.assertEqual((c["status"], c["display_as"]), ("UNMEASURED", "Integration required"))
        pe = next(c for c in p["categories"] if c["id"] == "page_experience")
        self.assertTrue(pe["provisional"])
        self.assertLessEqual(pe["score"], 65)
        self.assertEqual([h for h in fabrication_hits([json.dumps(p)]) if not h["permitted"]], [])

    def test_psi_available_uses_real_field_values(self):
        rd = {"pagespeed": {"mobile": {"ok": True, "mode": "api", "fetched_at": "2026-10-07T00:00:00Z",
                                       "field_url": {"scope": "url", "metrics": {"LCP": {"p75": 4800, "rating": "poor"}, "CLS": {"p75": 0.31, "rating": "poor"},
                                                                                "INP": {"p75": 150, "rating": "good"}, "TTFB": {"p75": 700, "rating": "good"}}}}}}
        p = run(audit(good_site(2), real_data=rd))
        self.assertEqual(chk(p, "P01")["status"], "FAIL")
        self.assertEqual(chk(p, "P03")["status"], "FAIL")
        self.assertEqual(chk(p, "P02")["status"], "PASS")
        self.assertEqual(chk(p, "P01")["evidence"]["values"]["p75"], 4800)
        self.assertIn("PageSpeed Insights", chk(p, "P01")["evidence"]["statement"])

    def test_javascript_only_site_is_not_scored_as_empty(self):
        shell = doc(body="Loading", h2=()).replace("</body>", "".join(f"<script src='/app{i}.js'></script>" for i in range(8)) + "</body>")
        p = run(audit([page("/", shell), page("/water-pumps-1", shell.replace(BASE + "/", BASE + "/water-pumps-1"))]))
        self.assertTrue(p["audit"]["render_dependency"])
        for cid in ("C01", "C02", "K01", "O04"):
            self.assertEqual(chk(p, cid)["status"], "UNMEASURED", cid)
        self.assertNotEqual(next(c for c in p["categories"] if c["id"] == "content")["score"], 0)

    def test_local_business_and_gbp_unknown(self):
        p = run(audit(good_site(2)))
        self.assertEqual(chk(p, "Lo02")["status"], "PASS")
        self.assertEqual(chk(p, "Lo09")["status"], "UNMEASURED")

    def test_nap_only_on_homepage(self):
        pages = good_site(1) + [page(f"/inner-{i}", doc(url=BASE + f"/inner-{i}", title=f"Inner page number {i} about water pumps | Example").replace("<nav>", "<nav hidden>"))
                                for i in range(3)]
        p = run(audit(pages))
        self.assertEqual(chk(p, "Lo02")["status"], "PASS")
        self.assertEqual(chk(p, "Lo03")["status"], "WARN")  # D.10: present but not propagated
        self.assertIn("not propagated", chk(p, "Lo03")["evidence"]["statement"])
        self.assertEqual(chk(p, "X01")["status"], "FAIL")   # D.12: homepage only
        absent = run(audit([page("/", doc()), page("/inner", doc(url=BASE + "/inner", title="Inner page about water pumps | Example"))]))
        self.assertIn("absent everywhere", chk(absent, "Lo03")["evidence"]["statement"])

    def test_multilingual_and_single_market_hreflang_never_fails(self):
        p = run(audit(good_site(2)))
        self.assertFalse(any("hreflang" in c["name"].lower() and c["status"] == "FAIL" for c in p["checks"]))

    def test_ecommerce_profile(self):
        prod = {"@context": "https://schema.org", "@type": "Product", "name": "Pump X", "offers": {"@type": "Offer", "price": "100", "availability": "InStock"}}
        pages = [page("/", doc()), page("/products/pump-x", doc(jsonld=prod, url=BASE + "/products/pump-x", extra="<button>Add to cart</button> Price: Rs 25,000 In stock")),
                 page("/products/pump-y", doc(jsonld=prod, url=BASE + "/products/pump-y", extra="<button>Add to cart</button> Price: Rs 30,000 In stock"))]
        p = run(audit(pages))
        self.assertEqual(p["audit"]["vertical_profile"], "ecommerce")
        self.assertEqual(chk(p, "E01")["status"], "PASS")
        self.assertEqual(chk(p, "E04")["status"], "PASS")

    def test_form_without_email(self):
        form = "<form><input name='name'><input name='phone'><textarea name='message'></textarea><input type='hidden' name='hp'></form>"
        p = run(audit([page("/", doc(extra=form))]))
        self.assertEqual(chk(p, "X03")["status"], "FAIL")
        issue = next(i for i in p["issues"] if i["check_id"] == "X03")
        self.assertEqual(issue["severity"], "critical")
        self.assertTrue(issue["business_impact"])

    def test_form_discards_context_vs_prefills(self):
        link = "<a href='/quote/?product=50-kva-ricardo'>Get a quote</a>"
        empty = "<form><input name='name'><input type='email' name='email'><select name='product'><option>Choose</option></select></form>"
        pref = "<form><input name='name'><input type='email' name='email'><select name='product'><option selected>50 KVA Ricardo</option></select></form>"
        p = run(audit([page("/", doc(extra=link)), page("/quote/?product=50-kva-ricardo", doc(extra=empty, url=BASE + "/quote/?product=50-kva-ricardo"))]))
        self.assertEqual(chk(p, "X04")["status"], "FAIL")
        p = run(audit([page("/", doc(extra=link)), page("/quote/?product=50-kva-ricardo", doc(extra=pref, url=BASE + "/quote/?product=50-kva-ricardo"))]))
        self.assertEqual(chk(p, "X04")["status"], "PASS")

    def test_cta_without_mechanism(self):
        p = run(audit([page("/", doc(extra="<p>For prices, send us an email today.</p>"))]))
        self.assertEqual(chk(p, "X05")["status"], "FAIL")
        self.assertEqual(next(i for i in p["issues"] if i["check_id"] == "X05")["severity"], "high")

    def test_counter_rendering_as_zero(self):
        p = run(audit([page("/", doc(extra="<div>0+ projects completed</div><div>15 years</div>"))]))
        c = chk(p, "C06")
        self.assertEqual(c["status"], "FAIL")
        self.assertIn("(Verified)", c["evidence"]["statement"])
        self.assertIn("Inferred", c["evidence"]["statement"])

    def test_5xx_everywhere_aborts(self):
        p = run(audit([page("/", "<html></html>", status=503), page("/a", "<html></html>", status=500)]))
        self.assertEqual(p["error"], "AUDIT_FAILED: site unreachable")
        self.assertIsNone(p["score"]["overall"])

    def test_single_page_site(self):
        p = run(audit([page("/", doc())]))
        self.assertTrue(p["audit"]["small_site"])
        self.assertEqual(chk(p, "T15")["status"], "NOT_APPLICABLE")
        self.assertEqual(chk(p, "L04")["status"], "NOT_APPLICABLE")


class PayloadContract(unittest.TestCase):
    def setUp(self):
        self.p = run(audit(good_site(3)), probes=probes())

    def test_unmeasured_external_data_disclosed(self):
        self.assertTrue(self.p["score"]["potential"]["disclaimer_required"])
        self.assertIn("estimate, not a guarantee", self.p["score"]["potential"]["disclaimer"])
        self.assertIn("Statement on data integrity", self.p["integrity"]["statement"])
        self.assertTrue({"P01", "P02", "P03", "P04"} <= {u["check_id"] for u in self.p["unmeasured"]})

    def test_potential_never_100_and_rederives(self):
        self.assertTrue(all(c["potential_score"] < 100 for c in self.p["categories"]))
        self.assertTrue(self.p["integrity"]["verification_gate"]["passed"], self.p["integrity"]["verification_gate"])

    def test_every_issue_backed_by_failed_check_and_ordered(self):
        status = {c["id"]: c["status"] for c in self.p["checks"]}
        rank = {"critical": 0, "high": 1, "medium": 2, "low": 3}
        keys = [(rank[i["severity"]], -WEIGHTS[i["category"]], i["check_id"]) for i in self.p["issues"]]
        self.assertEqual(keys, sorted(keys))
        for i in self.p["issues"]:
            self.assertIn(status[i["check_id"]], ("FAIL", "WARN"))

    def test_overall_is_weighted_mean_of_categories(self):
        cats = self.p["categories"]
        ws = sum(c["weight"] * c["score"] for c in cats if c["score"] is not None)
        self.assertEqual(self.p["score"]["weighted_sum"], ws)
        self.assertEqual(self.p["score"]["overall"], round_half_up(ws / 100))
        self.assertEqual(sum(c["weight"] for c in cats), 100)

    def test_gate_catches_tampering(self):
        bad = copy.deepcopy(self.p); bad["score"]["overall"] += 1
        self.assertFalse(run_gate(bad)["passed"])
        bad = copy.deepcopy(self.p); bad["categories"][0]["score"] = (bad["categories"][0]["score"] or 0) + 5
        self.assertFalse(run_gate(bad)["passed"])
        if self.p["issues"]:
            bad = copy.deepcopy(self.p); bad["issues"][0]["id"] = "99"
            self.assertFalse(run_gate(bad)["passed"])
        self.assertFalse(run_gate(self.p, ["LCP is probably about 3.5 s on mobile."])["passed"])

    def test_ai_layer_cannot_emit_numbers(self):
        self.assertIsNone(clean_prose(87))
        self.assertIsNone(clean_prose("Your LCP is around 3.5 seconds which is slow for users."))
        self.assertIsNone(clean_prose("You rank at position 4 on Google for pumps."))
        self.assertEqual(clean_prose("Your titles are clear. Add a postal address to every page footer."),
                         "Your titles are clear. Add a postal address to every page footer.")

    def test_determinism(self):
        a = audit(good_site(4))
        first = json.dumps(run(a, probes=probes()), sort_keys=True)
        for _ in range(30):
            self.assertEqual(json.dumps(run(a, probes=probes()), sort_keys=True), first)


if __name__ == "__main__":
    unittest.main(verbosity=2)
