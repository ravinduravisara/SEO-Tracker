import sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from backend.report_service import normalize_8_categories

# Test 1: A Rich Business Website (like a dental clinic or local service)
mock_local_business_audit = {
    "score": 82.5,
    "scores": {
        "technical": 8.5,
        "on_page": 8.2,
        "categories": [
            {"category": "Crawlability & Status", "score": 10.0},
            {"category": "Indexability", "score": 10.0},
            {"category": "On-page Fundamentals", "score": 8.5},
            {"category": "Content Quality Signals", "score": 8.8},
            {"category": "Keyword & Topic Signals", "score": 8.2},
            {"category": "Internal Linking", "score": 8.0},
            {"category": "Images & Media", "score": 7.5},
            {"category": "Structured Data", "score": 9.0},
            {"category": "Social / Open Graph", "score": 9.0},
            {"category": "Performance Proxies", "score": 8.0},
            {"category": "Accessibility & Semantics", "score": 9.0},
            {"category": "Web Security Signals", "score": 9.0},
            {"category": "URL Hygiene", "score": 10.0},
            {"category": "Internationalization", "score": 10.0},
            {"category": "Trust & Local Signals", "score": 8.5},
            {"category": "Sitemap & Robots", "score": 10.0},
        ]
    },
    "pages": [
        {
            "url": "https://example-dentist.com",
            "title": "Family Dental Care - Best Dentist in Colombo",
            "meta_description": "Comprehensive family dental clinic in Colombo offering cleanings, implants, and emergency care. Call today.",
            "h1": ["Family Dental Care in Colombo"],
            "h2": ["Our Dental Services", "Why Patients Choose Us", "Meet Our Doctors", "Book an Appointment"],
            "word_count": 850,
            "internal_links": ["/about", "/services", "/contact", "/team", "/emergency", "/faq"],
            "schema_types": ["Dentist", "LocalBusiness", "PostalAddress"],
            "contact_signals": {"has_phone": True, "has_address": True},
            "html": "<address>123 Galle Road, Colombo</address><a href='tel:+94112345678'>Call</a><iframe src='maps.google.com'></iframe>",
            "top_terms": [{"term": "dental", "count": 18}, {"term": "dentist", "count": 12}, {"term": "colombo", "count": 9}, {"term": "care", "count": 7}]
        }
    ],
    "keyword_intelligence": {
        "observed_keywords": ["dental care", "dentist colombo", "family dental", "implants", "teeth cleaning"]
    },
    "stats": {"broken_links": 0}
}

cats = normalize_8_categories(mock_local_business_audit)
print("\n=== LOCAL BUSINESS WEBSITE AUDIT RESULT ===")
for c in cats:
    print(f"  {c['name']:<25}: {c['display']:<15} | {c['status']:<15} | {c['description']}")
