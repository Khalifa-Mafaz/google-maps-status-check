"""Check many URLs with a small concurrency limit and a shared browser."""

from __future__ import annotations

import asyncio
import sys
from datetime import datetime, timezone

from gmaps_status.classify import assess_place, classify
from gmaps_status.http_checks import fetch_preview, make_client, probe_image, resolve_url
from gmaps_status.models import UNKNOWN, CheckResult, Evidence
from gmaps_status.parse import parse_maps_url
from gmaps_status.render import Renderer


class _Gate:
    """Start at most `concurrency` checks, and not faster than `min_interval`."""

    def __init__(self, concurrency: int, min_interval: float):
        self._sem = asyncio.Semaphore(concurrency)
        self._interval = min_interval
        self._lock = asyncio.Lock()
        self._next = 0.0

    async def __aenter__(self):
        await self._sem.acquire()
        async with self._lock:
            loop = asyncio.get_running_loop()
            now = loop.time()
            if now < self._next:
                await asyncio.sleep(self._next - now)
            self._next = asyncio.get_running_loop().time() + self._interval
        return self

    async def __aexit__(self, *_exc):
        self._sem.release()


def _now() -> str:
    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


class Checker:
    def __init__(
        self,
        *,
        concurrency: int = 3,
        timeout: float = 30.0,
        proxy: str | None = None,
        no_render: bool = False,
        screenshots: str | None = None,
        browser: str = "auto",
        min_interval: float = 0.35,
    ):
        self.timeout = timeout
        self.proxy = proxy
        self.no_render = no_render
        self.screenshots = screenshots
        self.browser = browser
        self._gate = _Gate(max(1, concurrency), min_interval)
        self._renderer: Renderer | None = None
        self._render_lock = asyncio.Lock()
        self._render_error: str | None = None

    async def _renderer_for(self) -> Renderer:
        async with self._render_lock:
            if self._render_error:
                raise RuntimeError(self._render_error)
            if self._renderer is None:
                renderer = Renderer(
                    self.browser,
                    self.timeout,
                    self.screenshots,
                    proxy=self.proxy,
                )
                try:
                    await renderer.__aenter__()
                except Exception as exc:
                    self._render_error = str(exc)
                    raise
                self._renderer = renderer
            return self._renderer

    async def close(self) -> None:
        if self._renderer is not None:
            await self._renderer.__aexit__(None, None, None)
            self._renderer = None

    def _wants_render(self, kind: str, preview_known: bool) -> bool:
        if self.no_render:
            return False
        if self.screenshots:
            return True
        if kind in {"photo", "video"}:
            return True
        if kind == "place" and not preview_known:
            return True
        return False

    async def check_one(self, client, url: str, index: int) -> CheckResult:
        checked_at = _now()
        try:
            resolved = await resolve_url(client, url)
        except Exception as exc:  # keep one bad URL from killing the batch
            return CheckResult(
                input_url=url,
                status=UNKNOWN,
                reason=f"check failed: {exc.__class__.__name__}",
                checked_at=checked_at,
            )

        parsed = parse_maps_url(resolved.final_url or url)
        evidence = Evidence(
            input_url=url,
            parsed=parsed,
            final_url=resolved.final_url,
            link_dead=resolved.dead,
            dead_reason=resolved.dead_reason,
            blocked_reason=resolved.blocked_reason,
            no_render=self.no_render,
        )
        if resolved.error and not resolved.dead and not resolved.blocked_reason:
            evidence.blocked_reason = resolved.error

        if not resolved.dead and not evidence.blocked_reason and parsed.is_maps:
            image_task = asyncio.create_task(probe_image(client, parsed.image_url))
            preview_task = asyncio.create_task(
                fetch_preview(
                    client,
                    parsed=parsed,
                    final_url=resolved.final_url,
                    page_html=resolved.body,
                    kind=parsed.kind,
                )
            )
            image_status, preview = await asyncio.gather(image_task, preview_task)
            evidence.image_status = image_status
            evidence.preview_body = preview.body
            evidence.preview_size = preview.size
            evidence.preview_error = preview.error
            evidence.preview_trustworthy = preview.trustworthy

            conclusive = assess_place(evidence) in {"exists", "removed"}
            if self._wants_render(parsed.kind, conclusive):
                try:
                    renderer = await self._renderer_for()
                    rendered = await renderer.render(
                        resolved.final_url,
                        screenshot_stem=f"{index + 1:03d}",
                    )
                except RuntimeError as exc:
                    rendered_error = str(exc)
                    evidence.render_error = rendered_error
                    evidence.no_render = True
                else:
                    evidence.render_text = rendered.text
                    evidence.render_title = rendered.title
                    evidence.render_final_url = rendered.final_url
                    evidence.render_image_srcs = rendered.image_srcs
                    evidence.render_error = rendered.error

        result = classify(evidence)
        result.checked_at = checked_at
        return result

    async def run(self, urls: list[str]) -> list[CheckResult]:
        client = make_client(self.timeout, self.proxy)
        results: list[CheckResult | None] = [None] * len(urls)

        async def wrapped(index: int, url: str) -> None:
            async with self._gate:
                try:
                    result = await self.check_one(client, url, index)
                except Exception as exc:
                    result = CheckResult(
                        input_url=url,
                        status=UNKNOWN,
                        reason=f"check failed: {exc.__class__.__name__}: {exc}",
                        checked_at=_now(),
                    )
                results[index] = result
                label = result.place_name or result.input_url
                print(
                    f"[{index + 1}/{len(urls)}] {result.status}  {result.type}  {label}",
                    file=sys.stderr,
                    flush=True,
                )

        try:
            await asyncio.gather(*(wrapped(i, url) for i, url in enumerate(urls)))
        finally:
            await client.aclose()
            await self.close()
        return [item for item in results if item is not None]
