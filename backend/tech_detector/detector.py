"""
Technology Detection Engine
Inspects HTTP responses, HTML, headers, cookies, scripts, and DOM markers to classify websites.
Adheres strictly to evidence-based detection, honest uncertainty, and custom website classification.
"""

from __future__ import annotations
import re
from typing import Dict, List, Optional, Tuple, Any
from datetime import datetime, timezone
import uuid

from .signatures import CATALOG, TechSignature, get_all_catalog_entries
from .models import (
    ScanResponse,
    TechnologyFinding,
    EvidenceItem,
    SecurityHeaderInfo
)
from .scanner import ScanPayload, SafeTechScanner


SECURITY_HEADERS_TO_CHECK = [
    "content-security-policy",
    "strict-transport-security",
    "x-frame-options",
    "x-content-type-options",
    "referrer-policy",
    "permissions-policy"
]


class TechnologyDetector:
    """Core detection engine evaluating signatures against scanned website payloads."""

    def __init__(self, scanner: Optional[SafeTechScanner] = None):
        self.scanner = scanner or SafeTechScanner()

    def evaluate_signature(
        self,
        sig: TechSignature,
        payload: ScanPayload
    ) -> Tuple[str, str, Optional[str], List[EvidenceItem]]:
        """
        Evaluate a single technology signature against the scan payload.
        Returns (detection_status, confidence, version, evidence_list).
        """
        evidence_items: List[EvidenceItem] = []
        detected_version: Optional[str] = None

        # 1. Inspect HTML Meta Generators
        for gen in payload.meta_generators:
            for pattern in sig.meta_generators:
                match = re.search(pattern, gen, re.IGNORECASE)
                if match:
                    if match.groups() and match.group(1):
                        detected_version = match.group(1)
                    evidence_items.append(EvidenceItem(
                        source="HTML Meta Generator",
                        observed_fact=f'<meta name="generator" content="{gen[:120]}">',
                        inference=f"Explicit platform generator declaration for {sig.name}" + (f" v{detected_version}" if detected_version else ""),
                        confidence="Strong Evidence"
                    ))

        # 2. Inspect HTTP Response Headers
        for h_key, pattern in sig.headers.items():
            val = payload.headers.get(h_key.lower())
            if val:
                match = re.search(pattern, val, re.IGNORECASE)
                if match:
                    if match.groups() and match.group(1) and not detected_version:
                        detected_version = match.group(1)
                    evidence_items.append(EvidenceItem(
                        source="HTTP Response Header",
                        observed_fact=f"{h_key}: {val[:120]}",
                        inference=f"Header '{h_key}' matches signature pattern for {sig.name}",
                        confidence="Strong Evidence"
                    ))

        # 3. Inspect Set-Cookie Headers
        for cookie in payload.cookies:
            for cookie_pat in sig.cookies:
                if re.search(cookie_pat, cookie, re.IGNORECASE):
                    evidence_items.append(EvidenceItem(
                        source="Set-Cookie Header",
                        observed_fact=f"Cookie '{cookie}'",
                        inference=f"Platform-specific session or tracking cookie associated with {sig.name}",
                        confidence="Possible"
                    ))

        # 4. Inspect Script and Style Asset URLs
        all_assets = payload.scripts + payload.styles
        matched_assets = 0
        for asset in all_assets:
            for asset_pat in sig.assets:
                if re.search(asset_pat, asset, re.IGNORECASE):
                    matched_assets += 1
                    if matched_assets <= 2:  # Cap to prevent repetitive items
                        evidence_items.append(EvidenceItem(
                            source="Asset URL",
                            observed_fact=f"Asset link: '{asset[:140]}'",
                            inference=f"Resource path matches distinctive asset pattern for {sig.name}",
                            confidence="Strong Evidence" if "/wp-" in asset or "cdn.shopify.com" in asset or "/_next/" in asset else "Possible"
                        ))
                    break
            if matched_assets >= 3:
                break

        # 5. Inspect HTML Body Patterns
        matched_html = 0
        for html_pat in sig.html_patterns:
            match = re.search(html_pat, payload.html, re.IGNORECASE)
            if match:
                matched_html += 1
                snippet = match.group(0)[:100]
                if matched_html <= 2:
                    evidence_items.append(EvidenceItem(
                        source="HTML Structure",
                        observed_fact=f"Matched: '{snippet}'",
                        inference=f"HTML markup contains characteristic markup element for {sig.name}",
                        confidence="Strong Evidence" if "data-reactroot" in snippet or "__NEXT_DATA__" in snippet or "data-wf-" in snippet else "Possible"
                    ))

        # 6. Inspect DOM Markers / CSS Selectors
        if payload.soup and sig.dom_markers:
            for selector in sig.dom_markers:
                try:
                    el = payload.soup.select_one(selector)
                    if el:
                        snippet = str(el)[:100].replace("\n", " ")
                        evidence_items.append(EvidenceItem(
                            source="DOM Signature",
                            observed_fact=f"Found element matching selector '{selector}': {snippet}",
                            inference=f"Component DOM structure confirms presence of {sig.name}",
                            confidence="Strong Evidence"
                        ))
                except Exception:
                    pass

        # 7. Targeted Safe Probes (e.g. for WordPress /wp-json/)
        if sig.id == "wordpress" and evidence_items:
            # If WordPress hints were observed, probe /wp-json/ to corroborate
            probe_result = self.scanner.probe_path(payload.final_url, "/wp-json/")
            if probe_result and probe_result.get("status") == 200:
                body = probe_result.get("snippet", "")
                if "namespaces" in body or "wp/v2" in body:
                    evidence_items.append(EvidenceItem(
                        source="Public Endpoint Probe",
                        observed_fact="HTTP 200 from /wp-json/ exposing 'wp/v2' namespace",
                        inference="Corroborating public REST API endpoint confirmed WordPress installation",
                        confidence="Strong Evidence"
                    ))

        # Determine overall detection status and confidence
        if not evidence_items:
            return "Not Detected", "Not Detected", None, []

        has_strong = any(e.confidence == "Strong Evidence" for e in evidence_items)
        if has_strong or len(evidence_items) >= 2:
            status = "Strong Evidence"
            conf = "Strong Evidence"
        else:
            status = "Possible"
            conf = "Possible"

        return status, conf, detected_version, evidence_items

    def detect(self, payload: ScanPayload) -> ScanResponse:
        """
        Run all catalog signatures against payload and generate complete ScanResponse.
        """
        scan_id = str(uuid.uuid4())
        scanned_at = datetime.now(timezone.utc).isoformat()

        all_findings: List[TechnologyFinding] = []
        detected_findings: List[TechnologyFinding] = []

        # Check for empty or failing page
        is_empty = len(payload.html.strip()) < 100
        is_error = payload.status_code >= 400

        if not is_error and not is_empty:
            for sig in CATALOG:
                # Skip evaluating Category 12 fallback items until after primary sweep
                if sig.category_id == 12:
                    continue

                status, conf, version, evidence = self.evaluate_signature(sig, payload)
                finding = TechnologyFinding(
                    id=sig.id,
                    name=sig.name,
                    category=sig.category_name,
                    category_id=sig.category_id,
                    detection_status=status,
                    confidence=conf,
                    version=version,
                    evidence=evidence,
                    description=sig.description,
                    explanation=f"{sig.name} detected via {len(evidence)} evidence indicators." if evidence else f"No recognizable signatures of {sig.name} were identified.",
                    limitations=sig.limitations,
                    is_reliably_detectable=sig.is_reliably_detectable
                )
                all_findings.append(finding)
                if status in ("Strong Evidence", "Possible"):
                    detected_findings.append(finding)

            # Evaluate Category 12 (Other Web Technologies / Custom)
            cms_detected = any(f.category_id in (1, 2, 3, 6, 8, 9, 10, 11) for f in detected_findings)
            frontend_framework_detected = any(f.category_id == 4 for f in detected_findings)
            backend_framework_detected = any(f.category_id == 5 for f in detected_findings)

            for sig in CATALOG:
                if sig.category_id != 12:
                    continue

                # Category 12 detection logic
                if sig.id == "plain_html":
                    # Plain HTML is suggested when no CMS and no frontend framework are present on a valid HTML page
                    if not cms_detected and not frontend_framework_detected and not backend_framework_detected and payload.status_code == 200:
                        evidence = [
                            EvidenceItem(
                                source="HTML Structure Analysis",
                                observed_fact="Clean semantic HTML document with standard DOM elements",
                                inference="Document does not contain dynamic CMS markers or frontend framework client bundles",
                                confidence="Possible"
                            )
                        ]
                        finding = TechnologyFinding(
                            id=sig.id,
                            name=sig.name,
                            category=sig.category_name,
                            category_id=12,
                            detection_status="Possible",
                            confidence="Possible",
                            version=None,
                            evidence=evidence,
                            description=sig.description,
                            explanation="The page exhibits straightforward HTML/CSS markup without dynamic application frameworks or CMS indicators.",
                            limitations=sig.limitations,
                            is_reliably_detectable=sig.is_reliably_detectable
                        )
                        all_findings.append(finding)
                        detected_findings.append(finding)
                    else:
                        all_findings.append(TechnologyFinding(
                            id=sig.id,
                            name=sig.name,
                            category=sig.category_name,
                            category_id=12,
                            detection_status="Not Detected",
                            confidence="Not Detected",
                            version=None,
                            evidence=[],
                            description=sig.description,
                            explanation="Dynamic CMS or frontend framework indicators are present.",
                            limitations=sig.limitations,
                            is_reliably_detectable=sig.is_reliably_detectable
                        ))

                else:
                    status, conf, version, evidence = self.evaluate_signature(sig, payload)
                    # If this generic backend language is matched, but a specific CMS/framework already owns it,
                    # keep it as Possible or corroborate
                    finding = TechnologyFinding(
                        id=sig.id,
                        name=sig.name,
                        category=sig.category_name,
                        category_id=12,
                        detection_status=status,
                        confidence=conf,
                        version=version,
                        evidence=evidence,
                        description=sig.description,
                        explanation=f"{sig.name} indicators observed." if evidence else f"No recognizable signatures of {sig.name} were identified.",
                        limitations=sig.limitations,
                        is_reliably_detectable=sig.is_reliably_detectable
                    )
                    all_findings.append(finding)
                    if status in ("Strong Evidence", "Possible"):
                        detected_findings.append(finding)

        else:
            # Site error or empty response: mark all catalog entries as Inconclusive or Not Measured
            for sig in CATALOG:
                finding = TechnologyFinding(
                    id=sig.id,
                    name=sig.name,
                    category=sig.category_name,
                    category_id=sig.category_id,
                    detection_status="Inconclusive" if is_error else "Not Measured",
                    confidence="Inconclusive",
                    version=None,
                    evidence=[],
                    description=sig.description,
                    explanation="Measurement could not be completed because the website response was empty or returned an HTTP error.",
                    limitations=sig.limitations,
                    is_reliably_detectable=sig.is_reliably_detectable
                )
                all_findings.append(finding)

        # Primary Classification and Custom Website Assessment Logic (Section 7)
        primary_classification, primary_summary, primary_category, custom_assessment, is_inconclusive, inconclusive_reasons = (
            self._determine_classification(payload, detected_findings)
        )

        # Security Headers
        security_headers: List[SecurityHeaderInfo] = []
        for h in SECURITY_HEADERS_TO_CHECK:
            val = payload.headers.get(h)
            security_headers.append(SecurityHeaderInfo(
                name=h,
                present=bool(val),
                value=val[:200] if val else None
            ))

        # Standard Scan Limitations
        scan_limitations = [
            "Inspection is non-invasive and relies exclusively on publicly observable HTTP responses and client-side HTML/assets.",
            "Modern CDNs, reverse proxies, and server configurations often strip or replace backend headers (e.g., Server, X-Powered-By).",
            "Headless CMS architectures separate content storage from presentation, often leaving minimal or zero public footprints in the final HTML.",
            "Custom builds and bundlers (Webpack, Vite) minify and rename scripts, which can obscure framework signatures.",
            "Absence of evidence does not confirm the absence of a technology; backend languages and private APIs cannot be determined with certainty from outside."
        ]

        return ScanResponse(
            scan_id=scan_id,
            submitted_url=payload.submitted_url,
            final_url=payload.final_url,
            http_status=payload.status_code,
            is_https=payload.is_https,
            scanned_at=scanned_at,
            primary_classification=primary_classification,
            primary_summary=primary_summary,
            primary_category=primary_category,
            custom_website_assessment=custom_assessment,
            detected_technologies=detected_findings,
            all_catalog_results=all_findings,
            total_detected_count=len(detected_findings),
            catalog_total_count=96,
            security_headers=security_headers,
            scan_limitations=scan_limitations,
            is_inconclusive=is_inconclusive,
            inconclusive_reasons=inconclusive_reasons
        )

    def _determine_classification(
        self,
        payload: ScanPayload,
        detected: List[TechnologyFinding]
    ) -> Tuple[str, str, str, str, bool, List[str]]:
        """
        Synthesize the primary classification and custom website assessment statement
        according to the strict rules in Section 4.D and Section 7.
        """
        if payload.status_code >= 400:
            return (
                "Inconclusive",
                f"Website responded with HTTP status {payload.status_code}. Public content could not be inspected.",
                "Inconclusive",
                "Inconclusive because the website returned an HTTP error code.",
                True,
                [f"Target returned HTTP error {payload.status_code}."]
            )

        if len(payload.html.strip()) < 100:
            return (
                "Inconclusive",
                "Target returned an empty or minimal response payload. Insufficient evidence to classify technology.",
                "Inconclusive",
                "Inconclusive because the available evidence is insufficient to make a determination.",
                True,
                ["Response body contained fewer than 100 bytes of content."]
            )

        # 1. Check for WordPress specifically
        wp = next((f for f in detected if f.id == "wordpress"), None)
        if wp and wp.detection_status == "Strong Evidence":
            ver = f" (v{wp.version})" if wp.version else ""
            return (
                f"WordPress Detected{ver}",
                f"The website displays confirmed WordPress signatures including standard asset structures and generator metadata.",
                "CMS Platforms",
                "A recognized CMS platform (WordPress) is actively powering this website.",
                False,
                []
            )

        # 2. Check for another CMS Platform (Category 1)
        cms = next((f for f in detected if f.category_id == 1 and f.detection_status == "Strong Evidence"), None)
        if cms:
            return (
                f"{cms.name} Detected",
                f"The website displays strong public indicators of {cms.name}.",
                "CMS Platforms",
                f"A recognized CMS platform ({cms.name}) is powering this website.",
                False,
                []
            )

        # 3. Check for E-Commerce Platforms (Category 2)
        ecom = next((f for f in detected if f.category_id == 2 and f.detection_status == "Strong Evidence"), None)
        if ecom:
            return (
                f"E-Commerce Platform Detected ({ecom.name})",
                f"The website displays verified signatures of the {ecom.name} commerce platform.",
                "E-Commerce Platforms",
                f"A recognized e-commerce platform ({ecom.name}) was confirmed.",
                False,
                []
            )

        # 4. Check for Website Builders (Category 3)
        builder = next((f for f in detected if f.category_id == 3 and f.detection_status == "Strong Evidence"), None)
        if builder:
            return (
                f"Website Builder Detected ({builder.name})",
                f"The website is built and hosted using {builder.name}.",
                "Website Builders",
                f"A hosted website builder platform ({builder.name}) was confirmed.",
                False,
                []
            )

        # 5. Check other CMS categories (Headless, Forums, LMS, Enterprise CMS, Blogging)
        other_cms = next((f for f in detected if f.category_id in (6, 8, 9, 10, 11) and f.detection_status == "Strong Evidence"), None)
        if other_cms:
            return (
                f"{other_cms.category} Detected ({other_cms.name})",
                f"The website displays confirmed public signatures of {other_cms.name}.",
                other_cms.category,
                f"A recognized platform ({other_cms.name}) in category '{other_cms.category}' was confirmed.",
                False,
                []
            )

        # 6. Check for Frontend Frameworks (Category 4)
        # Prioritize meta-frameworks (Next.js, Nuxt, SvelteKit, Astro, Remix, Gatsby) over underlying component libraries (React, Vue, Svelte)
        fe_meta = next((f for f in detected if f.id in ("nextjs", "nuxt", "sveltekit", "astro", "remix", "gatsby") and f.detection_status in ("Strong Evidence", "Possible")), None)
        fe = fe_meta or next((f for f in detected if f.category_id == 4 and f.detection_status in ("Strong Evidence", "Possible")), None)
        be = next((f for f in detected if f.category_id == 5 and f.detection_status in ("Strong Evidence", "Possible")), None)

        if fe:
            summary = f"The website runs on the {fe.name} frontend framework."
            if be:
                summary += f" Backend indicators suggest {be.name}."
            return (
                f"Frontend Framework Detected ({fe.name})",
                summary,
                "Frontend Frameworks and Libraries",
                "Custom-developed architecture is possible, but not confirmed. The site utilizes modern application frameworks without a recognized off-the-shelf CMS.",
                False,
                []
            )

        # 7. Check for Backend Frameworks only (Category 5)
        if be:
            return (
                f"Backend Framework Indicators Detected ({be.name})",
                f"Public response headers or cookies suggest {be.name}.",
                "Backend Frameworks",
                "Custom-developed architecture is possible, but not confirmed. Backend framework indicators were observed without a recognized CMS.",
                False,
                []
            )

        # 8. Check for Plain HTML / Custom Web (Category 12)
        plain = next((f for f in detected if f.id == "plain_html"), None)
        if plain:
            return (
                "Plain HTML / CSS Website",
                "The site displays semantic HTML markup with no dynamic CMS or frontend framework dependencies.",
                "Other Web Technologies",
                "No recognized CMS signature was detected from the available evidence. This website may be custom-developed, use a headless or less common CMS, or conceal its technology indicators.",
                False,
                []
            )

        # 9. No Known CMS Signature Detected (Section 7 explicit requirement)
        return (
            "No Known CMS Detected",
            "No recognized CMS or website platform signature was identified from publicly observable responses.",
            "Unclassified / Custom",
            "No recognized CMS signature was detected from the available evidence. This website may be custom-developed, use a headless or less common CMS, or conceal its technology indicators.",
            False,
            []
        )
