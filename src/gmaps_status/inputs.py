"""Collect URLs from arguments, files, and stdin."""

from __future__ import annotations

import csv
import io
from dataclasses import dataclass, field
from pathlib import Path


@dataclass
class InputBatch:
    urls: list[str] = field(default_factory=list)
    duplicates: int = 0
    skipped: int = 0


def _from_csv(text: str) -> list[str]:
    sample = text.lstrip("\ufeff")
    try:
        dialect = csv.Sniffer().sniff(sample.splitlines()[0] if sample else "", delimiters=",\t")
    except csv.Error:
        dialect = csv.excel
    reader = csv.DictReader(io.StringIO(sample), dialect=dialect)
    if not reader.fieldnames:
        return []
    fields = [name.strip().lower() for name in reader.fieldnames if name]
    key = None
    for candidate in ("input_url", "url", "link", "maps_url"):
        if candidate in fields:
            key = reader.fieldnames[fields.index(candidate)]
            break
    if key is None:
        return []
    found = []
    for row in reader:
        value = (row.get(key) or "").strip()
        if value:
            found.append(value)
    return found


def _from_lines(text: str) -> list[str]:
    found = []
    for raw in text.splitlines():
        line = raw.strip()
        if not line or line.startswith("#"):
            continue
        # Allow "url  comment" only when the first token is the URL.
        token = line.split()[0].strip("\"'")
        found.append(token)
    return found


def urls_in_text(text: str, *, filename: str = "") -> list[str]:
    stripped = text.lstrip("\ufeff")
    head = stripped[:200].lower()
    looks_csv = filename.lower().endswith(".csv") or head.startswith(
        ("input_url", "url,", "url\t", "link,")
    )
    if looks_csv:
        rows = _from_csv(stripped)
        if rows:
            return rows
    return _from_lines(stripped)


def _accept(url: str) -> bool:
    return url.startswith("http://") or url.startswith("https://")


def collect_urls(raw_urls: list[str]) -> InputBatch:
    """Drop blanks, comments, and non-http values. Keep the first copy of each URL."""

    batch = InputBatch()
    seen: set[str] = set()
    for raw in raw_urls:
        url = raw.strip()
        if not url or url.startswith("#"):
            continue
        if not _accept(url):
            batch.skipped += 1
            continue
        if url in seen:
            batch.duplicates += 1
            continue
        seen.add(url)
        batch.urls.append(url)
    return batch


def load_inputs(
    argv_urls: list[str],
    files: list[str],
    stdin_text: str | None,
) -> InputBatch:
    raw: list[str] = list(argv_urls)
    for name in files:
        if name == "-":
            raw.extend(urls_in_text(stdin_text or "", filename="stdin.txt"))
            stdin_text = None
            continue
        path = Path(name)
        raw.extend(urls_in_text(path.read_text(encoding="utf-8"), filename=path.name))
    if stdin_text is not None:
        raw.extend(urls_in_text(stdin_text, filename="stdin.txt"))
    return collect_urls(raw)
