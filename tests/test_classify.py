from gmaps_status.classify import assess_place, classify
from gmaps_status.models import (
    ACTIVE,
    INACTIVE_LINK_DEAD,
    INACTIVE_PHOTO_REMOVED,
    INACTIVE_PLACE_REMOVED,
    PLACE_REMOVED_MAX_BYTES,
    UNKNOWN,
    Evidence,
    ParsedUrl,
)

HEX = "0x47c6fad51cf2d4c3:0x223996dcb3d178bf"
PHOTO_ID = "CIHM0ogKEICAgMDw7sLgxQE"


def place_parsed(**overrides) -> ParsedUrl:
    base = dict(
        kind="place",
        place_name="AH Kerkstraat",
        lat=51.7287885,
        lng=5.433234,
        place_id=HEX,
        is_maps=True,
    )
    base.update(overrides)
    return ParsedUrl(**base)


def photo_parsed(**overrides) -> ParsedUrl:
    base = dict(
        kind="photo",
        place_name="Eiffel Tower",
        lat=48.8583701,
        lng=2.2944813,
        photo_id=PHOTO_ID,
        image_url="https://lh3.googleusercontent.com/gps-cs-s/example",
        is_maps=True,
    )
    base.update(overrides)
    return ParsedUrl(**base)


def evidence(parsed: ParsedUrl, **overrides) -> Evidence:
    ev = Evidence(input_url="https://maps.app.goo.gl/example", parsed=parsed)
    for key, value in overrides.items():
        setattr(ev, key, value)
    return ev


def live_preview(size: int = 44598) -> str:
    padding = " " * max(0, size - len(HEX) - 10)
    return f')]\'\n["{HEX}",{padding}]'


def test_small_preview_without_an_id_is_removed():
    body = ")]}'\n[null,null]" + (" " * 1400)
    ev = evidence(
        place_parsed(),
        preview_body=body,
        preview_size=len(body),
        preview_trustworthy=True,
    )
    assert assess_place(ev) == "removed"
    result = classify(ev)
    assert result.status == INACTIVE_PLACE_REMOVED
    assert result.place_id == HEX
    assert result.lat == "51.7287885"


def test_historical_14kb_empty_preview_is_removed():
    body = "x" * 14_600
    ev = evidence(
        place_parsed(),
        preview_body=body,
        preview_size=14_600,
        preview_trustworthy=True,
    )
    assert len(body) < PLACE_REMOVED_MAX_BYTES
    assert assess_place(ev) == "removed"


def test_untrustworthy_small_preview_stays_unknown():
    body = "short"
    ev = evidence(
        place_parsed(),
        preview_body=body,
        preview_size=len(body),
        preview_trustworthy=False,
    )
    assert assess_place(ev) == "unknown"
    assert classify(ev).status == UNKNOWN


def test_preview_containing_the_place_id_is_active():
    body = live_preview()
    ev = evidence(
        place_parsed(),
        preview_body=body,
        preview_size=len(body),
        preview_trustworthy=True,
        final_url="https://www.google.com/maps/place/AH+Kerkstraat/",
    )
    assert assess_place(ev) == "exists"
    result = classify(ev)
    assert result.status == ACTIVE
    assert result.type == "place"
    assert HEX in result.reason or "place id" in result.reason


def test_different_place_id_is_a_mismatch():
    other = "0x111:0x222"
    body = other + (" " * 40_000)
    ev = evidence(
        place_parsed(),
        preview_body=body,
        preview_size=len(body),
        preview_trustworthy=True,
    )
    assert assess_place(ev) == "mismatch"
    assert classify(ev).status == UNKNOWN


def test_link_dead_short_link():
    ev = evidence(
        ParsedUrl(is_maps=True, kind="other"),
        link_dead=True,
        dead_reason="HTTP 404 with no Maps listing (the link itself is dead)",
    )
    result = classify(ev)
    assert result.status == INACTIVE_LINK_DEAD
    assert "404" in result.reason


def test_http_200_image_is_not_active_without_render():
    ev = evidence(photo_parsed(), image_status=200, no_render=True, preview_trustworthy=True)
    ev.preview_body = live_preview()
    ev.preview_size = len(ev.preview_body)
    result = classify(ev)
    assert result.status == UNKNOWN
    assert "200" in result.reason


def test_image_403_without_render_is_photo_removed():
    ev = evidence(photo_parsed(), image_status=403, no_render=True)
    ev.preview_body = live_preview()
    ev.preview_size = len(ev.preview_body)
    ev.preview_trustworthy = True
    result = classify(ev)
    assert result.status == INACTIVE_PHOTO_REMOVED
    assert "403" in result.reason


