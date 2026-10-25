"""
Retrieval-Augmented Generation (RAG) Knowledge Base Engine.

Provides authoritative SEO documentation retrieval from Google Search Central,
Web.dev, and Schema.org. Grounds AI recommendations in verified documentation
with valid, verifiable citations.
"""

from __future__ import annotations

import hashlib
import json
import logging
import math
import re
import threading
from collections import Counter, defaultdict
from datetime import datetime
from typing import Any, Dict, List, Optional, Set, Tuple

from pydantic import BaseModel, Field

from ..database import SessionLocal, KnowledgeDocument

logger = logging.getLogger("aviance.ai.rag_engine")

STOP_WORDS: Set[str] = {
    "a", "about", "above", "after", "again", "against", "all", "am", "an", "and", "any", "are",
    "as", "at", "be", "because", "been", "before", "being", "below", "between", "both", "but",
    "by", "could", "did", "do", "does", "doing", "down", "during", "each", "few", "for", "from",
    "further", "had", "has", "have", "having", "he", "her", "here", "hers", "herself", "him",
    "himself", "his", "how", "i", "if", "in", "into", "is", "it", "its", "itself", "me", "more",
    "most", "my", "myself", "no", "nor", "not", "of", "off", "on", "once", "only", "or", "other",
    "ought", "our", "ours", "ourselves", "out", "over", "own", "same", "she", "should", "so",
    "some", "such", "than", "that", "the", "their", "theirs", "them", "themselves", "then",
    "there", "these", "they", "this", "those", "through", "to", "too", "under", "until", "up",
    "very", "was", "we", "were", "what", "when", "where", "which", "while", "who", "whom", "why",
    "with", "would", "you", "your", "yours", "yourself", "yourselves"
}


class DocCitation(BaseModel):
    document_id: str
    title: str
    source_url: str
    publisher: str
    section: str = ""
    knowledge_version: str = "1.0.0"
    retrieved_at: str = ""


class KnowledgeChunk(BaseModel):
    document_id: str
    title: str
    source_url: str
    publisher: str
    topic: str
    category: str
    content: str
    content_hash: str
    knowledge_version: str = "1.0.0"
    review_status: str = "APPROVED"
    retrieved_at: Optional[str] = None


