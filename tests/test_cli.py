import sys

import pytest

from gmaps_status.cli import main


def test_help_exits_zero(capsys):
    with pytest.raises(SystemExit) as caught:
        main(["--help"])
    assert caught.value.code == 0
    captured = capsys.readouterr()
    assert "Read-only" in captured.out
    assert "--no-render" in captured.out
    assert "--previous" in captured.out


def test_version(capsys):
    with pytest.raises(SystemExit) as caught:
        main(["--version"])
    assert caught.value.code == 0
    assert "gmaps-status" in capsys.readouterr().out


def test_missing_urls_is_an_error(monkeypatch):
    monkeypatch.setattr(sys.stdin, "isatty", lambda: True)
    with pytest.raises(SystemExit) as caught:
        main([])
    assert caught.value.code == 2