def test_image_404_and_place_removed_prefers_place_removed():
    body = "nope"
    ev = evidence(
        photo_parsed(),
        image_status=404,
        no_render=True,
        preview_body=body,
        preview_size=len(body),
        preview_trustworthy=True,
    )
    result = classify(ev)
    assert result.status == INACTIVE_PLACE_REMOVED


def test_no_user_photo_text_is_photo_removed_even_if_image_is_200():
    ev = evidence(
        photo_parsed(),
        image_status=200,
        render_text="Climate HVAC Pros\nNo user photo available here.\nPLACE DETAILS",
        render_final_url=(
            "https://www.google.com/maps/place/data=!1e2!1s" + PHOTO_ID
        ),
    )
    result = classify(ev)
    assert result.status == INACTIVE_PHOTO_REMOVED
    assert "No user photo available here" in result.reason


def test_photo_caption_with_same_id_is_active():
    final = (
        "https://www.google.com/maps/place/Eiffel+Tower/@48.85,2.29,3a,75y/"
        f"data=!1e2!1s{PHOTO_ID}!6shttps://lh3.googleusercontent.com/x"
    )
    ev = evidence(
        photo_parsed(),
        image_status=200,
        render_text="Eiffel Tower\nSalamat Dosqali\nPhoto - Mar 2025\nImage capture: Mar 2025",
        render_title="Eiffel Tower - Google Maps",
        render_final_url=final,
    )
    result = classify(ev)
    assert result.status == ACTIVE
    assert "Photo - Mar 2025" in result.reason
    assert result.place_name == "Eiffel Tower"
    assert result.photo_id == PHOTO_ID


def test_cover_substitution_when_photo_id_changes():
    final = (
        "https://www.google.com/maps/place/Eiffel+Tower/data=!1e2!1sCIHMdifferentCover"
    )
    ev = evidence(
        photo_parsed(),
        image_status=403,
        render_text="Someone Else\nPhoto - Jan 2019\nImage capture: Jan 2019",
        render_final_url=final,
    )
    result = classify(ev)
    assert result.status == INACTIVE_PHOTO_REMOVED
    assert "substituted" in result.reason


def test_same_photo_caption_stays_active_when_image_url_403s():
    # The viewer can load the photo through a different CDN URL than the one
    # baked into the share link. A 403 on that exact URL does not override a
    # caption for the same photo id.
    final = f"https://www.google.com/maps/place/Eiffel+Tower/data=!1e2!1s{PHOTO_ID}"
    ev = evidence(
        photo_parsed(),
        image_status=403,
        render_text="Photo - Mar 2025",
        render_final_url=final,
    )
    result = classify(ev)
    assert result.status == ACTIVE
    assert "403" in result.reason


def test_video_stuck_is_inactive():
    ev = evidence(
        photo_parsed(kind="video", photo_id="vid123"),
        render_text="Harbor Cafe\n-:--\nAdd photos & videos",
        render_final_url="https://www.google.com/maps/place/Harbor+Cafe/data=!1e5!1svid123",
    )
    result = classify(ev)
    assert result.status == INACTIVE_PHOTO_REMOVED
    assert "-:--" in result.reason


def test_video_caption_is_active():
    ev = evidence(
        photo_parsed(kind="video", photo_id="vid123"),
        image_status=200,
        render_text="Video - Apr 2024\n0:45",
        render_final_url="https://www.google.com/maps/place/Harbor/data=!1e5!1svid123",
    )
    result = classify(ev)
    assert result.status == ACTIVE
    assert result.type == "video"


def test_no_photo_on_a_removed_place_is_place_removed():
    body = "empty"
    ev = evidence(
        photo_parsed(place_id=HEX),
        render_text="No user photo available here.",
        preview_body=body,
        preview_size=len(body),
        preview_trustworthy=True,
        render_final_url=f"https://www.google.com/maps/place/data=!1e2!1s{PHOTO_ID}",
    )
    result = classify(ev)
    assert result.status == INACTIVE_PLACE_REMOVED


def test_rendered_not_found_panel():
    ev = evidence(
        place_parsed(),
        preview_error="place page had no /maps/preview/place URL",
        render_text="Google Maps can't find Not A Real Place",
    )
    result = classify(ev)
    assert result.status == INACTIVE_PLACE_REMOVED


def test_bot_check_is_unknown():
    ev = evidence(place_parsed(), blocked_reason="Google showed a bot-check page")
    assert classify(ev).status == UNKNOWN


def test_non_maps_url_is_unknown():
    ev = evidence(ParsedUrl(is_maps=False, kind="other"))
    result = classify(ev)
    assert result.status == UNKNOWN
    assert result.type == "other"
