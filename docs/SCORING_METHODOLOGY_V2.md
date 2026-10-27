# Aviance SEO Pro Max — Scoring Methodology v2.0
**Document Version:** 2.0.0  
**Ruleset Version:** `2.0.0` (`v2.0-evidence-based`)  
**Baseline Reference:** `1.0.0` (`ruleset_v1.json`)  
**Published:** October 2026  
**Audience:** Technical SEO Analysts, Developers, Executive Stakeholders

---

## 1. Executive Overview & Design Principles

The Aviance SEO Scoring Engine v2.0 represents an independently engineered, evidence-first SEO measurement platform designed in strict accordance with official **Google Search Central Documentation**, **W3C Web Standards**, and **WCAG 2.1 Accessibility Guidelines**. 

Unlike legacy SEO scoring systems that rely on proprietary black-box scoring or fabricate metrics when APIs are absent, Aviance v2.0 enforces five foundational principles:

1. **Zero Metric Fabrication:** Metrics that cannot be directly measured or verified via connected APIs (e.g., first-party search traffic, impressions, private analytics) report `UNMEASURED` or `NOT_APPLICABLE`. They are never filled with artificial estimates.
2. **Dual-Score Separation:** Clear distinction between:
   - **Technical SEO Health Score (0–100%):** Measures crawlability, indexability, security protocols, Core Web Vitals, and mobile compliance.
   - **Overall SEO Audit Score (0–100%):** Measures total site maturity across technical health, on-page optimization, content depth, structured data, backlink authority, and vertical business alignment.
3. **Transparent Mathematical Formulation:** Every score is calculated deterministically through normalized, weighted category sums, rounded using unbiased `ROUND_HALF_UP` arithmetic.
4. **Context-Aware Business Profile Adaptation:** An agency or SaaS platform is never penalized for lacking walk-in storefront operating hours or physical parking maps. Audit rules adapt based on verified business entities.
5. **Ruleset Versioning & Immutability:** Legacy audits remain reproducible against `ruleset_v1.json` (1.0.0), while new audits execute against `ruleset_v2.json` (2.0.0).

---

## 2. Category Weights & Scoring Architecture

The overall audit evaluation is partitioned across twelve distinct technical and strategic disciplines totaling exactly 100 points:

| Category ID | Category Name | Weight (%) | Scope & Official Standard Reference |
| :--- | :--- | :---: | :--- |
| `technical` | Technical & Crawlability | 15% | HTTP status, robots.txt, canonical integrity, sitemap indexability |
| `on_page` | On-Page Optimization | 12% | Title tags, meta descriptions, H1 hierarchy, OpenGraph, Twitter cards |
| `content` | Content Quality & Depth | 12% | Word counts, heading structures, thin content detection, commercial intent |
| `keyword` | Keyword Targeting | 8% | Title/heading keywords, intent alignment, body density without keyword stuffing |
| `ux` | User Experience | 8% | Clean navigation architecture, 404 error handling, favicon, viewport |
| `page_experience`| Page Experience & Speed | 8% | Google CrUX / PageSpeed Core Web Vitals (LCP, INP, CLS, FCP) |
| `mobile` | Mobile Optimization | 8% | Responsive viewport, touch targets, font scaling, mobile parity |
| `security` | Security Protocols | 8% | Enforced HTTPS, HSTS, secure cookies, mixed content elimination |
| `schema` | Structured Data | 7% | Schema.org JSON-LD validity, Organization, WebSite, SoftwareApplication |
| `backlinks` | Backlink & Authority | 6% | Referring domain diversity, OpenPageRank, Ahrefs DR, toxic anchor detection |
| `local` | Local SEO | 4% | NAP consistency, Google Business Profile presence (physical entities only) |
| `vertical` | Vertical-Specific SEO | 2% | Tailored industry rubrics (SaaS, Agency, E-commerce, Publishing, B2B) |
| **Total** | | **100%** | |

---

## 3. Mathematical Scoring Formulas

### 3.1 Check Result Status & Credit Function

Each evaluated check produces a standardized `CheckResult`:

