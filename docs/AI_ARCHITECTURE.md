# SEO Tracker — Hybrid AI Architecture & Intelligence System

## 1. Executive Summary & Design Philosophy
Aviance SEO Pro Max / SEO Tracker implements a **zero-fabrication, evidence-grounded hybrid AI intelligence architecture**. The platform strictly combines deterministic rule evaluations with dynamic Retrieval-Augmented Generation (RAG) and post-generation algorithmic verification.

Under no circumstances does generative AI overwrite measured technical SEO scores, invent crawler facts, fabricated search keyword volumes, or guarantee search engine rankings.

---

## 2. Multi-Layer Hybrid Architecture

```
+-----------------------------------------------------------------------------------------+
|                                1. DETERMINISTIC SEO ENGINE                              |
|   Crawling Probes -> DNS -> Robots.txt -> Sitemaps -> HTML Parsing -> Category Scoring  |
|                               (Scores: 0 - 100%, Immutable)                             |
+-----------------------------------------------------------------------------------------+
                                           |
                                           v
+-----------------------------------------------------------------------------------------+
|                                2. AUDIT EVIDENCE TELEMETRY                              |
|   Structured Issues (Check IDs, Severity, Measured Values, Affected URLs, Status Codes) |
+-----------------------------------------------------------------------------------------+
          |                                                               |
          |                                                               v
          |                                            +----------------------------------+
          |                                            |   3. DYNAMIC RAG RETRIEVER       |
          |                                            |   BM25 Lexical Search Engine     |
          |                                            |   Google Search Central Corpus   |
          |                                            |   Schema.org & Web.dev Specs     |
          |                                            +----------------------------------+
          |                                                               |
          v                                                               v
+-----------------------------------------------------------------------------------------+
|                      4. INJECTION-RESISTANT CONTEXT BUILDER                             |
|   - Strips Prompt-Injection Vectors ("ignore instructions", "system prompt", HTML tags) |
|   - Encapsulates Evidence in XML Boundary Tags (<measured_audit_evidence>)              |
|   - Attaches Authoritative Citations (<authoritative_knowledge_citations>)              |
+-----------------------------------------------------------------------------------------+
                                           |
                                           v
+-----------------------------------------------------------------------------------------+
|                      5. PRODUCTION GEMMA 4 / GEMINI MODEL CLIENT                        |
|   - Hosted Gemma 4 API (Bearer Token) / Google GenAI REST API                           |
|   - Exponential Backoff & Jitter (3 bounded retries)                                    |
|   - Response Caching (SHA-256 Prompt Key, 1h TTL)                                       |
|   - Strict JSON Schema Output Enforcement                                               |
+-----------------------------------------------------------------------------------------+
                                           |
                                           v
+-----------------------------------------------------------------------------------------+
|                      6. RECOMMENDATION VERIFICATION GATE                                |
|   - Rule Contradiction Filter: blocks claims contradicting audit measurements           |
|     (e.g., claiming sitemap missing when verified; claiming 404 robots.txt is penalty)  |
|   - Fabricated Volume Filter: drops invented search volumes without provider connection |
|   - Prohibited Guarantees Filter: blocks promises of #1 rankings or guaranteed traffic  |
|   - Domain Boundary Enforcer: blocks advice pointing outside target hostname            |
+-----------------------------------------------------------------------------------------+
                                           |
                    +----------------------+----------------------+
                    |                                             |
                    v                                             v
+--------------------------------------+       +------------------------------------------+
|      7. AUDIT & REPORT GENERATION    |       |   8. INSTRUCTION TRAINING DATA PIPELINE  |
|   - Executive PDF with Citations     |       |   - Curated Verified Pairs               |
|   - Developer Handover Workbooks     |       |   - Review States (PENDING/APPROVED)     |
|   - Interactive Client Dashboard     |       |   - JSONL Instruction Tuning Export      |
+--------------------------------------+       +------------------------------------------+
```

---

## 3. Subsystem Breakdown

### 3.1 Deterministic SEO Ruleset
* Located in `backend/seo_engine/checks.py` and `backend/seo_engine/scoring.py`.
* 74+ automated checks spanning Technical, On-Page, Content, Linking, Performance, Schema, Mobile, and International SEO.
* All scores are mathematically calculated using weighted category baselines.

### 3.2 Dynamic RAG Knowledge Base
* Located in `backend/ai/rag_engine.py`.
* In-memory BM25 lexical retriever with inverse document frequency (IDF) term weighting ($k_1 = 1.5, b = 0.75$).
* Seeded with 13 authoritative documents from Google Search Central, Web.dev, and Schema.org.
* Produces verifiable `DocCitation` objects attached directly to client recommendations.

### 3.3 Prompt-Injection Defense
* Located in `backend/ai/context_builder.py`.
* Strips adversarial prompts crawled from target web pages (`<title>`, HTML comments, metadata).
* Isolates crawler findings within non-executable XML boundary enclosures.

### 3.4 Resilient Model Client
* Located in `backend/ai/model_client.py`.
* Supports hosted Gemma 4 (`gemma4:31b`) and Google Gemini models (`gemini-2.5-flash`).
* Thread-safe in-memory caching with 1-hour TTL reduces token consumption and eliminates latency on repeated requests.

### 3.5 Post-Generation Recommendation Verifier
* Located in `backend/ai/recommendation_validator.py`.
* Enforces deterministic verification:
  1. **Contradiction Detection**: If XML sitemap was verified present, any AI advice claiming "missing sitemap" is immediately rejected.
  2. **HTTP 404 Robots.txt Specification**: Treats robots.txt 404 as unrestricted crawl, rejecting fabricated claims of ranking penalties.
  3. **Fabricated Keyword Metrics**: Drops numerical search volumes unless connected to DataForSEO or Google Search Console.
  4. **Prohibited Ranking Guarantees**: Flags and rejects any unsupportable guarantees of search engine ranking positions.