# -----------------------------------------------------------------------------
# AUTHORITATIVE SEED KNOWLEDGE CORPUS
# -----------------------------------------------------------------------------
SEED_KNOWLEDGE_DOCUMENTS: List[Dict[str, Any]] = [
    {
        "document_id": "GSC-ROBOTS-001",
        "title": "Google Search Central: Introduction to robots.txt",
        "source_url": "https://developers.google.com/search/docs/crawling-indexing/robots/intro",
        "publisher": "Google Search Central",
        "topic": "robots_txt",
        "category": "technical",
        "content": (
            "A robots.txt file tells search engine crawlers which URLs the crawler can access on your site. "
            "Under Google Search Central guidelines, an unavailable or HTTP 404 robots.txt file is not an automatic "
            "critical failure; Googlebot treats HTTP 404 or 410 as meaning the site has no crawling restrictions. "
            "However, if robots.txt returns HTTP 5xx, Googlebot halts crawling until the server error resolves. "
            "To allow indexing, ensure robots.txt does not disallow Googlebot from important public pages and assets."
        )
    },
    {
        "document_id": "GSC-SITEMAP-001",
        "title": "Google Search Central: Sitemaps Overview & Best Practices",
        "source_url": "https://developers.google.com/search/docs/crawling-indexing/sitemaps/overview",
        "publisher": "Google Search Central",
        "topic": "xml_sitemaps",
        "category": "technical",
        "content": (
            "A sitemap tells Google which pages and files you think are important on your site. "
            "XML sitemaps should list only canonical, indexable URLs that return HTTP 200. "
            "Do not include noindex URLs, 301/302 redirects, or 404 pages in XML sitemaps. "
            "Sitemaps can be declared via the 'Sitemap:' directive in robots.txt or submitted directly in Google Search Console. "
            "For sites with over 50,000 URLs or 50MB uncompressed, use a sitemap index file."
        )
    },
    {
        "document_id": "GSC-CANONICAL-001",
        "title": "Google Search Central: Consolidating Duplicate URLs & Canonicals",
        "source_url": "https://developers.google.com/search/docs/crawling-indexing/consolidate-duplicate-urls",
        "publisher": "Google Search Central",
        "topic": "canonicalization",
        "category": "technical",
        "content": (
            "A canonical tag (rel='canonical') specifies the primary preferred URL when multiple versions of a page exist. "
            "Google strongly recommends self-referencing canonical tags on all indexable pages to avoid duplicate content ambiguity. "
            "The canonical URL must be absolute, match the preferred protocol (HTTPS), specify the canonical hostname (with or without www consistently), "
            "and point to an HTTP 200 indexable destination. Canonicals pointing to 404 or redirected pages are ignored by Google."
        )
    },
    {
        "document_id": "GSC-REDIRECTS-001",
        "title": "Google Search Central: Redirects and Google Search",
        "source_url": "https://developers.google.com/search/docs/crawling-indexing/301-redirects",
        "publisher": "Google Search Central",
        "topic": "redirects",
        "category": "technical",
        "content": (
            "301 Permanent Redirects forward visitors and search engines to a new URL while transferring ranking equity. "
            "Avoid redirect chains (more than 1 hop) and redirect loops. Long redirect chains consume crawl budget and introduce latency. "
            "When moving content, update internal links directly to the final destination URL rather than relying on redirects."
        )
    },
    {
        "document_id": "GSC-TITLES-001",
        "title": "Google Search Central: Influencing Title Links in Search Results",
        "source_url": "https://developers.google.com/search/docs/appearance/title-link",
        "publisher": "Google Search Central",
        "topic": "page_titles",
        "category": "on_page",
        "content": (
            "Title links are critical for helping users understand page relevance. Every page should have a unique, descriptive <title> tag. "
            "Best practice convention is between 30 and 60 characters (approximately 500-600 pixels). "
            "Titles should lead with the primary topic or product/service term, avoid generic boilerplate like 'Home' or 'Untitled', "
            "and avoid keyword stuffing. Brand names should be placed consistently, typically at the end with a delimiter like ' | BrandName'."
        )
    },
    {
        "document_id": "GSC-SNIPPETS-001",
        "title": "Google Search Central: Controlling Your Snippets in Search",
        "source_url": "https://developers.google.com/search/docs/appearance/snippet",
        "publisher": "Google Search Central",
        "topic": "meta_descriptions",
        "category": "on_page",
        "content": (
            "Meta description tags provide Google with a concise summary of the page to generate search snippets. "
            "While meta descriptions are not a direct ranking factor, compelling descriptions dramatically improve organic click-through rate (CTR). "
            "Descriptions should be between 70 and 155 characters to display cleanly without truncation on mobile and desktop. "
            "Every indexable page should have a unique meta description accurately reflecting the page content."
        )
    },
    {
        "document_id": "GSC-HEADINGS-001",
        "title": "Google Search Central & W3C: Semantic Headings and Structure",
        "source_url": "https://developers.google.com/search/docs/fundamentals/seo-starter-guide",
        "publisher": "Google Search Central",
        "topic": "heading_hierarchy",
        "category": "on_page",
        "content": (
            "Semantic HTML heading tags (H1 through H6) outline the hierarchical structure of page content. "
            "Every indexable page should feature exactly one distinct H1 tag that encapsulates the primary product, service, or topic. "
            "Subsequent headings (H2, H3) should organize subtopics without skipping levels (e.g., jumping from H1 directly to H4). "
            "Avoid using heading tags merely for styling or typography sizing."
        )
    },
    {
        "document_id": "GSC-LINKS-001",
        "title": "Google Search Central: Link Best Practices for Crawlability",
        "source_url": "https://developers.google.com/search/docs/crawling-indexing/links-crawlable",
        "publisher": "Google Search Central",
        "topic": "internal_links",
        "category": "internal_linking",
        "content": (
            "Google can only crawl links that use proper HTML <a> elements with an href attribute: <a href='/page'>. "
            "Links implemented via JavaScript onclick handlers or buttons without href attributes cannot be discovered reliably. "
            "Anchor text must be descriptive and contextual, avoiding vague labels like 'click here' or 'read more'. "
            "Maintain an interconnected internal link architecture to distribute link equity and eliminate orphan pages."
        )
    },
    {
        "document_id": "GSC-IMAGES-001",
        "title": "Google Search Central: Google Images SEO Best Practices",
        "source_url": "https://developers.google.com/search/docs/appearance/google-images",
        "publisher": "Google Search Central",
        "topic": "image_seo",
        "category": "image",
        "content": (
            "Image alt attributes provide accessible alternative text for screen readers and search engines to understand image context. "
            "Provide concise, descriptive alt text for informative images; decorative images should use empty alt='' attributes. "
            "Use modern, responsive formats like WebP or AVIF, provide explicit width and height attributes to avoid Cumulative Layout Shift (CLS), "
            "and utilize native lazy loading (loading='lazy') below the fold."
        )
    },
    {
        "document_id": "SCHEMA-SD-001",
        "title": "Google Search Central: Introduction to Structured Data & Schema.org",
        "source_url": "https://developers.google.com/search/docs/appearance/structured-data/intro-structured-data",
        "publisher": "Google Search Central",
        "topic": "structured_data",
        "category": "structured_data",
        "content": (
            "Structured data is standardized code formatted in JSON-LD to classify page content and enable Google rich results. "
            "Commercial sites should declare Organization or LocalBusiness schemas with valid Name, URL, Logo, and ContactPoint. "
            "E-commerce stores should implement Product, AggregateRating, and Offer schemas with valid price and availability. "
            "Structured data must accurately match the visible content rendered to human visitors."
        )
    },
    {
        "document_id": "WEBDEV-CWV-001",
        "title": "Web.dev: Core Web Vitals & Page Experience Thresholds",
        "source_url": "https://web.dev/articles/vitals",
        "publisher": "web.dev",
        "topic": "core_web_vitals",
        "category": "page_experience",
        "content": (
            "Core Web Vitals measure real-world user experience across three key pillars: "
            "1. Largest Contentful Paint (LCP): measures loading performance; good is <= 2.5s. "
            "2. Interaction to Next Paint (INP): measures page responsiveness; good is <= 200ms. "
            "3. Cumulative Layout Shift (CLS): measures visual stability; good is <= 0.1. "
            "Server response time (TTFB) should be <= 800ms. Optimize assets, server caching, and critical CSS rendering paths."
        )
    },
    {
        "document_id": "GSC-CONTENT-001",
        "title": "Google Search Central: Creating Helpful, People-First Content",
        "source_url": "https://developers.google.com/search/docs/fundamentals/creating-helpful-content",
        "publisher": "Google Search Central",
        "topic": "helpful_content",
        "category": "content",
        "content": (
            "Google's ranking systems reward original, high-quality, people-first content demonstrating first-hand expertise and depth. "
            "Thin pages with fewer than 150 words of actual informational content fail to satisfy search intent. "
            "Avoid automated spinning, deceptive summaries, or publishing pages primarily to game search engine rankings without providing clear utility."
        )
    },
    {
        "document_id": "GSC-LOCAL-001",
        "title": "Google Search Central: Local SEO and Business Representation",
        "source_url": "https://developers.google.com/search/docs/appearance/structured-data/local-business",
        "publisher": "Google Search Central",
        "topic": "local_seo",
        "category": "local",
        "content": (
            "Local businesses must maintain consistent Name, Address, and Phone Number (NAP) details across website footers, contact pages, "
            "and external local citations. Implement LocalBusiness or PostalAddress structured data specifying addressLocality, addressCountry, "
            "postalCode, telephone, and geo coordinates. Ensure phone numbers are clickable (tel: links) for mobile users."
        )
    }
]


