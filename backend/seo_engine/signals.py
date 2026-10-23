"""Raw-evidence extraction for the scoring engine (spec PART B step 6).

Called by the crawler's HTML parser with the BeautifulSoup tree of the *raw* fetched HTML.
Everything here is an observation (counts, flags, exact strings); nothing is scored here.
Strings are preserved as served (e.g. a heading that reads "---" stays "---", spec O12/L23).
"""
from __future__ import annotations

import json
import re
from typing import Any
from urllib.parse import urldefrag, urljoin, urlparse

NAV_CONTAINERS = ("nav", "header", "footer")
CTA_WORDS = re.compile(r"\b(contact|quote|enquir|inquir|book|buy|order|call|email|get started|request|subscribe|download|whatsapp|chat)", re.I)
EMAIL_RE = re.compile(r"\b[A-Z0-9._%+-]+@[A-Z0-9.-]+\.[A-Z]{2,}\b", re.I)
PHONE_RE = re.compile(r"(?<![\w/.])\+?\(?\d[\d\s().-]{7,18}\d(?![\w/])")
POSTAL_RE = re.compile(r"\b\d{5}\b|\b\d{4,6}\b(?=[^\n]{0,30}\b(?:sri lanka|lk|india|usa|uk)\b)", re.I)
HOURS_RE = re.compile(
    r"opening hours|business hours|office hours|working hours|open (?:daily|24)|"
    r"\b(?:mon|monday)\s*(?:-|–|to)\s*(?:fri|friday|sat|saturday|sun|sunday)\b|"
    r"\b\d{1,2}(?:[:.]\d{2})?\s*(?:am|a\.m\.)\s*(?:-|–|to)\s*\d{1,2}(?:[:.]\d{2})?\s*(?:pm|p\.m\.)", re.I)
SPEC_RE = re.compile(r"\b\d+(?:[.,]\d+)?\s?(?:kva|kw|kwh|hp|v|vac|vdc|a|amp|hz|bar|psi|mpa|kpa|rpm|l/min|lpm|m3/h|m³/h|gpm|mm|cm|kg|ton|tonnes|°c|w|mah|ah|db|lumens?|m head|m\b)", re.I)
MODEL_RE = re.compile(r"\b[A-Z]{1,5}[- ]?\d{2,5}[A-Z]{0,3}\b")
PRICE_RE = re.compile(r"(?:rs\.?|lkr|usd|us\$|\$|€|£|inr|₹)\s?\d[\d,]*(?:\.\d+)?|\b\d[\d,]*(?:\.\d+)?\s?(?:lkr|usd|rs)\b|price[s]?\s*(?:from|starting)", re.I)
QUOTE_RE = re.compile(r"request (?:a )?quot|get (?:a )?quot|free quot|ask for (?:a )?price|price on request|contact (?:us )?for (?:a )?(?:price|quot)", re.I)
STOCK_RE = re.compile(r"\b(?:in stock|out of stock|ex[- ]?stock|lead time|available from stock|ships in|delivery within|indent)\b", re.I)
SELECTION_RE = re.compile(r"how to choose|selection guide|which .{0,30} is right|choosing (?:the|a)|applications?\b|suitable for|ideal for", re.I)
ITINERARY_RE = re.compile(r"\bday\s*0?1\b|\bday one\b|itinerary", re.I)
DURATION_RE = re.compile(r"\b\d+\s*(?:days?|nights?)\b|group size|departure|pick[- ]?up point|starting point", re.I)
INCLUSIONS_RE = re.compile(r"\binclusions?\b|\bexclusions?\b|what'?s included|not included|price includes", re.I)
REVIEWS_RE = re.compile(r"tripadvisor|google reviews|trustpilot|testimonials?|reviews?\b|rated \d", re.I)
LICENCE_RE = re.compile(r"\bsltda\b|licen[cs]ed|registration no|reg\.? no|member of|iata\b|asta\b|association", re.I)
EXPERIENCE_RE = re.compile(r"case stud|our projects|projects completed|completed projects|portfolio|clients? include|installations?|we have (?:supplied|installed|completed)|testimonial", re.I)
PLACEHOLDER_RE = re.compile(r"lorem ipsum|dolor sit amet|hello world!|sample page|just another wordpress site|your company name|insert (?:text|content) here|placeholder text|coming soon", re.I)
ZERO_COUNTER_RE = re.compile(r"(?<![\d.,])0\s*\+|(?<![\d.,])0\s*%\s*(?:satisf|happy|client)|(?<![\d.,])0\s+(?:projects|clients|customers|years|happy)", re.I)
EMAIL_INVITE_RE = re.compile(r"(?:send|drop|write) us an? e-?mail|e-?mail us\b|contact us (?:by|via) e-?mail", re.I)
FAQ_RE = re.compile(r"frequently asked|\bfaqs?\b", re.I)
SHIPPING_RE = re.compile(r"shipping|delivery (?:policy|information|charges)|returns? policy|refund policy", re.I)
CART_RE = re.compile(r"add to cart|add to basket|add to bag|buy now|checkout", re.I)
BOOKING_RE = re.compile(r"book now|book this|enquire now|inquire now|reserve|check availability|request (?:a )?booking", re.I)
MESSAGING_HOSTS = ("wa.me", "api.whatsapp.com", "chat.whatsapp.com", "whatsapp.com/send", "m.me/", "viber://", "t.me/", "line.me")


