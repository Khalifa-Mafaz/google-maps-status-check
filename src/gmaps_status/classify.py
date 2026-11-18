"""Turn fetched evidence into a status. This module does no I/O.

Render text is the authority for contributed photos and videos. An lh3
response of 200 only means Google still has the file; deleted photos often
stay on the CDN. 403/404 means those bytes are gone, which is enough in
HTTP-only mode and is the substitution signal when the viewer is showing a
different photo.
"""

from __future__ import annotations

import re

from gmaps_status.models import (
    ACTIVE,
    IMAGE_GONE_STATUSES,
    INACTIVE_LINK_DEAD,
    INACTIVE_PHOTO_REMOVED,
    INACTIVE_PLACE_REMOVED,
    PLACE_REMOVED_MAX_BYTES,
    UNKNOWN,
    CheckResult,
    Evidence,
    ParsedUrl,
)
from gmaps_status.parse import format_coord, parse_maps_url, strip_bidi

_DASH = r"[-–—−]"
_MONTH = r"(?:Jan|Feb|Mar|Apr|May|Jun|Jul|Aug|Sep|Oct|Nov|Dec)[a-z]*"
_PHOTO_CAPTION = re.compile(rf"Photo\s*{_DASH}\s*{_MONTH}\s+\d{{4}}")
_VIDEO_CAPTION = re.compile(rf"Video\s*{_DASH}\s*")
_IMAGE_CAPTURE = re.compile(r"Image capture\s*:")
_NO_PHOTO = re.compile(r"No user photo available here\.?")
_STUCK = re.compile(rf"(?:^|[\s|]){_DASH}:{_DASH}{_DASH}(?:$|[\s|])", re.M)
_HEX_ID = re.compile(r"0x[0-9a-fA-F]+:0x[0-9a-fA-F]+")
_CANT_FIND = re.compile(
    r"can(?:not|['’]t) find|No results found|couldn['’]t find",
    re.IGNORECASE,
)


def place_ids_in(body: str) -> list[str]:
    seen: list[str] = []
    for match in _HEX_ID.findall(body or ""):
        if match not in seen:
            seen.append(match)
    return seen


def assess_place(evidence: Evidence) -> str:
    """Return ``exists``, ``removed``, ``mismatch``, or ``unknown``."""

    if evidence.preview_error and not evidence.preview_body:
        return "unknown"
    if evidence.preview_size is None and not evidence.preview_body:
        return "unknown"

    body = evidence.preview_body or ""
    size = evidence.preview_size if evidence.preview_size is not None else len(body)
    ids = place_ids_in(body)
    expected = (evidence.parsed.place_id or "").strip()
    expected_hex = expected.lower() if expected.startswith(("0x", "0X")) else ""

    if expected_hex and any(item.lower() == expected_hex for item in ids):
        return "exists"
    if expected.startswith("ChIJ") and expected in body and size >= PLACE_REMOVED_MAX_BYTES:
        return "exists"

    if not ids and size < PLACE_REMOVED_MAX_BYTES:
        if evidence.preview_trustworthy:
            return "removed"
        return "unknown"

    if ids and size >= PLACE_REMOVED_MAX_BYTES:
        if expected_hex and expected_hex not in {item.lower() for item in ids}:
            return "mismatch"
        return "exists"
    return "unknown"


def _name_from_title(title: str) -> str:
    title = strip_bidi(title or "").strip()
    suffix = " - Google Maps"
    if title.endswith(suffix):
        name = title[: -len(suffix)].strip()
        if name and name.lower() != "google maps":
            return name
    return ""


def _caption(text: str) -> str:
    for pattern in (_PHOTO_CAPTION, _IMAGE_CAPTURE, _VIDEO_CAPTION):
        match = pattern.search(text)
        if not match:
            continue
        line = text[match.start() : match.start() + 48].splitlines()[0].strip()
        return line
    return ""


def _shown_photo(evidence: Evidence) -> ParsedUrl:
    if not evidence.render_final_url:
        return ParsedUrl()
    return parse_maps_url(evidence.render_final_url)


def _substitution(evidence: Evidence, shown: ParsedUrl) -> str:
    """Return a reason if the viewer is showing a different photo, else ''."""

    requested = evidence.parsed.photo_id
    if not requested:
        return ""
    if shown.photo_id and shown.photo_id != requested:
        return (
            f"viewer URL photo id {shown.photo_id} does not match the link's {requested}; "
            "Maps substituted another photo (usually the place cover)"
        )
    srcs = " ".join(evidence.render_image_srcs)
    id_still_visible = requested in (evidence.render_final_url or "") or requested in srcs
    if evidence.image_status in IMAGE_GONE_STATUSES and not id_still_visible:
        return (
            f"linked image returned HTTP {evidence.image_status} and the "
            "viewer is not displaying that photo id"
        )
    return ""


def _base_result(evidence: Evidence, status: str, reason: str) -> CheckResult:
    parsed = evidence.parsed
    title_name = _name_from_title(evidence.render_title)
    final = evidence.render_final_url or evidence.final_url
    return CheckResult(
        input_url=evidence.input_url,
        status=status,
        reason=reason,
        type=parsed.kind or "other",
        place_name=title_name or parsed.place_name,
        lat=format_coord(parsed.lat),
        lng=format_coord(parsed.lng),
        place_id=parsed.place_id,
        photo_id=parsed.photo_id,
        image_url=parsed.image_url,
        final_url=final,
    )


