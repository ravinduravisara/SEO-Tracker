"""
SSRF-Safe Website Fetcher and Inspector for Technology Detection
Performs non-invasive, read-only inspections of publicly reachable websites.
"""

from __future__ import annotations
import ipaddress
import logging
import socket
import time
from dataclasses import dataclass
from typing import Dict, List, Optional, Tuple, Any
from urllib.parse import urlparse, urljoin
import requests
from bs4 import BeautifulSoup

logger = logging.getLogger("tech_detector_scanner")

# Constants
MAX_RESPONSE_BYTES = 5_000_000  # 5 MB
DEFAULT_TIMEOUT = 12.0          # 12 seconds
MAX_REDIRECTS = 5
SCANNER_USER_AGENT = (
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
    "(KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36 "
    "(eSupport-Tech-Detector/10.4; +https://esupport.live/)"
)

# Blocked IP networks for SSRF defense
_BLOCKED_NETWORKS = [
    ipaddress.ip_network("0.0.0.0/8"),
    ipaddress.ip_network("10.0.0.0/8"),
    ipaddress.ip_network("100.64.0.0/10"),
    ipaddress.ip_network("127.0.0.0/8"),
    ipaddress.ip_network("169.254.0.0/16"),
    ipaddress.ip_network("172.16.0.0/12"),
    ipaddress.ip_network("192.0.0.0/24"),
    ipaddress.ip_network("192.0.2.0/24"),
    ipaddress.ip_network("192.88.99.0/24"),
    ipaddress.ip_network("192.168.0.0/16"),
    ipaddress.ip_network("198.18.0.0/15"),
    ipaddress.ip_network("198.51.100.0/24"),
    ipaddress.ip_network("203.0.113.0/24"),
    ipaddress.ip_network("224.0.0.0/4"),
    ipaddress.ip_network("240.0.0.0/4"),
    ipaddress.ip_network("255.255.255.255/32"),
    ipaddress.ip_network("::/128"),
    ipaddress.ip_network("::1/128"),
    ipaddress.ip_network("fc00::/7"),
    ipaddress.ip_network("fe80::/10"),
    ipaddress.ip_network("ff00::/8"),
]


def is_public_ip(ip_str: str) -> bool:
    """Validate whether an IP address is publicly routable and not internal/reserved."""
    try:
        ip = ipaddress.ip_address(ip_str)
    except ValueError:
        return False
    if isinstance(ip, ipaddress.IPv6Address) and ip.ipv4_mapped is not None:
        ip = ip.ipv4_mapped
    if ip.is_private or ip.is_loopback or ip.is_link_local or ip.is_reserved or ip.is_multicast or ip.is_unspecified:
        return False
    for net in _BLOCKED_NETWORKS:
        if ip in net:
            return False
    return True


def is_public_hostname(hostname: str) -> Tuple[bool, str]:
    """Resolve hostname and confirm every IP it resolves to is publicly reachable."""
    host = (hostname or "").strip().rstrip(".").lower()
    if not host:
        return False, "Missing hostname."
    if host == "localhost" or host.endswith(".localhost") or host in ("metadata.google.internal", "instance-data"):
        return False, f"Host '{host}' is an internal or disallowed address."
    try:
        infos = socket.getaddrinfo(host, None)
        addresses = {info[4][0] for info in infos}
    except socket.gaierror as exc:
        return False, f"DNS resolution failed for '{host}': {exc}"

    if not addresses:
        return False, f"DNS resolution returned no IP addresses for '{host}'."

    blocked = [ip for ip in addresses if not is_public_ip(ip)]
    if blocked:
        return False, f"Host '{host}' resolves to non-public address ({blocked[0]}); internal and cloud metadata destinations are blocked."

    return True, ""


def validate_and_normalize_url(url: str) -> str:
    """
    Validate URL syntax, require http/https scheme, and verify destination is public.
    Raises ValueError with descriptive reason if invalid or disallowed.
    """
    raw = (url or "").strip()
    if not raw:
        raise ValueError("URL cannot be empty.")
    if not (raw.startswith("http://") or raw.startswith("https://")):
        raw = "https://" + raw

    parsed = urlparse(raw)
    if parsed.scheme not in ("http", "https"):
        raise ValueError("Only http:// and https:// URLs are supported.")

    hostname = parsed.hostname
    if not hostname:
        raise ValueError("URL is missing a valid hostname.")

    ok, reason = is_public_hostname(hostname)
    if not ok:
        raise ValueError(reason)

    path = parsed.path or "/"
    normalized = f"{parsed.scheme}://{parsed.netloc}{path}"
    if parsed.query:
        normalized += f"?{parsed.query}"
    return normalized


@dataclass
class ScanPayload:
    submitted_url: str
    final_url: str
    status_code: int
    is_https: bool
    headers: Dict[str, str]
    cookies: List[str]
    html: str
    soup: BeautifulSoup
    scripts: List[str]
    styles: List[str]
    meta_generators: List[str]
    all_meta: List[Dict[str, str]]
    comments: List[str]
    truncated: bool = False
    error: Optional[str] = None


