# google-maps-status-check

Read-only checker for Google Maps links. It tells a threat analyst whether a link is still **active**, or inactive because the **short link is dead**, the **contributed photo/video was removed**, or the **place itself was removed**.

It only sends GET requests and opens pages in a headless browser. It does not report, flag, review, suggest edits, or sign in.

```bash
gmaps-status -f urls.txt --csv today.csv --previous yesterday.csv
```

## Install on Debian and ChromeOS Crostini

Crostini is the Debian container behind ChromeOS Linux. These commands are the same on both.

```bash
sudo apt update
sudo apt install -y python3 python3-venv python3-pip
python3 -m venv .venv
source .venv/bin/activate
pip install -e ".[dev]"
```

Rendering uses headless Chromium. Either install Google Chrome, or let Playwright download Chromium:

```bash
# option A: Google Chrome (the tool prefers it automatically)
# https://www.google.com/chrome/  — the .deb installs on Crostini

# option B: Playwright's Chromium
playwright install chromium
playwright install-deps chromium   # if the browser exits on a missing system library
```

Check that it runs:

```bash
gmaps-status --help
python -m gmaps_status --version
```

HTTP-only mode does not need a browser:

```bash
gmaps-status --no-render -f urls.txt --csv fast.csv
```

## Usage

URLs can be arguments, a file, or stdin. Blank lines and `#` comments are ignored. A CSV is accepted when it has an `input_url`, `url`, or `link` column (so a previous result file can be rechecked). Repeated URLs are fetched once.

```bash
gmaps-status https://maps.app.goo.gl/example

gmaps-status -f urls.txt --csv today.csv --json today.json

cat urls.txt | gmaps-status --concurrency 3 --timeout 30

gmaps-status -f urls.txt --previous yesterday.csv

gmaps-status -f urls.txt --screenshots shots/ --browser chrome

gmaps-status --proxy http://127.0.0.1:8888 -f urls.txt
```

`--concurrency` defaults to 3. Checks also start at least 0.35 seconds apart. Raise the timeout if Maps is slow; the default is 30 seconds per request.

### Output columns

The console shows a short table. `--csv` and `--json` write every column:

| column | meaning |
| --- | --- |
| `input_url` | the URL you passed in |
| `status` | one of the five statuses below |
| `reason` | the signal that decided it |
| `type` | `photo`, `video`, `place`, or `other` |
| `place_name` | from the URL, or the rendered page title when the browser ran |
| `lat`, `lng` | place pin from `!3d` / `!4d` (not the street-view camera in `@lat,lng`) |
| `place_id` | hex feature id `0x…:0x…`, or a `ChIJ…` id when that is all the link has |
| `photo_id` | contributed photo or video id |
| `image_url` | `lh3` / `lh5` URL from `!6s` |
| `final_url` | where the short link actually landed |
| `checked_at` | UTC timestamp |

With `--previous old.csv` (a CSV that has `input_url` and `status`), two more columns are added: `previous_status` and `change` (`unchanged`, `changed`, or `new`). The summary prints an agreement count and lists every status that flipped. That is the takedown diff: run it again next week and see which links went from Active to removed.

## What the statuses mean

| status | meaning |
| --- | --- |
| `Active` | The place preview contains the place id, or the photo/video viewer is actually showing that contribution (`Photo - Mar 2025`, `Video - …`, `Image capture:`). |
| `Inactive - link dead` | The short link returned HTTP 404 or 410, or a redirect with no target. `maps.app.goo.gl` still returns **302** when the photo or place is gone, so a redirect is not a dead link. |
| `Inactive - photo removed` | The contribution is gone and the place is still listed. Also used for removed videos (there is no separate video status). |
| `Inactive - place removed` | The place record is gone, so the contribution has nowhere to live. |
| `Unknown` | The signals disagreed or a check failed (bot page, timeout, HTTP-only mode looking at a photo Google still hosts). Do not treat Unknown as taken down. |