$$\text{Credit}(c) = \begin{cases} 
1.0 & \text{if } \text{Status}(c) = \text{PASS} \\
0.5 & \text{if } \text{Status}(c) = \text{WARN} \\
0.0 & \text{if } \text{Status}(c) = \text{FAIL} \\
\text{Excluded} & \text{if } \text{Status}(c) \in \{\text{UNMEASURED}, \text{NOT\_APPLICABLE}\}
\end{cases}$$

### 3.2 Category Score Calculation

For category $k$ with applicable checks $C_k$:

$$S_k = \text{round}\left(100 \times \frac{\sum_{c \in C_k^{\text{measured}}} \text{Points}(c) \times \text{Credit}(c)}{\sum_{c \in C_k^{\text{measured}}} \text{Points}(c)}\right)$$

If an entire category has no measurable checks (e.g. no Google Search Console connected for query clicks), $S_k = \text{None}$ (Unscorable / Provisional).

### 3.3 Confidence Capping for Unmeasured Data

When third-party integrations (e.g. CrUX, GSC, Ahrefs) are not configured, provisional category scores are capped to prevent over-optimistic ratings:

$$\text{Cap}_k = 100 - (\alpha \times U_k)$$

Where:
- $U_k$ is the sum of unmeasured check points in category $k$.
- $\alpha = 0.5$ is the confidence cap coefficient.
- The provisional category score satisfies: $S_k^{\text{provisional}} \le \text{Cap}_k$.

### 3.4 Overall SEO Audit Score

The Overall SEO Audit Score represents the weighted contribution of all scorable categories normalized across the active weight sum:

$$\text{Overall Score} = \text{round\_half\_up}\left(\frac{\sum_{k} W_k \times S_k}{\sum_{k} W_k}\right)$$

### 3.5 Technical SEO Health Score

The Technical SEO Health Score measures strictly infrastructural and technical resilience:

$$\text{Technical Health} = \text{round\_half\_up}\left(100 \times \frac{\sum_{c \in T^{\text{measured}}} \text{Points}(c) \times \text{Credit}(c)}{\sum_{c \in T^{\text{measured}}} \text{Points}(c)}\right)$$

Where $T$ is the set of technical checks comprising:
- Crawl & Indexability: `T01`–`T16`
- Mobile Compatibility: `M01`–`M03`
- Page Experience & Core Web Vitals: `P01`–`P06`
- Core Structured Data: `S01`, `S03`

---

## 4. Letter Grading System (10-Tier Scale)

Aviance v2.0 establishes an unambiguous 10-tier letter grading scale aligned with international software quality metrics:

| Score Range | Letter Grade | Evaluation Band | Recommended Color | Technical Interpretation |
| :---: | :---: | :---: | :---: | :--- |
| **95 – 100** | **A+** | Exceptional | `#059669` (Emerald) | Flawless infrastructure, zero critical or high-priority defects. |
| **90 – 94** | **A** | Excellent | `#10B981` (Green) | Industry-leading SEO execution with negligible minor notices. |
| **85 – 89** | **A-** | Very Good | `#14B8A6` (Teal) | Strong technical foundation; minor optimization opportunities. |
| **80 – 84** | **B+** | Good | `#06B6D4` (Cyan) | Healthy site with solid crawlability; non-blocking warnings present. |
| **75 – 79** | **B** | Above Average | `#2563EB` (Blue) | Competitive baseline; requires content or link equity improvements. |
| **70 – 74** | **B-** | Moderate | `#3B82F6` (Royal Blue) | Baseline performance; noticeable gaps in schema or on-page tags. |
| **65 – 69** | **C+** | Fair | `#F59E0B` (Amber) | Several medium/high issues affecting organic potential. |
| **60 – 64** | **C** | Needs Improvement | `#D97706` (Orange) | Deficiencies in crawl paths, mobile rendering, or performance. |
| **50 – 59** | **D** | Poor | `#F97316` (Deep Orange) | Critical architectural bottlenecks suppressing organic indexing. |
| **0 – 49** | **F** | Critical | `#EF4444` (Red) | Severe crawl failures, broken canonicals, or security blocks. |

---

## 5. Corrected SEO Rules & False-Positive Elimination

In Ruleset v2.0, multiple legacy rules were identified as generating false positives or conflicting with Google Search Central recommendations. The following corrections are active in `backend/seo_engine/checks.py`:

