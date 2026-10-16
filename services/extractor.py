import ipaddress
import logging
import socket
from dataclasses import dataclass
from urllib.parse import urljoin, urlparse

import requests
from bs4 import BeautifulSoup


class ExtractionError(Exception):
    pass


@dataclass
class ExtractedPage:
    url: str
    title: str
    text: str
    method: str = "static"


MIN_READABLE_WORDS = 8
MAX_RESPONSE_BYTES = 2_000_000
DEFAULT_DYNAMIC_MIN_WORDS = 40
DEFAULT_DYNAMIC_TIMEOUT_MS = 15_000
logger = logging.getLogger(__name__)
ACCESS_INTERSTITIAL_MARKERS = (
    "one quick check before you continue",
    "you've been blocked by network security",
    "you have been blocked by network security",
    "verify you are human",
    "checking your browser before accessing",
)


def _validate_public_url(url):
    parsed = urlparse(url)
    if parsed.scheme.lower() not in {"http", "https"} or not parsed.hostname:
        raise ExtractionError("Only complete public http:// and https:// URLs are supported.")
    if parsed.username or parsed.password:
        raise ExtractionError("URLs containing usernames or passwords are not allowed.")
    try:
        port = parsed.port
    except ValueError:
        raise ExtractionError("That webpage URL contains an invalid port.") from None
    if port not in (None, 80, 443):
        raise ExtractionError("Only standard web ports 80 and 443 are supported.")
    hostname = parsed.hostname.rstrip(".").lower()
    if hostname == "localhost" or hostname.endswith((".localhost", ".local", ".internal")):
        raise ExtractionError("Private or local webpages cannot be fetched.")
    try:
        addresses = [ipaddress.ip_address(hostname)]
    except ValueError:
        try:
            addresses = [
                ipaddress.ip_address(result[4][0])
                for result in socket.getaddrinfo(
                    hostname, port or (443 if parsed.scheme == "https" else 80)
                )
            ]
        except (OSError, ValueError):
            raise ExtractionError("The webpage address could not be resolved.") from None
    if not addresses or any(
        not address.is_global or address.is_multicast or address.is_unspecified
        for address in addresses
    ):
        raise ExtractionError("Private or local webpages cannot be fetched.")


def _extract_text(html, max_length):
    soup = BeautifulSoup(html, "html.parser")
    title = soup.title.get_text(" ", strip=True) if soup.title else ""
    for element in soup(
        ["script", "style", "noscript", "svg", "iframe", "header", "footer", "nav", "form"]
    ):
        element.decompose()
    main = soup.find("article") or soup.find("main") or soup.body or soup
    text = " ".join(main.stripped_strings)
    return title, " ".join(text.split())[:max_length]


def _extract_static(url, timeout, max_redirects, max_length):
    current_url = url
    headers = {
        "User-Agent": "InsightLens/1.0 (+webpage text analysis)",
        "Accept": "text/html,application/xhtml+xml",
    }
    with requests.Session() as client:
        client.trust_env = False
        for _ in range(max_redirects + 1):
            _validate_public_url(current_url)
            response = client.get(
                current_url,
                headers=headers,
                timeout=timeout,
                allow_redirects=False,
                stream=True,
            )
            if response.is_redirect:
                location = response.headers.get("Location")
                response.close()
                if not location:
                    raise ExtractionError("The webpage returned an invalid redirect.")
                current_url = urljoin(current_url, location)
                continue
            if response.status_code >= 400:
                response.close()
                raise ExtractionError(
                    f"The webpage returned an error (HTTP {response.status_code})."
                )
            content_type = response.headers.get("Content-Type", "").lower()
            if "text/html" not in content_type and "application/xhtml+xml" not in content_type:
                response.close()
                raise ExtractionError("That URL does not appear to contain an HTML webpage.")
            chunks = []
            size = 0
            try:
                for chunk in response.iter_content(chunk_size=8192):
                    if not chunk:
                        continue
                    size += len(chunk)
                    if size > MAX_RESPONSE_BYTES:
                        raise ExtractionError("The webpage is too large to process.")
                    chunks.append(chunk)
                encoding = response.encoding or "utf-8"
            finally:
                response.close()
            html = b"".join(chunks).decode(encoding, errors="replace")
            title, text = _extract_text(html, max_length)
            return ExtractedPage(
                url=current_url,
                title=title or urlparse(current_url).netloc,
                text=text,
            )
    raise ExtractionError("The webpage redirected too many times.")