class SafeTechScanner:
    """Safe HTTP client executing non-invasive technology detection scans."""

    def __init__(self, timeout: float = DEFAULT_TIMEOUT):
        self.timeout = timeout
        self.session = requests.Session()
        # Set clean browser-like headers; DO NOT forward application cookies or secrets
        self.session.headers.update({
            "User-Agent": SCANNER_USER_AGENT,
            "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,image/avif,image/webp,*/*;q=0.8",
            "Accept-Language": "en-US,en;q=0.9",
            "Cache-Control": "no-cache",
            "Pragma": "no-cache",
        })

    def fetch(self, url: str) -> ScanPayload:
        """
        Fetch the target website safely, following up to MAX_REDIRECTS with SSRF verification at every step.
        """
        validated_url = validate_and_normalize_url(url)
        current_url = validated_url
        history_hops: List[str] = []

        response = None
        for _ in range(MAX_REDIRECTS + 1):
            # SSRF check on current step
            parsed = urlparse(current_url)
            ok, reason = is_public_hostname(parsed.hostname or "")
            if not ok:
                raise ValueError(f"Redirect hop blocked: {reason}")

            try:
                response = self.session.get(
                    current_url,
                    timeout=self.timeout,
                    allow_redirects=False,
                    stream=True,
                    verify=True,
                )
            except requests.exceptions.SSLError as ssl_err:
                # Fallback to verify=False if site has self-signed/expired cert, while preserving SSRF protection
                logger.warning("SSL verification failed for %s (%s); retrying with verify=False", current_url, ssl_err)
                response = self.session.get(
                    current_url,
                    timeout=self.timeout,
                    allow_redirects=False,
                    stream=True,
                    verify=False,
                )
            except requests.exceptions.RequestException as req_err:
                raise RuntimeError(f"Network connection failed: {req_err}")

            if response.is_redirect or response.status_code in (301, 302, 303, 307, 308):
                location = response.headers.get("Location")
                if not location:
                    break
                next_url = urljoin(current_url, location)
                history_hops.append(current_url)
                current_url = next_url
                response.close()
            else:
                break

        if response is None:
            raise RuntimeError("No HTTP response received from target.")

        # Read response body with 5MB size limit
        content_chunks = []
        bytes_read = 0
        truncated = False
        try:
            for chunk in response.iter_content(chunk_size=16384):
                if not chunk:
                    break
                bytes_read += len(chunk)
                if bytes_read > MAX_RESPONSE_BYTES:
                    truncated = True
                    break
                content_chunks.append(chunk)
        finally:
            response.close()

        raw_bytes = b"".join(content_chunks)

        # Detect encoding safely
        encoding = response.encoding or "utf-8"
        try:
            html_text = raw_bytes.decode(encoding, errors="replace")
        except Exception:
            html_text = raw_bytes.decode("utf-8", errors="replace")

        # Parse with BeautifulSoup
        soup = BeautifulSoup(html_text, "html.parser")

        # Extract meta tags
        meta_generators: List[str] = []
        all_meta: List[Dict[str, str]] = []
        for m in soup.find_all("meta"):
            attrs = {k.lower(): str(v) for k, v in m.attrs.items()}
            all_meta.append(attrs)
            if attrs.get("name", "").lower() == "generator" and attrs.get("content"):
                meta_generators.append(attrs["content"].strip())
            elif attrs.get("property", "").lower() == "generator" and attrs.get("content"):
                meta_generators.append(attrs["content"].strip())

        # Extract script src and inline snippets
        scripts: List[str] = []
        for s in soup.find_all("script"):
            src = s.get("src")
            if src:
                scripts.append(str(src))
            elif s.string:
                scripts.append(s.string[:2000])

        # Extract style and link hrefs
        styles: List[str] = []
        for link in soup.find_all("link"):
            href = link.get("href")
            if href:
                styles.append(str(href))

        # Extract HTML comments (first 50)
        comments: List[str] = []
        from bs4 import Comment
        for c in soup.find_all(string=lambda text: isinstance(text, Comment))[:50]:
            comments.append(str(c).strip())

        # Format headers and cookies
        clean_headers = {k.lower(): str(v) for k, v in response.headers.items()}
        cookies_list: List[str] = []
        for cookie_header in response.headers.getlist("Set-Cookie") if hasattr(response.headers, "getlist") else []:
            cookie_name = cookie_header.split("=")[0].strip()
            cookies_list.append(cookie_name)
        if not cookies_list and "set-cookie" in clean_headers:
            cookie_name = clean_headers["set-cookie"].split("=")[0].strip()
            cookies_list.append(cookie_name)

        final_parsed = urlparse(current_url)

        return ScanPayload(
            submitted_url=url,
            final_url=current_url,
            status_code=response.status_code,
            is_https=final_parsed.scheme == "https",
            headers=clean_headers,
            cookies=cookies_list,
            html=html_text,
            soup=soup,
            scripts=scripts,
            styles=styles,
            meta_generators=meta_generators,
            all_meta=all_meta,
            comments=comments,
            truncated=truncated
        )

    def probe_path(self, base_url: str, probe_path: str) -> Optional[Dict[str, Any]]:
        """
        Safely execute a targeted probe request (e.g., '/wp-json/') to confirm a platform signature.
        SSRF protected, short 3-second timeout, non-invasive GET.
        """
        try:
            target = urljoin(base_url, probe_path)
            validate_and_normalize_url(target)
            resp = self.session.get(target, timeout=3.0, allow_redirects=False, verify=False)
            status = resp.status_code
            headers = {k.lower(): str(v) for k, v in resp.headers.items()}
            body_snippet = resp.text[:1000] if resp.text else ""
            resp.close()
            return {"status": status, "headers": headers, "snippet": body_snippet}
        except Exception:
            return None
