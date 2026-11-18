"""Parse Google Maps place and contributed-media URLs.

Maps encodes a protobuf-like blob in the ``data`` query/path parameter.
Tokens are ``!`` separated: ``<field><type><value>``, for example
``!3d51.72!4d5.43`` or ``!1s0xabc:0xdef``.

Observed (and checked against live links):

* ``/maps/place/<name>/`` is the place name. URL-decode it and strip bidi
  overrides (U+202D shows up on Arabic names). A ``ChIJ…`` or ``0x…:0x…``
  segment in that position is an id, not a name.
* ``!3d<lat>!4d<lng>`` is the place pin. The ``@lat,lng`` camera in the path
  can be somewhere else entirely (street-view camera vs. the shop).
* ``!1s0x…:0x…`` is the hex feature id. ``ChIJ…`` in the path is the
  public place id used by contribution URLs.
* ``!1e2`` marks a photo and ``!1e5`` marks a video. The photo id is the
  next ``!1s`` value that is not a place id (``AF1Qip…``, ``CIHM…``, …).
* ``!6s`` is the lh3/lh5 image URL, often percent-encoded.
"""

from __future__ import annotations

import re
from urllib.parse import parse_qsl, unquote, unquote_plus, urlparse

from gmaps_status.models import ParsedUrl

_BIDI = dict.fromkeys(map(ord, "\u202a\u202b\u202c\u202d\u202e\u200e\u200f\u2066\u2067\u2068\u2069\ufeff"), None)

_TOKEN = re.compile(r"!(\d+)([a-z])([^!]*)")
_HEX_ID = re.compile(r"^0x[0-9a-fA-F]+:0x[0-9a-fA-F]+$")
_CHIJ = re.compile(r"^ChIJ[A-Za-z0-9_-]{8,}$")
_AT = re.compile(r"@(-?\d+(?:\.\d+)?),(-?\d+(?:\.\d+)?)")
_PLACE_PATH = re.compile(r"/maps/place/([^/@?#]+)")
_HOSTS = (
    "google.com",
    "googleusercontent.com",
    "goo.gl",
    "maps.app.goo.gl",
)


def is_maps_host(url: str) -> bool:
    host = (urlparse(url).hostname or "").lower().rstrip(".")
    if not host:
        return False
    return any(host == suffix or host.endswith("." + suffix) for suffix in _HOSTS)


def strip_bidi(value: str) -> str:
    return value.translate(_BIDI).strip()


def _decode_image(value: str) -> str:
    current = value.strip()
    for _ in range(2):
        decoded = unquote(current)
        if decoded == current:
            break
        current = decoded
    current = current.replace("\\u003d", "=").replace("\\u0026", "&").replace("\\u003f", "?")
    if "googleusercontent.com" not in current and not current.startswith("http"):
        return ""
    return current.split()[0]


def _coord(value: str) -> float | None:
    try:
        number = float(value)
    except ValueError:
        return None
    return number


def _valid_lat_lng(lat: float | None, lng: float | None) -> tuple[float | None, float | None]:
    if lat is None or lng is None:
        return None, None
    if not (-90.0 <= lat <= 90.0 and -180.0 <= lng <= 180.0):
        return None, None
    return lat, lng


def _token_source(url: str) -> str:
    """Path plus a ``data`` query param. Other query params (``hl``, ``entry``) are not tokens."""

    parts = urlparse(url)
    source = parts.path
    for key, value in parse_qsl(parts.query, keep_blank_values=True):
        if key == "data":
            source += value
    return source


def _cut(value: str) -> str:
    """Drop a query string that the last ``!`` token would otherwise swallow."""

    return value.split("?", 1)[0].split("#", 1)[0]


def parse_maps_url(url: str) -> ParsedUrl:
    """Parse a Maps URL. Non-Maps URLs come back as kind ``other``."""

    parsed = ParsedUrl()
    if not url or not is_maps_host(url):
        return parsed
    parsed.is_maps = True

    path_and_query = _token_source(url)
    for match in _PLACE_PATH.finditer(path_and_query):
        raw = strip_bidi(unquote_plus(match.group(1)))
        if not raw or raw.lower() in {"data", "place", "search"}:
            continue
        if _CHIJ.match(raw) and not parsed.place_id:
            parsed.place_id = raw
        elif _HEX_ID.match(raw) and not parsed.place_id:
            parsed.place_id = raw
        elif not _CHIJ.match(raw) and not _HEX_ID.match(raw):
            parsed.place_name = raw

    chij_in_path = re.search(r"/place/(ChIJ[A-Za-z0-9_-]{8,})", path_and_query)
    if chij_in_path and (not parsed.place_id or parsed.place_id.startswith("ChIJ")):
        parsed.place_id = chij_in_path.group(1)

    media: str | None = None
    lat_3d: float | None = None
    lng_4d: float | None = None
    early_media_ids: list[str] = []
    for field, kind, value in _TOKEN.findall(path_and_query):
        if kind == "e" and field == "1":
            flag = _cut(value)
            if flag == "5":
                media = "video"
            elif flag == "2":
                media = media or "photo"
            continue
        if kind == "d" and field == "3" and lat_3d is None:
            lat_3d = _coord(_cut(value))
            continue
        if kind == "d" and field == "4" and lng_4d is None:
            lng_4d = _coord(_cut(value))
            continue
        if kind == "s" and field == "1":
            token = unquote(_cut(value))
            if _HEX_ID.match(token):
                parsed.place_id = token
            elif _CHIJ.match(token) and not str(parsed.place_id).startswith("0x"):
                parsed.place_id = token
            elif token:
                if media in {"photo", "video"} and not parsed.photo_id:
                    parsed.photo_id = token
                else:
                    early_media_ids.append(token)
            continue
        if kind == "s" and field == "6" and not parsed.image_url:
            parsed.image_url = _decode_image(_cut(value))

    if media and not parsed.photo_id and early_media_ids:
        parsed.photo_id = early_media_ids[0]

    lat, lng = _valid_lat_lng(lat_3d, lng_4d)
    if lat is None:
        at = _AT.search(path_and_query)
        if at:
            lat, lng = _valid_lat_lng(float(at.group(1)), float(at.group(2)))
    parsed.lat, parsed.lng = lat, lng

    if media == "video":
        parsed.kind = "video"
    elif media == "photo" or parsed.photo_id:
        parsed.kind = "photo"
    elif parsed.place_id or parsed.place_name:
        parsed.kind = "place"
    else:
        parsed.kind = "other"
    return parsed


def format_coord(value: float | None) -> str:
    if value is None:
        return ""
    text = f"{value:.7f}".rstrip("0").rstrip(".")
    return text or "0"