def _extract_dynamic(url, timeout_ms, max_length):
    try:
        from playwright.sync_api import Error as PlaywrightError
        from playwright.sync_api import sync_playwright
    except ImportError:
        raise ExtractionError(
            "This page needs JavaScript to load its content. Install the optional browser "
            "support with `python -m pip install -r requirements-dynamic.txt` and "
            "`python -m playwright install chromium`."
        ) from None

    blocked_resources = {"image", "media", "font"}

    def validate_request(route):
        request_url = route.request.url
        scheme = urlparse(request_url).scheme.lower()
        if scheme in {"data", "blob", "about"} or route.request.resource_type in blocked_resources:
            route.continue_()
            return
        if not _browser_request_is_public(request_url):
            route.abort()
            return
        route.continue_()

    try:
        with sync_playwright() as playwright:
            browser = playwright.chromium.launch(
                headless=True,
                args=["--disable-dev-shm-usage", "--disable-webrtc"],
            )
            try:
                context = browser.new_context(
                    service_workers="block",
                    accept_downloads=False,
                    ignore_https_errors=False,
                )
                context.route("**/*", validate_request)
                page = context.new_page()
                page.set_default_navigation_timeout(timeout_ms)
                page.set_default_timeout(timeout_ms)
                page.route_web_socket("**/*", lambda websocket: websocket.close())
                page.goto(url, wait_until="domcontentloaded")
                page.wait_for_timeout(min(1_000, timeout_ms // 4))
                final_url = page.url
                _validate_public_url(final_url)
                html = page.content()
                if len(html.encode("utf-8")) > MAX_RESPONSE_BYTES:
                    raise ExtractionError("The webpage is too large to process.")
                title, text = _extract_text(html, max_length)
                return ExtractedPage(
                    url=final_url,
                    title=title or urlparse(final_url).netloc,
                    text=text,
                    method="javascript",
                )
            finally:
                browser.close()
    except ExtractionError:
        raise
    except PlaywrightError:
        raise ExtractionError(
            "We couldn't render this webpage. Check that Chromium is installed and try again."
        ) from None


def _is_access_interstitial(page):
    visible_content = f"{page.title} {page.text[:500]}".casefold()
    return any(marker in visible_content for marker in ACCESS_INTERSTITIAL_MARKERS)


def _browser_request_is_public(request_url):
    try:
        _validate_public_url(request_url)
    except ExtractionError:
        return False
    return True


def extract_webpage(
    url,
    timeout=(5, 15),
    max_redirects=5,
    max_length=100_000,
    dynamic_enabled=True,
    dynamic_min_words=DEFAULT_DYNAMIC_MIN_WORDS,
    dynamic_timeout_ms=DEFAULT_DYNAMIC_TIMEOUT_MS,
):
    current_url = url.strip()
    _validate_public_url(current_url)
    try:
        page = _extract_static(current_url, timeout, max_redirects, max_length)
    except ExtractionError as static_error:
        if "Private or local" in str(static_error):
            raise
        if not dynamic_enabled:
            raise
        try:
            page = _extract_dynamic(current_url, dynamic_timeout_ms, max_length)
        except ExtractionError as dynamic_error:
            if "Private or local" in str(static_error) or "Only complete" in str(static_error):
                raise static_error
            raise dynamic_error from static_error
    except requests.Timeout:
        if not dynamic_enabled:
            raise ExtractionError("The webpage took too long to respond. Please try again.") from None
        page = _extract_dynamic(current_url, dynamic_timeout_ms, max_length)
    except requests.RequestException:
        if not dynamic_enabled:
            raise ExtractionError(
                "We couldn't retrieve that webpage. Check the URL and try again."
            ) from None
        page = _extract_dynamic(current_url, dynamic_timeout_ms, max_length)

    if _is_access_interstitial(page):
        raise ExtractionError(
            "The webpage showed an access or verification check instead of its content."
        )

    if len(page.text.split()) < max(dynamic_min_words, MIN_READABLE_WORDS):
        if not dynamic_enabled or page.method == "javascript":
            if len(page.text.split()) < MIN_READABLE_WORDS:
                raise ExtractionError("We couldn't find enough readable text on that webpage.")
        else:
            static_page = page
            try:
                dynamic_page = _extract_dynamic(current_url, dynamic_timeout_ms, max_length)
            except ExtractionError as dynamic_error:
                if len(static_page.text.split()) < MIN_READABLE_WORDS:
                    raise
                logger.warning(
                    "Dynamic extraction failed; retaining readable static content: %s",
                    dynamic_error,
                )
            else:
                if len(dynamic_page.text.split()) > len(static_page.text.split()):
                    page = dynamic_page
                elif len(static_page.text.split()) < MIN_READABLE_WORDS:
                    page = dynamic_page
                else:
                    logger.warning(
                        "Dynamic extraction returned less text; retaining readable static content."
                    )

    if len(page.text.split()) < MIN_READABLE_WORDS:
        raise ExtractionError("We couldn't find enough readable text on that webpage.")
    return page
