import sys
sys.path.insert(0, ".")
from backend.seo_engine import run_engine

# Construct reference crawl dataset matching the 15 sampled pages from PDF
data = {
    "target": "https://nattandiyaelectricals.lk",
    "pages": [
        {
            "url": "https://nattandiyaelectricals.lk/",
            "status": 200,
            "title": "Buy Electrical Items Online | Nattandiya Electricals",
            "meta_description": "Buy Electrical Items Online In Sri Lanka from Nattandiya Electricals. Switches, sockets, cables, breakers and lighting with islandwide cash on delivery.",
            "h1": [],
            "heading_order": [{"tag": "h6", "text": "Site Navigation"}, {"tag": "h4", "text": "+94 76 00 399 61"}],
            "word_count": 6988,
            "editorial_word_count": 45,
            "viewport": "width=device-width, initial-scale=1.0, maximum-scale=1",
            "canonical": "https://nattandiyaelectricals.lk/",
            "og": {"og:title": "Buy Electrical Items Online | Nattandiya Electricals", "og:description": "Online store", "og:image": "https://nattandiyaelectricals.lk/logo.png", "og:url": "https://nattandiyaelectricals.lk/", "og:locale": "en_US"},
            "images": [{"src": "https://nattandiyaelectricals.lk/slider1.jpg", "alt": "bacola"}, {"src": "https://nattandiyaelectricals.lk/slider2.jpg", "alt": "rgdfrg"}]
        },
        {
            "url": "https://nattandiyaelectricals.lk/shop/",
            "status": 200,
            "title": "Buy Electrical Items & Home Appliances Online In Sri Lanka | Nattandiya Electricals",
            "meta_description": "Browse our full catalogue of electrical items and home appliances in Sri Lanka with prices.",
            "h1": [],
            "heading_order": [{"tag": "h6", "text": "Site Navigation"}],
            "word_count": 1126,
            "editorial_word_count": 0,
            "canonical": "https://nattandiyaelectricals.lk/shop/",
            "og": {"og:title": "Shop", "og:url": "https://nattandiyaelectricals.lk/shop/product-1/"}
        },
        {
            "url": "https://nattandiyaelectricals.lk/product-category/switches-sockets/",
            "status": 200,
            "title": "Switches & Sockets - Nattandiya Electricals",
            "meta_description": "Switches and sockets in Sri Lanka.",
            "h1": [],
            "word_count": 800,
            "editorial_word_count": 0,
            "canonical": "https://nattandiyaelectricals.lk/product-category/switches-sockets/",
            "og": {"og:title": "Switches", "og:url": "https://nattandiyaelectricals.lk/shop/switch-1/"}
        },
        {
            "url": "https://nattandiyaelectricals.lk/product-category/geyzer/",
            "status": 200,
            "title": "Geyzer (Bathroom Water Heater) - Nattandiya Electricals",
            "meta_description": "Delmege geysers in Sri Lanka with warranty and islandwide delivery.",
            "h1": [],
            "word_count": 450,
            "editorial_word_count": 59,
            "canonical": "https://nattandiyaelectricals.lk/product-category/geyzer/"
        },
        {
            "url": "https://nattandiyaelectricals.lk/product-category/water-heaters/",
            "status": 200,
            "title": "Water Heaters - Nattandiya Electricals",
            "meta_description": "",
            "h1": [],
            "word_count": 472,
            "editorial_word_count": 0,
            "canonical": "https://nattandiyaelectricals.lk/product-category/water-heaters/"
        },
        {
            "url": "https://nattandiyaelectricals.lk/product-category/uncategorized/",
            "status": 200,
            "title": "Uncategorized - Nattandiya Electricals",
            "meta_description": "",
            "h1": [],
            "word_count": 300,
            "editorial_word_count": 0,
            "canonical": "https://nattandiyaelectricals.lk/product-category/uncategorized/"
        },
        {
            "url": "https://nattandiyaelectricals.lk/brand/kevilton/",
            "status": 200,
            "title": "Kevilton Archives - Nattandiya Electricals",
            "meta_description": "Kevilton brand electrical items.",
            "h1": [],
            "word_count": 600,
            "editorial_word_count": 129,
            "canonical": "https://nattandiyaelectricals.lk/brand/kevilton/"
        },
        {
            "url": "https://nattandiyaelectricals.lk/shop/1-gang-1-way-switch-kevilton-nature/",
            "status": 200,
            "title": "Best 1 Gang 1 Way Switch - Kevilton Nature",
            "meta_description": "Kevilton Nature 1 gang 1 way switch with SLS 1000 standard and lifetime warranty.",
            "h1": ["1 Gang 1 Way Switch Kevilton Nature"],
            "heading_order": [{"tag": "h1", "text": "1 Gang 1 Way Switch"}, {"tag": "h2", "text": "Description"}],
            "word_count": 65,
            "editorial_word_count": 65,
            "prose_word_count": 0,
            "canonical": "https://nattandiyaelectricals.lk/shop/1-gang-1-way-switch-kevilton-nature/",
            "commerce_signals": {"has_availability": True, "has_reviews": False}
        },
        {
            "url": "https://nattandiyaelectricals.lk/shop/rcd-alpha-2-pole-40a-30m/",
            "status": 200,
            "title": "Best RCD Alpha 2 Pole 40A",
            "meta_description": "RCD Alpha 2 pole 40A 30mA protection device IEC 60898.",
            "h1": ["RCD Alpha 2 Pole 40A 30mA"],
            "word_count": 60,
            "editorial_word_count": 60,
            "prose_word_count": 0,
            "canonical": "https://nattandiyaelectricals.lk/shop/rcd-alpha-2-pole-40a-30m/",
            "commerce_signals": {"has_availability": True, "has_reviews": False}
        },
        {
            "url": "https://nattandiyaelectricals.lk/shop/12w-cool-white-sunk-round-plastic/",
            "status": 200,
            "title": "Best LED Panel Light 12W Cool White Sunk Round Plastic",
            "meta_description": "12W cool white panel light.",
            "h1": ["12W Cool White Sunk Round Plastic"],
            "word_count": 21,
            "editorial_word_count": 21,
            "prose_word_count": 0,
            "canonical": "https://nattandiyaelectricals.lk/shop/12w-cool-white-sunk-round-plastic/",
            "commerce_signals": {"has_availability": True, "has_reviews": False}
        },
        {
            "url": "https://nattandiyaelectricals.lk/about-us/",
            "status": 200,
            "title": "Nattandiya Electricals | Buy Quality Electrical Items In Sri Lanka",
            "meta_description": "About Nattandiya Electricals Kuliyapitiya Road showroom.",
            "h1": [],
            "word_count": 580,
            "editorial_word_count": 580,
            "canonical": "https://nattandiyaelectricals.lk/about-us/"
        },
        {
            "url": "https://nattandiyaelectricals.lk/contact/",
            "status": 200,
            "title": "Contact Us - Nattandiya Electricals",
            "meta_description": "Contact Nattandiya Electricals.",
            "h1": ["Get In Touch"],
            "word_count": 350,
            "editorial_word_count": 200,
            "canonical": "https://nattandiyaelectricals.lk/contact/",
            "links": [
                {"u": "tel:6031112298", "t": "+94 76 00 399 61 Call us (mobile /whatsapp)", "z": "body"},
                {"u": "mailto:nattandiyaelectricals@gmail.com", "t": "email us", "z": "body"}
            ]
        },
        {
            "url": "https://nattandiyaelectricals.lk/blog/",
            "status": 200,
            "title": "Blog - Nattandiya Electricals",
            "meta_description": "",
            "h1": [],
            "word_count": 400,
            "editorial_word_count": 100,
            "canonical": "https://nattandiyaelectricals.lk/blog/"
        },
        {
            "url": "https://nattandiyaelectricals.lk/things-to-know-before-getting-a-quotation/",
            "status": 200,
            "title": "8 Key Points to Know Before Getting a Quotation for Your Wiring",
            "meta_description": "Wiring quotation checklist.",
            "h1": ["Point 1", "Point 2", "Point 3", "Point 4", "Point 5", "Point 6", "Point 7", "Point 8"],
            "word_count": 950,
            "editorial_word_count": 950,
            "canonical": "https://nattandiyaelectricals.lk/things-to-know-before-getting-a-quotation/"
        },
        {
            "url": "https://nattandiyaelectricals.lk/privacy-policy/",
            "status": 200,
            "title": "Privacy Policy - Nattandiya Electricals",
            "meta_description": "",
            "h1": ["Privacy Policy"],
            "word_count": 800,
            "editorial_word_count": 600,
            "canonical": "https://nattandiyaelectricals.lk/privacy-policy/"
        }
    ],
    "sitemap": {
        "detected": "https://nattandiyaelectricals.lk/sitemap_index.xml",
        "urls": ["https://nattandiyaelectricals.lk/" for _ in range(1176)],
        "files": [{"url": "https://nattandiyaelectricals.lk/sitemap_index.xml", "status": 200}]
    },
    "sitemap_set": [
        "https://nattandiyaelectricals.lk/cart/",
        "https://nattandiyaelectricals.lk/checkout/",
        "https://nattandiyaelectricals.lk/my-account/"
    ],
    "robots": {
        "found": True,
        "url": "https://nattandiyaelectricals.lk/robots.txt",
        "content": "User-agent: *\nDisallow: /wp-admin/\nAllow: /wp-admin/admin-ajax.php\nSitemap: https://nattandiyaelectricals.lk/sitemap_index.xml",
        "googlebot_allows_root": True,
        "sitemaps": ["https://nattandiyaelectricals.lk/sitemap_index.xml"]
    },
    "probes": {
        "probes": [{"control": True, "url": "https://nattandiyaelectricals.lk/this-does-not-exist-xyz", "status": 404, "final_url": "https://nattandiyaelectricals.lk/this-does-not-exist-xyz"}]
    }
}

payload = run_engine(data)
print("\n=======================================================")
print(f"Overall Score: {payload['score']['overall']} / 100 ({payload['score']['grade']})")
print("=======================================================")
for cat in payload["categories"]:
    print(f"  {cat['name']:<30}: {cat['score']:>3} / 100  (weight={cat['weight']:>2}, contribution={cat['weighted_contribution']:>5.1f})")
print(f"Total weighted sum: {sum(c['weighted_contribution'] for c in payload['categories']):.1f}")
