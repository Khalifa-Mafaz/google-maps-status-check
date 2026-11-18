"""Command-line entry point for gmaps-status."""

from __future__ import annotations

import argparse
import asyncio
import sys

from gmaps_status import __version__
from gmaps_status.inputs import load_inputs
from gmaps_status.output import (
    agreement,
    apply_diff,
    changed_lines,
    load_previous,
    render_table,
    summary_line,
    write_csv,
    write_json,
)
from gmaps_status.runner import Checker


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="gmaps-status",
        description=(
            "Check whether Google Maps links are still active. "
            "Read-only: this tool never reports, flags, reviews, or edits a listing."
        ),
        epilog=(
            "examples:\n"
            "  gmaps-status https://maps.app.goo.gl/example\n"
            "  gmaps-status -f urls.txt --csv today.csv --json today.json\n"
            "  gmaps-status -f urls.txt --previous yesterday.csv\n"
            "  gmaps-status -f urls.txt --no-render --concurrency 3\n"
            "  cat urls.txt | gmaps-status --screenshots shots/"
        ),
        formatter_class=argparse.RawDescriptionHelpFormatter,
    )
    parser.add_argument("urls", nargs="*", help="Maps URLs to check")
    parser.add_argument(
        "-f",
        "--file",
        action="append",
        default=[],
        metavar="FILE",
        help="text file (one URL per line) or CSV with an input_url/url column. Repeatable. Use - for stdin.",
    )
    parser.add_argument("--csv", metavar="FILE", help="write the full result table as CSV")
    parser.add_argument("--json", metavar="FILE", help="write the full result table as JSON")
    parser.add_argument(
        "--previous",
        metavar="CSV",
        help="earlier result CSV; print what changed status (for takedown tracking)",
    )
    parser.add_argument(
        "--concurrency",
        type=int,
        default=3,
        help="how many links to check at once (default 3)",
    )
    parser.add_argument(
        "--timeout",
        type=float,
        default=30.0,
        help="per-request timeout in seconds (default 30)",
    )
    parser.add_argument("--proxy", metavar="URL", help="HTTP(S) proxy for Maps and the browser")
    parser.add_argument(
        "--no-render",
        action="store_true",
        help="HTTP only. Image HTTP 200 and other uncertain cases are marked Unknown",
    )
    parser.add_argument(
        "--screenshots",
        metavar="DIR",
        help="save a PNG of each rendered page into DIR",
    )
    parser.add_argument(
        "--browser",
        default="auto",
        choices=["auto", "chrome", "chromium"],
        help="browser used for rendering (default: auto, prefer installed Chrome)",
    )
    parser.add_argument("--version", action="version", version=f"gmaps-status {__version__}")
    return parser


def main(argv: list[str] | None = None) -> int:
    parser = build_parser()
    args = parser.parse_args(argv)
    if args.concurrency < 1 or args.concurrency > 32:
        parser.error("--concurrency must be between 1 and 32")
    if args.timeout <= 0:
        parser.error("--timeout must be positive")

    use_stdin = False
    if "-" in args.file:
        use_stdin = True
    elif not args.urls and not args.file and not sys.stdin.isatty():
        use_stdin = True
    stdin_text = None
    if use_stdin:
        try:
            stdin_text = sys.stdin.read()
        except OSError:
            stdin_text = ""
    # A file of "-" consumes stdin inside load_inputs; don't also pass it as the fallback.
    try:
        if "-" in args.file:
            batch = load_inputs(args.urls, args.file, stdin_text)
        else:
            batch = load_inputs(args.urls, args.file, stdin_text if use_stdin else None)
    except OSError as exc:
        print(f"could not read input: {exc}", file=sys.stderr)
        return 2

    if batch.skipped:
        print(f"skipped {batch.skipped} line(s) that were not http(s) URLs", file=sys.stderr)
    if batch.duplicates:
        print(
            f"duplicate detection: skipped {batch.duplicates} repeated URL(s); each link is fetched once",
            file=sys.stderr,
        )
    if not batch.urls:
        parser.error("give at least one URL as an argument, with -f, or on stdin")

    if args.no_render and args.screenshots:
        print(
            "--screenshots needs a browser, so --no-render is ignored for pages that are rendered",
            file=sys.stderr,
        )
        args.no_render = False

    previous = load_previous(args.previous) if args.previous else None
    checker = Checker(
        concurrency=args.concurrency,
        timeout=args.timeout,
        proxy=args.proxy,
        no_render=args.no_render,
        screenshots=args.screenshots,
        browser=args.browser,
    )
    results = asyncio.run(checker.run(batch.urls))
    with_diff = previous is not None
    if previous is not None:
        apply_diff(results, previous)

    print(render_table(results, with_diff=with_diff))
    print()
    print(summary_line(results))
    if previous is not None:
        same, comparable = agreement(results)
        new = sum(1 for item in results if item.change == "new")
        changed = sum(1 for item in results if item.change == "changed")
        if comparable:
            pct = 100.0 * same / comparable
            print(f"agreement with previous: {same}/{comparable} ({pct:.1f}%)")
        else:
            print("agreement with previous: no overlapping URLs")
        print(f"changed: {changed}   new: {new}")
        lines = changed_lines(results)
        if lines:
            print("status changes:")
            print("\n".join(lines))

    if args.csv:
        write_csv(args.csv, results, with_diff=with_diff)
        print(f"wrote {args.csv}", file=sys.stderr)
    if args.json:
        write_json(args.json, results, with_diff=with_diff)
        print(f"wrote {args.json}", file=sys.stderr)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
