"""HTTP fetches: short-link resolution, place preview, image probe.

Read-only. GET only, with retries on 429 and 5xx. Hosts are limited to
Google Maps, goo.gl short links, and googleusercontent image CDNs.
"""

from __future__ import annotations

import asyncio
import random
import re
from dataclasses import dataclass
from html import unescape
from urllib.parse import quote, urljoin, urlparse

import httpx

from gmaps_status.models import CONSENT_COOKIE, SOCS_COOKIE, USER_AGENT
from gmaps_status.parse import is_maps_host

_RETRY = frozenset({429, 500, 502, 503, 504})
_DEAD = frozenset({404, 410})
_PREVIEW = re.compile(r'(/maps/preview/place\?[^"\'<>\\]{20,})')
_BLOCK = re.compile(r"unusual traffic|/sorry/|detected unusual traffic", re.IGNORECASE)


@dataclass
class Resolved:
    final_url: str
    status: int | None
    body: str
    dead: bool = False
    dead_reason: str = ""
    blocked_reason: str = ""
    error: str = ""


@dataclass
class PlacePreview:
    body: str = ""
    size: int | None = None
    error: str = ""
    trustworthy: bool = False


def browser_headers() -> dict[str, str]:
    return {
        "User-Agent": USER_AGENT,
        "Accept-Language": "en-US,en;q=0.9",
        "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
        "Cookie": f"CONSENT={CONSENT_COOKIE}; SOCS={SOCS_COOKIE}",
    }


def make_client(timeout: float, proxy: str | None) -> httpx.AsyncClient:
    kwargs: dict = {
        "headers": browser_headers(),
        "timeout": httpx.Timeout(timeout),
        "follow_redirects": False,
        "limits": httpx.Limits(max_connections=12, max_keepalive_connections=6),
    }
    if proxy:
        kwargs["proxy"] = proxy
    return httpx.AsyncClient(**kwargs)


async def request(
    client: httpx.AsyncClient,
    method: str,
    url: str,
    *,
    follow_redirects: bool = False,
    attempts: int = 4,
) -> httpx.Response:
    """GET/HEAD with exponential backoff. The caller reads the body."""

    delay = 0.6
    last_error: Exception | None = None
    for attempt in range(attempts):
        try:
            response = await client.request(method, url, follow_redirects=follow_redirects)
        except (httpx.TimeoutException, httpx.TransportError) as exc:
            last_error = exc
            if attempt + 1 >= attempts:
                raise
            await asyncio.sleep(delay + random.random() * 0.3)
            delay *= 2
            continue
        if response.status_code in _RETRY and attempt + 1 < attempts:
            retry_after = response.headers.get("retry-after", "")
            wait = delay
            if retry_after.isdigit():
                wait = min(float(retry_after), 30.0)
            await response.aclose()
            await asyncio.sleep(wait + random.random() * 0.25)
            delay *= 2
            continue
        return response
    if last_error:
        raise last_error
    raise httpx.TransportError(f"no response for {url}")


def _absolute(base: str, location: str) -> str:
    return urljoin(base, location.strip())


async def resolve_url(client: httpx.AsyncClient, url: str) -> Resolved:
    """Follow redirects ourselves so a 404 on the short link stays a 404.

    maps.app.goo.gl returns 302 even after the photo or place is gone.
    404 or a redirect with no Location means the link itself is dead.
    """

    current = url
    if not is_maps_host(current):
        return Resolved(final_url=current, status=None, body="", error="not a Maps host")

    for _hop in range(8):
        try:
            response = await request(client, "GET", current)
        except (httpx.TimeoutException, httpx.TransportError) as exc:
            return Resolved(
                final_url=current,
                status=None,
                body="",
                error=f"request failed: {exc.__class__.__name__}",
            )
        status = response.status_code
        if status in _DEAD:
            await response.aclose()
            return Resolved(
                final_url=current,
                status=status,
                body="",
                dead=True,
                dead_reason=f"HTTP {status} with no Maps listing (the link itself is dead)",
            )
        if status in {301, 302, 303, 307, 308}:
            location = response.headers.get("location") or ""
            await response.aclose()
            if not location.strip():
                return Resolved(
                    final_url=current,
                    status=status,
                    body="",
                    dead=True,
                    dead_reason=f"HTTP {status} with no redirect target",
                )
            nxt = _absolute(current, location)
            if not is_maps_host(nxt):
                return Resolved(
                    final_url=nxt,
                    status=status,
                    body="",
                    error=f"redirect left Google Maps ({urlparse(nxt).hostname})",
                )
            current = nxt
            continue
        body = response.text
        await response.aclose()
        if status == 429:
            return Resolved(
                final_url=current,
                status=status,
                body="",
                blocked_reason="Google returned HTTP 429 after retries",
            )
        if status >= 400:
            return Resolved(
                final_url=current,
                status=status,
                body="",
                error=f"HTTP {status} while resolving the link",
            )
        if _BLOCK.search(current) or _BLOCK.search(body[:4000]):
            return Resolved(
                final_url=current,
                status=status,
                body="",
                blocked_reason="Google showed a bot-check page; retry later or pass --proxy",
            )
        return Resolved(final_url=current, status=status, body=body)

    return Resolved(final_url=current, status=None, body="", error="too many redirects")


