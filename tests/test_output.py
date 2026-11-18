import csv
import json

from gmaps_status.models import ACTIVE, INACTIVE_PHOTO_REMOVED, CheckResult
from gmaps_status.output import agreement, apply_diff, load_previous, write_csv, write_json


def _result(url: str, status: str) -> CheckResult:
    return CheckResult(input_url=url, status=status, reason="because", type="photo")


def test_diff_marks_changes_and_agreement(tmp_path):
    previous = tmp_path / "old.csv"
    previous.write_text(
        "input_url,status\n"
        "https://maps.app.goo.gl/a,Active\n"
        "https://maps.app.goo.gl/b,Active\n"
        "https://maps.app.goo.gl/gone,Inactive - photo removed\n",
        encoding="utf-8",
    )
    loaded = load_previous(str(previous))
    results = [
        _result("https://maps.app.goo.gl/a", ACTIVE),
        _result("https://maps.app.goo.gl/b", INACTIVE_PHOTO_REMOVED),
        _result("https://maps.app.goo.gl/new", ACTIVE),
    ]
    apply_diff(results, loaded)
    assert [item.change for item in results] == ["unchanged", "changed", "new"]
    assert results[1].previous_status == ACTIVE
    assert agreement(results) == (1, 2)

    out = tmp_path / "now.csv"
    write_csv(str(out), results, with_diff=True)
    rows = list(csv.DictReader(out.open(encoding="utf-8")))
    assert rows[1]["change"] == "changed"
    assert rows[1]["status"] == INACTIVE_PHOTO_REMOVED
    assert "checked_at" in rows[0]


def test_csv_neutralizes_formula_injection(tmp_path):
    path = tmp_path / "out.csv"
    result = CheckResult(
        input_url="https://maps.app.goo.gl/a",
        status=ACTIVE,
        reason="ok",
        type="place",
        place_name="=HYPERLINK(\"http://evil\")",
    )
    write_csv(str(path), [result], with_diff=False)
    text = path.read_text(encoding="utf-8")
    assert "'=HYPERLINK" in text


def test_json_uses_null_for_empty_optional_fields(tmp_path):
    path = tmp_path / "out.json"
    write_json(
        str(path),
        [_result("https://maps.app.goo.gl/a", ACTIVE)],
        with_diff=False,
    )
    payload = json.loads(path.read_text(encoding="utf-8"))
    assert payload[0]["input_url"] == "https://maps.app.goo.gl/a"
    assert payload[0]["lat"] is None
    assert payload[0]["status"] == ACTIVE