def _photo_removed(evidence: Evidence, reason: str, place: str) -> CheckResult:
    if place == "removed":
        size = evidence.preview_size
        return _base_result(
            evidence,
            INACTIVE_PLACE_REMOVED,
            f"place preview is {size} bytes with no place id; the contribution is gone too"
            if "preview" not in reason
            else reason,
        )
    return _base_result(evidence, INACTIVE_PHOTO_REMOVED, reason)


def _http_only_media(evidence: Evidence, place: str) -> CheckResult:
    """HTTP-only decisions. Anything the CDN still serves stays Unknown."""

    if place == "removed":
        return _base_result(
            evidence,
            INACTIVE_PLACE_REMOVED,
            f"place preview is {evidence.preview_size} bytes and does not contain a place id",
        )
    if evidence.image_status in IMAGE_GONE_STATUSES:
        return _base_result(
            evidence,
            INACTIVE_PHOTO_REMOVED,
            f"image host returned HTTP {evidence.image_status}; "
            "listing was not rendered (--no-render)",
        )
    if evidence.render_error:
        return _base_result(
            evidence,
            UNKNOWN,
            f"render failed ({evidence.render_error}); HTTP is not enough to call this active",
        )
    if evidence.image_status == 200:
        return _base_result(
            evidence,
            UNKNOWN,
            "image file is still served (HTTP 200), but Maps keeps deleted photo files; "
            "render the listing to confirm it (--no-render)",
        )
    if place == "mismatch":
        return _base_result(
            evidence,
            UNKNOWN,
            "place preview resolved a different place id than the link (--no-render)",
        )
    if place == "exists":
        return _base_result(
            evidence,
            UNKNOWN,
            "place is still listed but the photo or video was not rendered (--no-render)",
        )
    detail = evidence.preview_error or "no image URL and no trustworthy place preview"
    return _base_result(evidence, UNKNOWN, f"not enough HTTP evidence ({detail})")


def _classify_media(evidence: Evidence, place: str) -> CheckResult:
    if evidence.no_render or (evidence.render_error and not evidence.render_text):
        return _http_only_media(evidence, place)

    text = evidence.render_text or ""
    if _NO_PHOTO.search(text):
        return _photo_removed(
            evidence,
            "page text says 'No user photo available here.'",
            place,
        )

    stuck = bool(_STUCK.search(text))
    video_caption = bool(_VIDEO_CAPTION.search(text))
    if evidence.parsed.kind == "video" and stuck and not video_caption:
        return _photo_removed(evidence, "video player is stuck at -:--", place)

    caption = _caption(text)
    if caption:
        shown = _shown_photo(evidence)
        swapped = _substitution(evidence, shown)
        if swapped:
            return _photo_removed(evidence, swapped, place)
        extra = ""
        if evidence.image_status in IMAGE_GONE_STATUSES:
            extra = f"; linked image URL returned HTTP {evidence.image_status}"
        elif evidence.image_status:
            extra = f"; image HTTP {evidence.image_status}"
        return _base_result(evidence, ACTIVE, f"viewer shows '{caption}'{extra}")

    if place == "removed":
        return _base_result(
            evidence,
            INACTIVE_PLACE_REMOVED,
            f"place preview is {evidence.preview_size} bytes and does not contain a place id",
        )
    if evidence.image_status in IMAGE_GONE_STATUSES:
        return _photo_removed(
            evidence,
            f"image host returned HTTP {evidence.image_status} and the viewer "
            "did not show a photo or video caption",
            place,
        )
    if evidence.render_error:
        return _base_result(evidence, UNKNOWN, f"render failed ({evidence.render_error})")
    return _base_result(
        evidence,
        UNKNOWN,
        "viewer text did not match a photo, video, or removal message",
    )


def _classify_place(evidence: Evidence, place: str) -> CheckResult:
    if place == "exists":
        return _base_result(
            evidence,
            ACTIVE,
            f"place preview contains the place id ({evidence.preview_size} bytes)",
        )
    if place == "removed":
        return _base_result(
            evidence,
            INACTIVE_PLACE_REMOVED,
            f"place preview is {evidence.preview_size} bytes and does not contain a place id",
        )
    if place == "mismatch":
        return _base_result(
            evidence,
            UNKNOWN,
            "place preview resolved a different place id than the link",
        )

    text = evidence.render_text or ""
    if text and _CANT_FIND.search(text):
        return _base_result(
            evidence,
            INACTIVE_PLACE_REMOVED,
            "rendered place panel says Maps cannot find this place",
        )
    name = evidence.parsed.place_name
    if text and name and name.lower() in text.lower() and "Directions" in text:
        return _base_result(
            evidence,
            ACTIVE,
            "rendered place panel shows the place name and directions",
        )
    detail = evidence.preview_error or evidence.render_error or "place preview was inconclusive"
    return _base_result(evidence, UNKNOWN, detail)


def classify(evidence: Evidence) -> CheckResult:
    if evidence.blocked_reason:
        return _base_result(evidence, UNKNOWN, evidence.blocked_reason)
    if evidence.link_dead:
        reason = evidence.dead_reason or "link returned HTTP 404"
        return _base_result(evidence, INACTIVE_LINK_DEAD, reason)
    if not evidence.parsed.is_maps and not is_followup_maps(evidence):
        return _base_result(
            evidence,
            UNKNOWN,
            "not a Google Maps URL (only maps and goo.gl short links are fetched)",
        )

    place = assess_place(evidence)
    if evidence.parsed.kind in {"photo", "video"}:
        return _classify_media(evidence, place)
    return _classify_place(evidence, place)


def is_followup_maps(evidence: Evidence) -> bool:
    return bool(evidence.parsed.is_maps)
