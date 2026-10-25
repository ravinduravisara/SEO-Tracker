# SEO Knowledge Base & RAG Architecture

## 1. Overview
The SEO Knowledge Base provides authoritative, verifiable reference specifications from Google Search Central, Web.dev, and Schema.org. It empowers Gemma 4 to cite exact documentation URLs and technical standards instead of generating ungrounded opinions.

---

## 2. In-Memory BM25 Lexical Retriever

* **Algorithm**: Okapi BM25 with dynamic Inverse Document Frequency (IDF) smoothing:
  $$IDF(q_i) = \ln\left(1 + \frac{N - n(q_i) + 0.5}{n(q_i) + 0.5}\right)$$
  $$Score(D, Q) = \sum_{i=1}^{n} IDF(q_i) \cdot \frac{f(q_i, D) \cdot (k_1 + 1)}{f(q_i, D) + k_1 \cdot \left(1 - b + b \cdot \frac{|D|}{\text{avgdl}}\right)}$$
* **Parameters**: $k_1 = 1.5, b = 0.75$.
* **Indexing Latency**: $< 5\text{ ms}$ for search queries across corpus.
* **Storage**: In-memory hash-map synchronized with persistent `knowledge_documents` database table.

---

## 3. Seed Document Corpus Catalog

| Document ID | Topic / Discipline | Title | Primary Source |
| :--- | :--- | :--- | :--- |
| `DOC-CANONICAL-URLS` | Technical SEO | Consolidating Duplicate URLs with Canonical Tags | [Google Search Central](https://developers.google.com/search/docs/crawling-indexing/consolidate-duplicate-urls) |
| `DOC-ROBOTS-TXT` | Technical SEO | Robots.txt Specifications & HTTP 404/5xx Handling | [Google Search Central](https://developers.google.com/search/docs/crawling-indexing/robots/robots_txt) |
| `DOC-XML-SITEMAP` | Technical SEO | Sitemaps Overview, Discovery & Lastmod Tags | [Google Search Central](https://developers.google.com/search/docs/crawling-indexing/sitemaps/overview) |
| `DOC-CORE-WEB-VITALS`| Performance | Core Web Vitals (LCP, INP, CLS) Thresholds | [Web.dev](https://web.dev/explore/fast) |
| `DOC-TITLE-SNIPPETS` | On-Page SEO | Controlling Your Title Links in Google Search | [Google Search Central](https://developers.google.com/search/docs/appearance/title-link) |
| `DOC-META-DESCRIPTIONS`| On-Page SEO | Snippet Optimization & Meta Descriptions | [Google Search Central](https://developers.google.com/search/docs/appearance/snippets) |
| `DOC-HEADING-TAGS` | Content & Structure | Semantic Headings and HTML5 Sectioning | [Google Search Central](https://developers.google.com/search/docs/fundamentals/seo-starter-guide) |
| `DOC-SCHEMA-ORG` | Structured Data | Understanding Structured Data (JSON-LD) | [Google Search Central](https://developers.google.com/search/docs/appearance/structured-data/intro-structured-data) |
| `DOC-SCHEMA-PRODUCT` | E-commerce | Product & Offer Rich Results Specifications | [Schema.org](https://schema.org/Product) |
| `DOC-INTERNAL-LINKING`| Linking Structure | Best Practices for Internal Links and Anchor Text | [Google Search Central](https://developers.google.com/search/docs/crawling-indexing/links-crawlable) |
| `DOC-HELPFUL-CONTENT`| Content Quality | Creating Helpful, Reliable, People-First Content | [Google Search Central](https://developers.google.com/search/docs/fundamentals/creating-helpful-content) |
| `DOC-LOCAL-SEO` | Local Business | Improving Your Local Ranking on Google | [Google Business Support](https://support.google.com/business/answer/7091) |
| `DOC-MOBILE-FIRST` | Mobile SEO | Mobile-First Indexing Best Practices | [Google Search Central](https://developers.google.com/search/docs/crawling-indexing/mobile/mobile-sites-mobile-first-indexing) |

---

## 4. Citation Generation & Output Format

Every recommendation verified by the RAG system includes formal documentation citations:
```json
{
  "citations": [
    {
      "document_id": "DOC-CANONICAL-URLS",
      "title": "Consolidating Duplicate URLs with Canonical Tags",
      "source_url": "https://developers.google.com/search/docs/crawling-indexing/consolidate-duplicate-urls",
      "publisher": "Google Search Central",
      "section": "Technical SEO",
      "knowledge_version": "1.0.0"
    }
  ]
}
```