def _digits(s: str) -> str:
    return re.sub(r"\D", "", s)


def _phones_in_text(text: str) -> list[str]:
    out = []
    for m in PHONE_RE.finditer(text):
        raw = m.group(0).strip()
        d = _digits(raw)
        if not 9 <= len(d) <= 13:
            continue
        if re.fullmatch(r"(19|20)\d{2}\s*[-–]\s*(19|20)\d{2}", raw):
            continue  # year range, not a phone
        if d not in out:
            out.append(d)
    return out[:10]


def _zone(tag) -> str:
    for parent in tag.parents:
        name = getattr(parent, "name", None)
        if name in NAV_CONTAINERS:
            return "nav"
        role = (parent.get("role") or "").lower() if hasattr(parent, "get") else ""
        if role in ("navigation", "banner", "contentinfo"):
            return "nav"
    return "body"


def extract_signals(soup, text: str, raw_html: str, page: dict[str, Any], base_url: str, same_site) -> dict[str, Any]:
    low = text.lower()
    raw_low = raw_html.lower()
    final_url = page.get("url", base_url)

    links: list[dict[str, str]] = []
    dead_ctas: list[str] = []
    tel: list[str] = []
    mailto: list[str] = []
    pdf_docs = 0
    messaging = False
    maps_link = False
    for a in soup.find_all("a"):
        href = (a.get("href") or "").strip()
        label = re.sub(r"\s+", " ", a.get_text(" ", strip=True))[:120]
        hl = href.lower()
        if hl.startswith("tel:"):
            d = _digits(hl[4:])
            label_digits = _digits(label)
            if d and label_digits and len(label_digits) >= 7 and d != label_digits and not label_digits.endswith(d) and not d.endswith(label_digits):
                dead_ctas.append(f"Mismatched call link: '{label}' dials tel:{hl[4:]}")
            elif d in ("6031112298", "1234567890", "12345678", "0123456789", "9876543210"):
                dead_ctas.append(f"Demo template call link dials demo number tel:{hl[4:]}")
            if d and d not in tel:
                tel.append(d)
            continue
        if hl.startswith("mailto:"):
            addr = hl[7:].split("?")[0]
            if addr and addr not in mailto:
                mailto.append(addr)
            continue
        if any(h in hl for h in MESSAGING_HOSTS):
            messaging = True
        if ("google." in hl and "/maps" in hl) or "maps.google." in hl or "goo.gl/maps" in hl or "maps.app.goo.gl" in hl:
            maps_link = True
        if not href or href == "#" or hl.startswith("javascript:"):
            if label and CTA_WORDS.search(label):
                dead_ctas.append(label)
            continue
        u = urldefrag(urljoin(base_url, href))[0]
        if urlparse(u).path.lower().endswith(".pdf"):
            pdf_docs += 1
        if u.startswith(("http://", "https://")) and same_site(u, final_url):
            if len(links) < 400:
                links.append({"u": u, "t": label.lower(), "z": _zone(a)})
    for b in soup.find_all("button"):
        label = re.sub(r"\s+", " ", b.get_text(" ", strip=True))[:120]
        if label and CTA_WORDS.search(label) and not b.find_parent("form") and not (b.get("onclick") or b.get("data-href") or b.get("data-toggle") or b.get("data-bs-toggle") or b.get("aria-controls")):
            dead_ctas.append(label)

    forms = []
    for f in soup.find_all("form"):
        inputs = f.find_all(["input", "textarea", "select"])
        visible = [i for i in inputs if (i.get("type") or "").lower() not in ("hidden", "submit", "button", "image", "reset")]
        names = [((i.get("name") or i.get("id") or i.get("placeholder") or "")[:40]).lower() for i in visible]
        is_search = (f.get("role") or "").lower() == "search" or (len(visible) <= 1 and any(n in ("s", "q", "search", "query", "keyword") for n in names))
        values = []
        for i in visible:
            if i.name == "select":
                opt = i.find("option", selected=True)
                if opt is not None:
                    values.append(re.sub(r"\s+", " ", opt.get_text(" ", strip=True))[:80].lower())
            elif i.name == "textarea":
                if i.get_text(strip=True):
                    values.append(i.get_text(" ", strip=True)[:80].lower())
            elif i.get("value"):
                values.append(str(i.get("value"))[:80].lower())
        forms.append({
            "search": is_search,
            "email_field": any((i.get("type") or "").lower() == "email" or "mail" in ((i.get("name") or "") + (i.get("id") or "")).lower() for i in visible),
            "textarea": any(i.name == "textarea" for i in visible),
            "field_count": len(visible),
            "fields": names[:20],
            "values": values[:20],
        })

    address_bits = []
    for addr in soup.find_all("address"):
        address_bits.append(re.sub(r"\s+", " ", addr.get_text(" ", strip=True))[:300])
    schema_blob = json.dumps(page.get("schema_nodes") or [], default=str).lower()
    schema_address = '"streetaddress"' in schema_blob
    schema_postal = '"postalcode"' in schema_blob
    address_text = " | ".join(address_bits)
    if not address_text:
        m = re.search(r"(?:address|location|head office|office|showroom|find us|visit us)\s*[:\-]\s*([^\n|]{15,160})", text, re.I)
        if m:
            address_text = m.group(1).strip()
    if not address_text:
        m = re.search(r"\b([A-Za-z0-9\s.-]+(?:Road|Street|Mawatha|Lane|Rd|St)\s*,\s*[A-Za-z\s]+)", text, re.I)
        if m:
            address_text = m.group(1).strip()

    frames = [str(f.get("src") or "").lower() for f in soup.find_all("iframe")]
    map_embed = any(("google." in x and "/maps" in x) or "maps.google." in x for x in frames)
    breadcrumb_visible = bool(
        soup.find(attrs={"aria-label": re.compile("breadcrumb", re.I)})
        or soup.find(class_=re.compile(r"breadcrumb", re.I))
        or soup.find(id=re.compile(r"breadcrumb", re.I))
    )
    faq_content = bool(FAQ_RE.search(" ".join(h.get("text", "") for h in page.get("heading_order", []))))
    if not faq_content:
        faq_content = sum(1 for h in page.get("heading_order", []) if h.get("text", "").strip().endswith("?")) >= 3

    hours_match = HOURS_RE.search(text)
    hours_text = hours_match.group(0) if hours_match else ""

    return {
        "fetch_method": "raw_http",
        "script_tags": len(soup.find_all("script")),
        "jsonld_blocks": len(soup.find_all("script", type=lambda x: str(x or "").lower() == "application/ld+json")),
        "links": links,
        "dead_ctas": dead_ctas[:20],
        "forms": forms[:10],
        "tel": tel[:10],
        "mailto": mailto[:10],
        "phones_text": _phones_in_text(text),
        "emails_text": sorted({e.lower() for e in EMAIL_RE.findall(text)})[:10],
        "messaging": messaging,
        "address_text": address_text[:300],
        "schema_address": schema_address,
        "postal_code": schema_postal or bool(address_text and POSTAL_RE.search(address_text)),
        "hours": "openinghours" in schema_blob or bool(hours_match),
        "hours_text": hours_text,
        "map_embed": map_embed,
        "maps_link": maps_link,
        "breadcrumb_visible": breadcrumb_visible,
        "analytics": {
            "ga4": bool(re.search(r"\bG-[A-Z0-9]{6,}\b", raw_html)) or "gtag(" in raw_low,
            "gtm": "googletagmanager.com/gtm.js" in raw_low or bool(re.search(r"\bGTM-[A-Z0-9]{4,}\b", raw_html)),
        },
        "spec_figures": len(SPEC_RE.findall(text)),
        "model_numbers": len(set(MODEL_RE.findall(text))),
        "prices": len(PRICE_RE.findall(text)),
        "quote_cta": bool(QUOTE_RE.search(text)),
        "stock": bool(STOCK_RE.search(text)),
        "selection": bool(SELECTION_RE.search(text)),
        "pdf_docs": pdf_docs,
        "itinerary": bool(ITINERARY_RE.search(text)),
        "duration": bool(DURATION_RE.search(text)),
        "inclusions": bool(INCLUSIONS_RE.search(text)),
        "reviews": (bool(REVIEWS_RE.search(text)) and not bool(re.search(r"\b(?:reviews?\s*\(0\)|no reviews yet|0 reviews|0 customer reviews)\b", text, re.I))) or '"aggregaterating"' in schema_blob,
        "licence": bool(LICENCE_RE.search(text)),
        "experience": len(EXPERIENCE_RE.findall(text)),
        "placeholder": sorted({m.group(0).lower() for m in PLACEHOLDER_RE.finditer(text)})[:5],
        "zero_counters": [m.group(0) for m in ZERO_COUNTER_RE.finditer(text)][:5],
        "email_invite": bool(EMAIL_INVITE_RE.search(text)),
        "faq_content": faq_content,
        "shipping_returns": bool(SHIPPING_RE.search(text)),
        "cart": bool(CART_RE.search(text)),
        "booking_cta": bool(BOOKING_RE.search(text)),
        "text_head": low[:1500],
    }