### 5.1 Canonical Tags (`T04`)
- **Old Behavior:** Flagged single self-referencing canonicals as redundant or threw arbitrary warnings on query parameters.
- **v2.0 Rule:** 
  - Multiple conflicting canonical tags on a single page $\rightarrow$ `FAIL` (Critical: search engines discard duplicate conflicting canonicals).
  - Relative canonical target URLs $\rightarrow$ `WARN` (Should be absolute `https://` URLs).
  - Valid, self-referencing absolute canonical $\rightarrow$ `PASS`.
  - Non-canonical alternate pages nominating valid canonical target $\rightarrow$ `PASS`.

### 5.2 Commercial Intent & Navigation (`C04`)
- **Old Behavior:** Literally flagged any website that included an `/about` page as an informational blog rather than a commercial entity, deducting points!
- **v2.0 Rule:** Verified offerings and service pages are evaluated from actual page links and service menus. Having an `/about` page is recognized as an E-E-A-T trust signal, not a commercial penalty.

### 5.3 Image Optimization & WCAG Accessibility (`I01`, `I04`)
- **Old Behavior:** Counted decorative images (`alt=""`) as missing alt attributes, penalizing accessible websites. Failed sites using JPEG/PNG even if next-gen WebP/AVIF formats were present.
- **v2.0 Rule:** 
  - Decorative images with explicit empty alt tags (`alt=""`) or `role="presentation"` are awarded 90% credit per WCAG 2.1 Level A guidelines.
  - Next-gen image format check (`I04`) passes when $\ge 25\%$ of media uses WebP, AVIF, or SVG, avoiding punitive scoring on legacy fallbacks.

### 5.4 Structured Data Schema (`S01`)
- **Old Behavior:** Failed any site that lacked `LocalBusiness` schema, even if it was a software platform or global agency.
- **v2.0 Rule:** Recognizes `WebSite`, `Organization`, `SoftwareApplication`, `TechArticle`, `Product`, and `Service` as primary structured data types.

### 5.5 Contact & Local Business Exemption (`M04`, `Lo02`–`Lo11`)
- **Old Behavior:** Penalized online agencies, SaaS products, and digital marketplaces if they did not display physical walk-in store hours, parking directions, or an embedded Google Map.
- **v2.0 Rule:** 
  - Digital contact channels (verified support email, live chat, or contact forms) satisfy contact requirements under `M04`.
  - Walk-in retail checks (`Lo02` Opening Hours, `Lo03` Map Embed, `Lo06` Transit/Parking) are automatically assigned `NOT_APPLICABLE` for non-local entities, removing them from the scoring denominator.

---

## 6. Business Profile Detection

The engine dynamically classifies target domains into one of nine distinct vertical profiles to apply tailored scoring rubrics:

1. `agency_services`: Digital marketing, web design, software development, creative agencies, IT consulting.
2. `software_saas`: Cloud software, SaaS platforms, developer APIs, documentation hubs.
3. `local_services`: Physical walk-in trades (dental clinics, restaurants, repair shops, retail stores).
4. `publisher_blog`: News websites, editorial publications, content hubs.
5. `ecommerce_retail`: Online retail stores with shopping carts, checkouts, and priced products.
6. `travel_tourism`: Tour operators, safari companies, hotels, travel itineraries.
7. `digital_asset_marketplace`: Motion graphics, templates, MOGRTs, royalty-free digital assets.
8. `b2b_product`: Industrial manufacturers, equipment suppliers, enterprise B2B components.
9. `general`: Universal fallback for informational or non-commercial websites.

Each vertical profile defines a 100-point specialized checkset ensuring industry-specific relevance.

---

## 7. Audit Explainability & Integrity Verification

Every audit generated by the Aviance platform is accompanied by an immutable verification ledger:
- **Rule Definitions:** Every score links directly to its rule ID (e.g., `T04`, `O02`, `C01`).
- **Observed Artefacts:** Check results include exact observed strings, status codes, and affected URLs.
- **Measurement Coverage Ratio:** The ratio of measured checks to total applicable checks is prominently reported (e.g. `Coverage: 92.5%`).
- **Verification Gate:** A tamper-detection hash ensures that calculated scores cannot be altered in memory without failing integrity validation.
