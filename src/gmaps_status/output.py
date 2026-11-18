"""Console table, CSV, JSON, and the previous-run diff."""

from __future__ import annotations

import csv
import io
import json
from collections import Counter
from pathlib import Path

from gmaps_status.models import COLUMNS, DIFF_COLUMNS, CheckResult

_FORMULA = "=+-@"


def load_previous(path: str) -> dict[str, str]:
    text = Path(path).read_text(encoding="utf-8-sig")
    reader = csv.DictReader(io.StringIO(text))
    if not reader.fieldnames:
        raise SystemExit(f"previous CSV has no header: {path}")
    fields = {name.strip().lower(): name for name in reader.fieldnames if name}
    url_key = fields.get("input_url") or fields.get("url") or fields.get("link")
    status_key = fields.get("status")
    if not url_key or not status_key:
        raise SystemExit(
            f"previous CSV needs input_url (or url) and status columns: {path}"
        )
    found: dict[str, str] = {}
    for row in reader:
        url = (row.get(url_key) or "").strip()
        status = (row.get(status_key) or "").strip()
        if url and status:
            found[url] = status
    return found


def apply_diff(results: list[CheckResult], previous: dict[str, str]) -> None:
    for result in results:
        old = previous.get(result.input_url)
        if old is None:
            result.previous_status = ""
            result.change = "new"
        else:
            result.previous_status = old
            result.change = "unchanged" if old == result.status else "changed"


def agreement(results: list[CheckResult]) -> tuple[int, int]:
    """Return (unchanged, comparable) for rows that existed in the previous file."""

    comparable = [item for item in results if item.change in {"unchanged", "changed"}]
    same = sum(1 for item in comparable if item.change == "unchanged")
    return same, len(comparable)


def _csv_safe(value: str) -> str:
    if value and value[0] in _FORMULA:
        return "'" + value
    return value


def write_csv(path: str, results: list[CheckResult], *, with_diff: bool) -> None:
    columns = list(COLUMNS) + (list(DIFF_COLUMNS) if with_diff else [])
    with open(path, "w", encoding="utf-8", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=columns, extrasaction="ignore")
        writer.writeheader()
        for result in results:
            row = result.as_dict(with_diff=with_diff)
            writer.writerow({key: _csv_safe(row.get(key, "")) for key in columns})


def write_json(path: str, results: list[CheckResult], *, with_diff: bool) -> None:
    payload = []
    for result in results:
        row = result.as_dict(with_diff=with_diff)
        for key, value in list(row.items()):
            if value == "" and key not in {"input_url", "status", "reason", "type"}:
                row[key] = None
        payload.append(row)
    text = json.dumps(payload, indent=2, ensure_ascii=False) + "\n"
    Path(path).write_text(text, encoding="utf-8")


def summary_line(results: list[CheckResult]) -> str:
    counts = Counter(item.status for item in results)
    parts = [f"{counts[status]} {status}" for status in counts]
    return " · ".join(parts) if parts else "0 links"


def _plain_table(results: list[CheckResult], *, with_diff: bool) -> str:
    headers = ["status", "type", "place_name", "reason", "input_url"]
    if with_diff:
        headers = ["change", "previous_status", *headers]
    lines = ["  ".join(headers)]
    for result in results:
        row = result.as_dict(with_diff=True)
        cells = []
        for key in headers:
            value = row.get(key, "") or ""
            if key in {"reason", "input_url", "place_name"} and len(value) > 72:
                value = value[:69] + "..."
            cells.append(value.replace("\n", " "))
        lines.append("  ".join(cells))
    return "\n".join(lines)


def render_table(results: list[CheckResult], *, with_diff: bool) -> str:
    try:
        from rich.console import Console
        from rich.markup import escape
        from rich.table import Table
        from rich import box
    except ImportError:
        return _plain_table(results, with_diff=with_diff)

    table = Table(box=box.SIMPLE, header_style="bold", show_lines=False, pad_edge=False)
    columns = ["status", "type", "place", "reason", "input"]
    if with_diff:
        columns = ["change", "previous", *columns]
    widths = {
        "status": 26,
        "type": 6,
        "place": 22,
        "reason": 52,
        "input": 40,
        "change": 10,
        "previous": 26,
    }
    for name in columns:
        overflow = "ellipsis" if name in {"reason", "input", "place"} else "fold"
        table.add_column(
            name,
            overflow=overflow,
            min_width=widths[name] if name in {"status", "previous", "change", "type"} else None,
            max_width=widths[name],
            no_wrap=name != "reason",
        )

    for result in results:
        status = result.status
        if status == "Active":
            status_cell = f"[green]{status}[/green]"
        elif status.startswith("Inactive"):
            status_cell = f"[red]{status}[/red]"
        else:
            status_cell = f"[yellow]{status}[/yellow]"
        cells = [
            status_cell,
            escape(result.type),
            escape(result.place_name),
            escape(result.reason),
            escape(result.input_url),
        ]
        if with_diff:
            change = result.change
            if change == "changed":
                change = f"[bold]{change}[/bold]"
            cells = [change, result.previous_status, *cells]
        table.add_row(*cells)

    console = Console(width=180, soft_wrap=False)
    with console.capture() as capture:
        console.print(table)
    return capture.get().rstrip()


def changed_lines(results: list[CheckResult]) -> list[str]:
    lines = []
    for result in results:
        if result.change != "changed":
            continue
        lines.append(
            f"  {result.previous_status}  ->  {result.status}    {result.input_url}"
        )
    return lines