## How a link is judged

Short links are followed without trusting the 302. The target URL is parsed:

- place name from `/maps/place/<name>/`, URL-decoded, with bidi overrides such as U+202D removed
- pin from `!3d<lat>!4d<lng>` — the `@lat,lng` in the path is only a fallback, because it is often the camera
- place id from `!1s0x…:0x…`, or `ChIJ…` on contribution links
- `!1e2` photo, `!1e5` video, then the `!1s` id that follows
- image URL from `!6s` (percent-decoded; `lh3`, `lh4`, `lh5`, and `gps-cs` hosts)

**Place removed vs photo removed.** The place page is fetched and the `/maps/preview/place?...` URL inside it is fetched with consent cookies, in English. A live place's preview contains its `0x…:0x…` id and is large (about 28–40 KB in the original manual run, about 44–132 KB in November 2026). A missing place comes back small and without that id (about 14.6 KB then, about 1.4 KB now). The tool treats a specific preview under 20 KB with no place id as removed. The id is the signal; the size is the backstop.

**Photos and videos.** An `lh3.googleusercontent.com` response of **403 or 404** means those bytes are gone. **HTTP 200 does not mean the listing is live** — Maps keeps serving files after the contribution is pulled. The reliable check is a headless Chromium render (en-US, `CONSENT` and `SOCS` cookies):

- `No user photo available here.` → photo removed (or place removed, if the preview says the place is gone)
- `Photo - <Mon YYYY>`, `Video -`, or `Image capture:` for **this** photo id → active
- the viewer rewrites the URL to a **different** photo id, or the image is 403/404 and the original id is no longer on the page → the contribution was removed and Maps substituted another photo, often the place cover
- a video stuck on `-:--` with no `Video -` caption → removed

`--no-render` skips Chromium. Dead links and place previews are still decided. A 403/404 image is reported as photo removed. A 200 image is **Unknown**, on purpose.

## Limitations

- Viewer text is matched in English. The tool asks for `hl=en` and `en-US`. A different language will not match `No user photo available here.`
- The consent cookies are what dismiss the EU wall. If Google rotates them, the page can stop showing the caption and results fall through to Unknown. Update `CONSENT_COOKIE` and `SOCS_COOKIE` in `src/gmaps_status/models.py` if that happens.
- Headless Chrome is sometimes served a bot check. The tool reports that as Unknown. Back off, or pass `--proxy`. It will not try to solve the check.
- A place that was deleted can still resolve by name to a *different* live place. When the preview's id is not the id in the link, the result is Unknown rather than Active.
- Public view only. A photo the owner can still see while logged in, and nobody else can, is inactive. That is the right call for an abuse listing.
- Street View panoramas without a contributed-photo marker are not called photos.
- Only `http(s)` links on Google Maps and `goo.gl` / `maps.app.goo.gl` are fetched.
- This does not submit a report, a review, or an edit, and it does not click "Report a problem".

## Tests

Unit tests cover URL parsing and the classification rules. They do not call Google.

```bash
source .venv/bin/activate
pytest
```

`tests/fixtures/smoke_urls.txt` is a five-link set checked live on 2026-11-17 (dead short link, live place, missing place, removed photo, live photo). It is a smoke test, not that 121-link corpus.

A regression against the original 121-link set (18 Active, 71 Inactive - photo removed, 32 Inactive - place removed) needs that run's `urls.txt` and `status.csv`. Those files were not in this tree. When you have them:

```bash
gmaps-status -f urls.txt --previous status.csv --csv today.csv
```

The agreement line is the regression result. Statuses that flipped are listed under `status changes`. Re-run with `--screenshots shots/` if you want to look at a disagreement before trusting it.

Expect some drift. Google rewrites share URLs, and a place that was only "photo removed" can later become "place removed" if the listing itself is taken down. Those show up as `changed`, which is what the diff is for.
