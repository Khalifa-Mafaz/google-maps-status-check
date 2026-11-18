"""Shared result records and the output schema."""

from __future__ import annotations

from dataclasses import dataclass, field

# Status strings are part of the public schema. Keep them stable.
ACTIVE = "Active"
INACTIVE_LINK_DEAD = "Inactive - link dead"
INACTIVE_PHOTO_REMOVED = "Inactive - photo removed"
INACTIVE_PLACE_REMOVED = "Inactive - place removed"
UNKNOWN = "Unknown"

STATUSES = (
    ACTIVE,
    INACTIVE_LINK_DEAD,
    INACTIVE_PHOTO_REMOVED,
    INACTIVE_PLACE_REMOVED,
    UNKNOWN,
)

COLUMNS = (
    "input_url",
    "status",
    "reason",
    "type",
    "place_name",
    "lat",
    "lng",
    "place_id",
    "photo_id",
    "image_url",
    "final_url",
    "checked_at",
)

DIFF_COLUMNS = ("previous_status", "change")

USER_AGENT = (
    "Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 "
    "(KHTML, like Gecko) Chrome/131.0.0.0 Safari/537.36"
)

# Dismisses the EU consent interstitial so Maps returns place data and
# English viewer text. Values observed working against google.com/maps
# in November 2026; they are consent cookies, not session credentials.
CONSENT_COOKIE = "YES+cb.20210328-17-p0.en+FX+410"
SOCS_COOKIE = (
    "CAISNQgDEitib3FfaWRlbnRpdHlmcm9udGVuZHVpc2VydmVyXzIwMjMwODI5LjA3X3Ax"
    "GgJlbiACGgYIgJ3-pQY"
)

# A not-found preview was ~14.6 KB in the original manual run and ~1.4 KB
# in November 2026. Live places were 28–40 KB then and 44–132 KB later.
# Anything under this size with no place id is treated as removed.
PLACE_REMOVED_MAX_BYTES = 20_000

# Image responses that mean the bytes are gone. HTTP 200 is not proof the
# listing is live: Maps keeps serving many deleted photo files.
IMAGE_GONE_STATUSES = frozenset({401, 403, 404, 410})


@dataclass
class ParsedUrl:
    """Fields pulled out of a Maps URL. Empty string / None means not present."""

    kind: str = "other"  # photo, video, place, other
    place_name: str = ""
    lat: float | None = None
    lng: float | None = None
    place_id: str = ""
    photo_id: str = ""
    image_url: str = ""
    is_maps: bool = False


@dataclass
class Evidence:
    """Everything the classifier is allowed to see. No I/O."""

    input_url: str
    parsed: ParsedUrl = field(default_factory=ParsedUrl)
    final_url: str = ""
    link_dead: bool = False
    dead_reason: str = ""
    blocked_reason: str = ""
    image_status: int | None = None
    preview_body: str = ""
    preview_size: int | None = None
    preview_error: str = ""
    preview_trustworthy: bool = False
    render_text: str = ""
    render_title: str = ""
    render_final_url: str = ""
    render_image_srcs: list[str] = field(default_factory=list)
    render_error: str = ""
    no_render: bool = False


@dataclass
class CheckResult:
    input_url: str
    status: str
    reason: str
    type: str = "other"
    place_name: str = ""
    lat: str = ""
    lng: str = ""
    place_id: str = ""
    photo_id: str = ""
    image_url: str = ""
    final_url: str = ""
    checked_at: str = ""
    previous_status: str = ""
    change: str = ""

    def as_dict(self, *, with_diff: bool = False) -> dict[str, str]:
        row = {
            "input_url": self.input_url,
            "status": self.status,
            "reason": self.reason,
            "type": self.type,
            "place_name": self.place_name,
            "lat": self.lat,
            "lng": self.lng,
            "place_id": self.place_id,
            "photo_id": self.photo_id,
            "image_url": self.image_url,
            "final_url": self.final_url,
            "checked_at": self.checked_at,
        }
        if with_diff:
            row["previous_status"] = self.previous_status
            row["change"] = self.change
        return row
