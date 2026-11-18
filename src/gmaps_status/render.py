"""Render a Maps URL in headless Chromium and read the visible text.

This is a read. The page is never asked to report, edit, review, or flag
anything. Consent buttons may be clicked so the English UI is actually shown.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path

from gmaps_status.models import CONSENT_COOKIE, SOCS_COOKIE, USER_AGENT

_CONSENT_LABELS = ("Accept all", "Reject all", "I agree", "Accept all cookies")


@dataclass
class Rendered:
    text: str = ""
    title: str = ""
    final_url: str = ""
    image_srcs: list[str] = field(default_factory=list)
    error: str = ""
    screenshot: str = ""


class Renderer:
    def __init__(
        self,
        browser_name: str,
        timeout: float,
        screenshot_dir: str | None,
        proxy: str | None = None,
    ):
        self.browser_name = browser_name
        self.timeout_ms = int(timeout * 1000)
        self.screenshot_dir = Path(screenshot_dir) if screenshot_dir else None
        self.proxy = proxy
        self._playwright = None
        self._browser = None
        self._context = None

    async def __aenter__(self) -> "Renderer":
        try:
            from playwright.async_api import async_playwright
        except ImportError as exc:
            raise RuntimeError(
                "playwright is not installed. Use --no-render, or pip install playwright "
                "and run playwright install chromium."
            ) from exc
        self._playwright = await async_playwright().start()
        self._browser = await self._launch()
        self._context = await self._browser.new_context(
            locale="en-US",
            viewport={"width": 1400, "height": 900},
            user_agent=USER_AGENT,
        )
        await self._context.add_cookies(
            [
                {
                    "name": "CONSENT",
                    "value": CONSENT_COOKIE,
                    "domain": ".google.com",
                    "path": "/",
                },
                {
                    "name": "SOCS",
                    "value": SOCS_COOKIE,
                    "domain": ".google.com",
                    "path": "/",
                },
            ]
        )
        if self.screenshot_dir:
            self.screenshot_dir.mkdir(parents=True, exist_ok=True)
        return self

    async def _launch(self):
        args = [
            "--disable-blink-features=AutomationControlled",
            "--lang=en-US",
            "--no-sandbox",
            "--disable-dev-shm-usage",
        ]
        name = self.browser_name
        errors: list[str] = []
        attempts: list[dict] = []
        if name in {"auto", "chrome"}:
            attempts.append({"channel": "chrome", "headless": True, "args": args})
        if name in {"auto", "chromium"}:
            attempts.append({"headless": True, "args": args})
        if not attempts:
            attempts.append({"channel": name, "headless": True, "args": args})
        for kwargs in attempts:
            if self.proxy:
                kwargs["proxy"] = {"server": self.proxy}
            try:
                return await self._playwright.chromium.launch(**kwargs)
            except Exception as exc:  # playwright raises Error, not a narrow type
                errors.append(f"{kwargs.get('channel', 'chromium')}: {exc}")
        raise RuntimeError(
            "could not launch a browser (" + "; ".join(errors) + "). "
            "Install Google Chrome, or run `playwright install chromium`."
        )

    async def __aexit__(self, *_exc) -> None:
        if self._context:
            await self._context.close()
        if self._browser:
            await self._browser.close()
        if self._playwright:
            await self._playwright.stop()

    async def render(self, url: str, *, screenshot_stem: str = "") -> Rendered:
        page = await self._context.new_page()
        try:
            target = url if "hl=" in url else url + ("&" if "?" in url else "?") + "hl=en"
            await page.goto(target, wait_until="domcontentloaded", timeout=self.timeout_ms)
            await self._dismiss_consent(page)
            await self._wait_for_signal(page)
            title = await page.title()
            text = await page.inner_text("body")
            final_url = page.url
            srcs = await page.eval_on_selector_all(
                "img",
                "els => els.map(e => e.currentSrc || e.src).filter(Boolean).slice(0, 40)",
            )
            shot = ""
            if self.screenshot_dir and screenshot_stem:
                path = self.screenshot_dir / f"{screenshot_stem}.png"
                await page.screenshot(path=str(path))
                shot = str(path)
            return Rendered(
                text=text or "",
                title=title or "",
                final_url=final_url or "",
                image_srcs=list(srcs or []),
                screenshot=shot,
            )
        except Exception as exc:
            return Rendered(error=f"{exc.__class__.__name__}: {exc}".splitlines()[0][:240])
        finally:
            await page.close()

    async def _dismiss_consent(self, page) -> None:
        for label in _CONSENT_LABELS:
            locator = page.get_by_role("button", name=label)
            try:
                if await locator.count():
                    await locator.first.click(timeout=1500)
                    await page.wait_for_timeout(500)
                    return
            except Exception:
                continue

    async def _wait_for_signal(self, page) -> None:
        try:
            await page.wait_for_function(
                """() => {
                    const t = document.body ? document.body.innerText : '';
                    return t.includes('No user photo available here')
                        || t.includes('Photo - ')
                        || t.includes('Video - ')
                        || t.includes('Image capture:')
                        || t.includes('Directions');
                }""",
                timeout=min(self.timeout_ms, 15000),
            )
        except Exception:
            # The panel can still be useful; classification treats empty text as unknown.
            await page.wait_for_timeout(1500)
        else:
            await page.wait_for_timeout(800)