def extract_preview_url(html: str, expected_id: str | None = None) -> str | None:
    """Pull the longest ``/maps/preview/place?...`` URL out of a place page."""

    if not html:
        return None
    candidates: list[str] = []
    for match in _PREVIEW.finditer(html):
        raw = unescape(match.group(1))
        raw = (
            raw.replace("\\u003d", "=")
            .replace("\\u0026", "&")
            .replace("\\u003f", "?")
            .replace("\\u003a", ":")
        )
        if "pb=" not in raw:
            continue
        candidates.append(raw)
    if not candidates:
        return None

    def absolute(path: str) -> str:
        if path.startswith("http"):
            return path
        return "https://www.google.com" + path

    if expected_id:
        encoded = quote(expected_id, safe="")
        for candidate in candidates:
            if expected_id in candidate or encoded in candidate:
                return absolute(candidate)
    return absolute(max(candidates, key=len))


def preview_is_specific(preview_url: str, expected_id: str | None) -> bool:
    if not preview_url:
        return False
    if expected_id and (expected_id in preview_url or quote(expected_id, safe="") in preview_url):
        return True
    return "pb=" in preview_url and len(preview_url) > 400


def build_place_url(parsed) -> str | None:
    """A place-page URL we can preview, built from fields on a photo link."""

    from gmaps_status.models import ParsedUrl

    parsed = parsed if isinstance(parsed, ParsedUrl) else parsed
    name = quote(parsed.place_name, safe="") if parsed.place_name else ""
    at = ""
    if parsed.lat is not None and parsed.lng is not None:
        at = f"/@{parsed.lat},{parsed.lng},17z"
    place_id = parsed.place_id or ""
    if place_id.startswith("0x"):
        label = name or "place"
        return (
            f"https://www.google.com/maps/place/{label}{at}/data=!4m2!3m1!1s{place_id}?hl=en"
        )
    if place_id.startswith("ChIJ"):
        query = quote(parsed.place_name or place_id, safe="")
        return (
            "https://www.google.com/maps/search/?api=1&query="
            f"{query}&query_place_id={place_id}&hl=en"
        )
    if name:
        return f"https://www.google.com/maps/place/{name}{at}?hl=en"
    return None


def _with_hl(url: str) -> str:
    if "hl=" in url:
        return url
    join = "&" if "?" in url else "?"
    return f"{url}{join}hl=en"


async def fetch_preview(
    client: httpx.AsyncClient,
    *,
    parsed,
    final_url: str,
    page_html: str,
    kind: str,
) -> PlacePreview:
    """Fetch ``/maps/preview/place`` for this listing.

    Place links reuse the HTML we already downloaded. Photo and video links
    get a separate place-page request so the photo viewer shell is not
    mistaken for the place record.
    """

    html = page_html
    if kind in {"photo", "video"} or "preview/place" not in (html or ""):
        built = build_place_url(parsed)
        if not built and kind == "place":
            built = _with_hl(final_url) if final_url else None
        if not built:
            return PlacePreview(error="no place id, name, or coordinates to preview")
        try:
            response = await request(client, "GET", built, follow_redirects=True)
        except (httpx.TimeoutException, httpx.TransportError) as exc:
            return PlacePreview(error=f"place page failed: {exc.__class__.__name__}")
        if response.status_code >= 400:
            status = response.status_code
            await response.aclose()
            return PlacePreview(error=f"place page returned HTTP {status}")
        html = response.text
        await response.aclose()

    preview_url = extract_preview_url(html, parsed.place_id or None)
    if not preview_url:
        return PlacePreview(error="place page had no /maps/preview/place URL")
    trustworthy = preview_is_specific(preview_url, parsed.place_id or None)
    try:
        response = await request(
            client,
            "GET",
            preview_url,
            follow_redirects=True,
        )
    except (httpx.TimeoutException, httpx.TransportError) as exc:
        return PlacePreview(error=f"preview failed: {exc.__class__.__name__}", trustworthy=trustworthy)
    body = response.text
    size = len(response.content)
    status = response.status_code
    await response.aclose()
    if status >= 400:
        return PlacePreview(
            error=f"preview returned HTTP {status}",
            trustworthy=trustworthy,
        )
    if _BLOCK.search(body[:2000]):
        return PlacePreview(error="preview was a bot-check page", trustworthy=False)
    return PlacePreview(body=body, size=size, trustworthy=trustworthy)


async def probe_image(client: httpx.AsyncClient, image_url: str) -> int | None:
    """Status code of the lh3/lh5 file. The body is discarded.

    200 means the file is still hosted, not that the Maps listing shows it.
    401/403/404/410 means those bytes are gone.
    """

    if not image_url or "googleusercontent.com" not in image_url:
        return None
    headers = {
        "Referer": "https://www.google.com/maps",
        "Accept": "image/avif,image/webp,image/*,*/*;q=0.8",
    }
    delay = 0.6
    for attempt in range(4):
        try:
            async with client.stream(
                "GET", image_url, follow_redirects=True, headers=headers
            ) as response:
                status = response.status_code
                if status in _RETRY and attempt < 3:
                    await response.aclose()
                    await asyncio.sleep(delay + random.random() * 0.2)
                    delay *= 2
                    continue
                return status
        except (httpx.TimeoutException, httpx.TransportError):
            if attempt == 3:
                return None
            await asyncio.sleep(delay)
            delay *= 2
    return None