class RAGKnowledgeBase:
    """
    In-memory BM25 lexical search engine backed by persistent database storage.
    """

    def __init__(self):
        self._lock = threading.Lock()
        self._documents: Dict[str, KnowledgeChunk] = {}
        self._doc_tokens: Dict[str, List[str]] = {}
        self._idf: Dict[str, float] = {}
        self._avg_dl: float = 0.0
        self._k1 = 1.5
        self._b = 0.75
        self.knowledge_version = "1.0.0"
        self._init_corpus()

    def _tokenize(self, text: str) -> List[str]:
        words = re.findall(r"\b[a-zA-Z0-9_\-\.]{2,}\b", text.lower())
        return [w for w in words if w not in STOP_WORDS]

    def _init_corpus(self):
        """Loads seed documents and synchronizes with persistent database."""
        with self._lock:
            # 1. Load seed documents into memory
            for doc_dict in SEED_KNOWLEDGE_DOCUMENTS:
                doc_id = doc_dict["document_id"]
                content = doc_dict["content"]
                c_hash = hashlib.sha256(content.encode("utf-8")).hexdigest()
                chunk = KnowledgeChunk(
                    document_id=doc_id,
                    title=doc_dict["title"],
                    source_url=doc_dict["source_url"],
                    publisher=doc_dict["publisher"],
                    topic=doc_dict["topic"],
                    category=doc_dict["category"],
                    content=content,
                    content_hash=c_hash,
                    knowledge_version=self.knowledge_version,
                    retrieved_at=datetime.utcnow().isoformat()
                )
                self._documents[doc_id] = chunk

            # 2. Synchronize to database if available
            try:
                with SessionLocal() as db:
                    existing = {d.document_id: d for d in db.query(KnowledgeDocument).all()}
                    for chunk in self._documents.values():
                        if chunk.document_id not in existing:
                            db_doc = KnowledgeDocument(
                                document_id=chunk.document_id,
                                title=chunk.title,
                                source_url=chunk.source_url,
                                publisher=chunk.publisher,
                                topic=chunk.topic,
                                category=chunk.category,
                                content=chunk.content,
                                content_hash=chunk.content_hash,
                                knowledge_version=chunk.knowledge_version,
                                review_status=chunk.review_status,
                                retrieved_at=datetime.utcnow()
                            )
                            db.add(db_doc)
                    db.commit()
            except Exception as exc:
                logger.debug(f"Knowledge document DB sync notice: {exc}")

            # 3. Build lexical index (BM25)
            self._rebuild_index()

    def _rebuild_index(self):
        """Builds BM25 term frequencies and inverted document frequencies."""
        total_docs = len(self._documents)
        if total_docs == 0:
            return

        doc_lengths = []
        df: Dict[str, int] = defaultdict(int)

        self._doc_tokens.clear()
        for doc_id, doc in self._documents.items():
            full_text = f"{doc.title} {doc.topic} {doc.category} {doc.content}"
            tokens = self._tokenize(full_text)
            self._doc_tokens[doc_id] = tokens
            doc_lengths.append(len(tokens))
            unique_tokens = set(tokens)
            for t in unique_tokens:
                df[t] += 1

        self._avg_dl = sum(doc_lengths) / total_docs if total_docs else 1.0

        self._idf.clear()
        for term, freq in df.items():
            # BM25 standard IDF formula with smoothing
            self._idf[term] = math.log(1.0 + (total_docs - freq + 0.5) / (freq + 0.5))

    def search(
        self,
        query: str,
        category: Optional[str] = None,
        top_k: int = 3
    ) -> List[Tuple[KnowledgeChunk, float]]:
        """
        Retrieves the top-k most relevant documentation passages using BM25 scoring.
        """
        with self._lock:
            q_tokens = self._tokenize(query)
            if not q_tokens:
                return []

            scores: Dict[str, float] = defaultdict(float)
            cat_filter = category.lower() if category else None

            for doc_id, tokens in self._doc_tokens.items():
                doc = self._documents[doc_id]
                
                # Category boost if query matches document category
                cat_boost = 1.25 if cat_filter and doc.category.lower() == cat_filter else 1.0

                dl = len(tokens)
                tf_counts = Counter(tokens)

                bm25_score = 0.0
                for term in q_tokens:
                    if term in tf_counts:
                        tf = tf_counts[term]
                        idf = self._idf.get(term, 0.5)
                        numerator = tf * (self._k1 + 1.0)
                        denominator = tf + self._k1 * (1.0 - self._b + self._b * (dl / self._avg_dl))
                        bm25_score += idf * (numerator / denominator)

                if bm25_score > 0:
                    scores[doc_id] = bm25_score * cat_boost

            sorted_docs = sorted(scores.items(), key=lambda kv: kv[1], reverse=True)
            results = []
            for doc_id, score in sorted_docs[:top_k]:
                results.append((self._documents[doc_id], round(score, 3)))

            return results

    def get_citations_for_issue(
        self,
        issue_code: str,
        issue_category: str,
        issue_message: str
    ) -> List[DocCitation]:
        """
        Retrieves authoritative citations specifically mapped to an SEO issue.
        """
        query = f"{issue_code} {issue_category} {issue_message}"
        results = self.search(query=query, category=issue_category, top_k=2)
        citations = []
        for doc, _ in results:
            citations.append(
                DocCitation(
                    document_id=doc.document_id,
                    title=doc.title,
                    source_url=doc.source_url,
                    publisher=doc.publisher,
                    section=doc.topic,
                    knowledge_version=doc.knowledge_version,
                    retrieved_at=doc.retrieved_at or datetime.utcnow().isoformat()
                )
            )
        return citations

    def get_document(self, document_id: str) -> Optional[KnowledgeChunk]:
        with self._lock:
            return self._documents.get(document_id)

    def get_all_documents(self) -> List[KnowledgeChunk]:
        with self._lock:
            return list(self._documents.values())

    def document_count(self) -> int:
        with self._lock:
            return len(self._documents)


# Global singleton
rag_knowledge_base = RAGKnowledgeBase()

