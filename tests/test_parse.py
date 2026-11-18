from gmaps_status.parse import parse_maps_url, strip_bidi

PLACE = (
    "https://www.google.com/maps/place/AH+Kerkstraat/@38.535463,-0.130814,3a,75y,90t/"
    "data=!4m6!3m5!1s0x47c6fad51cf2d4c3:0x223996dcb3d178bf!8m2!3d51.7287885!4d5.433234"
    "!16s%2Fg%2F1tj95n77"
)

PHOTO = (
    "https://www.google.com/maps/place/Eiffel+Tower/@48.8583701,2.2944813,3a,75y,90t/"
    "data=!3m8!1e2!3m6!1sCIHM0ogKEICAgMDw7sLgxQE!2e10!3e12!"
    "6shttps:%2F%2Flh3.googleusercontent.com%2Fgps-cs-s%2FANWiy9Qexample%3Dw400!7i4000!8i3000"
)

CONTRIB = (
    "https://www.google.com/maps/contrib/115683107025634263342/place/"
    "ChIJxyCOOno5s1IRpOzhiaSh1Dg/@45.1127578,-93.3848992,3a,75y,90t/"
    "data=!3m7!1e2!3m5!1sAF1QipMhyjNpB-DSYAqWkoRCmE1iNy2etOZk11NIBuVz!2e10!"
    "6shttps:%2F%2Flh5.googleusercontent.com%2Fp%2F"
    "AF1QipMhyjNpB-DSYAqWkoRCmE1iNy2etOZk11NIBuVz%3Dw365-h547-k-no!7i4672!8i7008"
)

VIDEO = (
    "https://www.google.com/maps/place/Harbor+Cafe/@25.1972,55.2744,3a,75y/"
    "data=!3m7!1e5!3m5!1sAF1QipVideoExample123!2e10!"
    "6shttps:%2F%2Flh3.googleusercontent.com%2Fgps-cs-s%2Fvideobytes"
)


def test_place_pin_beats_camera_at_coordinates():
    parsed = parse_maps_url(PLACE)
    assert parsed.kind == "place"
    assert parsed.place_name == "AH Kerkstraat"
    assert parsed.place_id == "0x47c6fad51cf2d4c3:0x223996dcb3d178bf"
    assert parsed.lat == 51.7287885
    assert parsed.lng == 5.433234
    assert parsed.photo_id == ""
    assert parsed.image_url == ""
    assert parsed.is_maps


def test_photo_url_fields():
    parsed = parse_maps_url(PHOTO)
    assert parsed.kind == "photo"
    assert parsed.place_name == "Eiffel Tower"
    assert parsed.photo_id == "CIHM0ogKEICAgMDw7sLgxQE"
    assert parsed.image_url.startswith("https://lh3.googleusercontent.com/gps-cs-s/ANWiy9Qexample")
    assert "=w400" in parsed.image_url
    assert parsed.lat == 48.8583701
    assert parsed.lng == 2.2944813


def test_contrib_url_does_not_use_chij_as_the_name():
    parsed = parse_maps_url(CONTRIB)
    assert parsed.kind == "photo"
    assert parsed.place_name == ""
    assert parsed.place_id == "ChIJxyCOOno5s1IRpOzhiaSh1Dg"
    assert parsed.photo_id == "AF1QipMhyjNpB-DSYAqWkoRCmE1iNy2etOZk11NIBuVz"
    assert parsed.image_url.startswith("https://lh5.googleusercontent.com/p/AF1Qip")
    assert "w365-h547-k-no" in parsed.image_url
    assert parsed.lat == 45.1127578
    assert parsed.lng == -93.3848992


def test_video_marker():
    parsed = parse_maps_url(VIDEO)
    assert parsed.kind == "video"
    assert parsed.place_name == "Harbor Cafe"
    assert parsed.photo_id == "AF1QipVideoExample123"
    assert "videobytes" in parsed.image_url


def test_bidi_override_is_stripped_from_place_name():
    url = "https://www.google.com/maps/place/%E2%80%ADCafe%E2%80%AC/@25.0,55.0,17z"
    parsed = parse_maps_url(url)
    assert parsed.place_name == "Cafe"
    assert "\u202d" not in parsed.place_name
    assert strip_bidi("\u202dName\u202c") == "Name"


def test_photo_id_before_media_marker_is_kept():
    url = (
        "https://www.google.com/maps/place/Shop/@1,2,17z/data="
        "!1sAF1QipEarlyPhoto!1e2!6shttps:%2F%2Flh3.googleusercontent.com%2Fp%2FAF1QipEarlyPhoto"
    )
    parsed = parse_maps_url(url)
    assert parsed.kind == "photo"
    assert parsed.photo_id == "AF1QipEarlyPhoto"


def test_short_link_host_is_maps_but_has_no_fields():
    parsed = parse_maps_url("https://maps.app.goo.gl/LVuCpGzsCMaa32DS9")
    assert parsed.is_maps
    assert parsed.kind == "other"


def test_unrelated_host_is_not_parsed():
    parsed = parse_maps_url("https://example.com/maps/place/Cafe/@1,2,17z")
    assert parsed.is_maps is False
    assert parsed.kind == "other"
    assert parsed.place_name == ""


def test_query_string_does_not_swallow_the_last_token():
    url = (
        "https://www.google.com/maps/place/Not+A+Real+Place+zzzz/@25.2,55.27,17z/"
        "data=!4m2!3m1!1s0xdeadbeef:0xdeadbeef?hl=en"
    )
    parsed = parse_maps_url(url)
    assert parsed.place_id == "0xdeadbeef:0xdeadbeef"
    assert parsed.place_name == "Not A Real Place zzzz"
    assert parsed.lat == 25.2
    assert parsed.lng == 55.27


def test_hex_place_id_wins_over_chij_when_both_exist():
    url = (
        "https://www.google.com/maps/place/ChIJxyCOOno5s1IRpOzhiaSh1Dg/@1,2,17z/"
        "data=!1s0xabc:0xdef"
    )
    parsed = parse_maps_url(url)
    assert parsed.place_id == "0xabc:0xdef"
    assert parsed.place_name == ""
    assert parsed.kind == "place"
