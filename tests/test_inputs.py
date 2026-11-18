from pathlib import Path

from gmaps_status.http_checks import extract_preview_url, preview_is_specific
from gmaps_status.inputs import collect_urls, load_inputs, urls_in_text


def test_lines_skip_comments_and_blanks():
    text = "\n# comment\nhttps://maps.app.goo.gl/aaa\n\nhttps://maps.app.goo.gl/bbb extra\n"
    assert urls_in_text(text) == [
        "https://maps.app.goo.gl/aaa",
        "https://maps.app.goo.gl/bbb",
    ]


def test_csv_uses_input_url_column():
    text = "input_url,status,place_name\nhttps://maps.app.goo.gl/aaa,Active,Cafe\n"
    assert urls_in_text(text, filename="status.csv") == ["https://maps.app.goo.gl/aaa"]


def test_duplicates_are_counted_once():
    batch = collect_urls(
        [
            "https://maps.app.goo.gl/aaa",
            "https://maps.app.goo.gl/aaa",
            "not a url",
            "https://maps.app.goo.gl/bbb",
        ]
    )
    assert batch.urls == [
        "https://maps.app.goo.gl/aaa",
        "https://maps.app.goo.gl/bbb",
    ]
    assert batch.duplicates == 1
    assert batch.skipped == 1


def test_load_file_and_args(tmp_path):
    path = tmp_path / "urls.txt"
    path.write_text("# keep\nhttps://maps.app.goo.gl/fromfile\n", encoding="utf-8")
    batch = load_inputs(
        ["https://maps.app.goo.gl/fromarg"],
        [str(path)],
        None,
    )
    assert batch.urls == [
        "https://maps.app.goo.gl/fromarg",
        "https://maps.app.goo.gl/fromfile",
    ]


def test_smoke_fixture_is_five_http_urls():
    text = Path(__file__).parent.joinpath("fixtures", "smoke_urls.txt").read_text(encoding="utf-8")
    urls = urls_in_text(text, filename="smoke_urls.txt")
    assert len(urls) == 5
    assert urls[0].startswith("https://maps.app.goo.gl/")
    assert all(url.startswith("https://") for url in urls)


def test_extract_preview_url_unescapes_and_prefers_the_place_id():
    pid = "0x47c6fad51cf2d4c3:0x223996dcb3d178bf"
    html = (
        '<link href="/maps/preview/place?authuser=0&amp;hl=en&amp;pb=%211m2%212sshort">'
        f'<link href="/maps/preview/place?authuser=0&amp;hl=en&amp;q=Cafe&amp;pb=!1s{pid}!2sCafe!extra=1">'
    )
    found = extract_preview_url(html, pid)
    assert found is not None
    assert found.startswith("https://www.google.com/maps/preview/place?")
    assert pid in found
    assert "&hl=en" in found
    assert preview_is_specific(found, pid)


def test_short_preview_without_the_id_is_not_specific():
    assert preview_is_specific("https://www.google.com/maps/preview/place?hl=en&pb=1", None) is False
