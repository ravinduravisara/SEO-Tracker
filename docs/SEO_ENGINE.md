# eSupport SEO Audit Engine (ruleset 1.0.0)

Implementation of **SEO-AUDIT-ENGINE-SPEC.md v1.0** (eSupport Digital Marketing). The spec is the authority; this
file explains where each part lives in the application.

## Single scoring path

```
REAL URL ─► crawl() (backend/main.py)                raw HTTP fetch, HTML kept intact incl. <script>
          ─► parse_page() + seo_engine/signals.py      raw evidence per page (nav/body links, forms, NAP, counters…)
          ─► seo_engine/probes.py                      www vs non-www, http→https, negative URLs + 404 control,
                                                       mobile-UA parity, sitemap <loc> sample, 360px browser render
          ─► seo_engine/checks.py                      PART D checks → PASS / WARN / FAIL / UNMEASURED / NOT_APPLICABLE
          ─► seo_engine/scoring.py                     PART E (faithful port of tests/reference/seo_scoring_engine.py)
          ─► seo_engine/issues.py                      one issue per FAIL/WARN check, severity → priority
          ─► seo_engine/gate.py                        PART I.10 verification gate + PART G.4 fabrication scan
          ─► audit["seo_engine"]                       PART J payload — the ONLY source of numbers
          ─► API / admin UI / client report / public check / PDF / CSV   (display only, no recalculation)
```

There is no other scorer. The removed systems were: `score_site()` (16 heuristic categories + a global
critical-issue penalty), `category_scoring.py` (8 categories), the single-page heuristic, per-page
`page_quality_score`, A–Z coverage percentages and the old recommendation engines.

## Constants (from `backend/seo_engine/ruleset_v1.json`)

| Category | Weight | | Category | Weight |
|---|---|---|---|---|
| Technical SEO | 15 | | Mobile SEO | 6 |
| On-Page SEO | 12 | | Page Experience | 8 |
| Content SEO | 12 | | Local SEO | 8 |
| Keyword Optimization | 8 | | Vertical SEO (profile) | 8 |
| Internal Linking | 6 | | Conversion SEO | 6 |
| Image SEO | 5 | | Structured Data | 6 |

* Overall = `round_half_up(Σ(weight × category score) / 100)`: one rounding, at the end (Decimal ROUND_HALF_UP).
* Category = `min(100 × earned / measured_points, 100 − 0.5 × unmeasured_points)`. Credit: PASS 1, WARN 0.5, FAIL 0;
  coverage checks earn `points × pages_passing / pages_evaluated`. UNMEASURED leaves the denominator; NOT_APPLICABLE is excluded.
* Bands: Excellent 90+, Very Good 80+, Good 70+, Needs Improvement 60+, Poor 40+, Critical below 40.
* Severity → priority: critical P1, high P2, medium P3, low P4 (WARN steps severity down one level). No global penalty.
* Vertical profiles: `b2b_product` (default), `travel_tourism`, `ecommerce` (DERIVED). Auto-detected, overridable via `vertical_profile`.

`VERIFIED` (from the source audits): weights, formula, bands, severity model, title ≤ 60 / description ≤ 155.
`DERIVED` (new in v1.0): check point values, severity defaults, maturity mapping, the e-commerce profile and the
deterministic potential projection (every measured gap fixed, unmeasured assumed measured, capped at 90).

## Unmeasured, never fabricated

| Reason | Display | Example |
|---|---|---|
| `capability_missing:psi` | Integration required | P01–P04 without a PageSpeed API key |
| `connector_no_data:psi` | Insufficient data | PSI returned no CrUX field data |
| `capability_missing:render` | Integration required | M03/M05 without a headless browser |
| `capability_missing:ga4` | Integration required | X09 when a tag exists but events can't be verified |
| `capability_missing:manual` | Not verifiable | T16, O05, C04, C07, K05, Lo09, V01 (b2b) |
| `capability_missing:html_raw` | Not verifiable | S01–S04 if script tags were not preserved — never "absent" |
| `not_attempted:*` | Not measured | probes on single-page / legacy audits |

Local Lighthouse runs (no API key) are shown to admins in **Real Data** but are **not** used for P01–P04: they are
lab numbers from this machine, not field data.

## Tests

```
.venv\Scripts\python.exe tests\reference\seo_scoring_engine.py     # must print RESULT: ALL PASS
.venv\Scripts\python.exe -m unittest tests.test_seo_engine -v      # 42 tests (PART L cases, gate, determinism)
```

## Re-scoring stored audits

`scripts/rescore_audits.py [--dry-run]` re-scores stored audits from their stored evidence (no network). Back up
`seo_platform.db` first. Published client report snapshots are frozen and are not changed.

## Known limitations

* The PART D rubric is DERIVED; on the calibration site voltedgepower-solutions.com a fresh crawl scores 67 vs. the
  analysts' 47. Most of the gap is in Technical, Content and B2B, where the analysts applied judgment (catalogue
  coverage vs. advertised range, copy quality) that the automated checks cannot fully reproduce.
* hreflang reciprocity is recorded as a per-URL finding but has no scored check in PART D.
* The 30-section narrative report (PART I) is not fully implemented; the PDF contains the scorecard, master issue
  table, quick wins, unmeasured data, missing pages and check-level evidence.
* Gate 1 (proposed title/description lengths) has nothing to check because the engine does not generate rewrites.
