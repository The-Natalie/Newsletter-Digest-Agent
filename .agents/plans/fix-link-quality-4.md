# Feature: fix-link-quality-4 — Fix Sections Missing for Multipart Emails

The following plan should be complete, but validate codebase patterns and task sanity before implementing.

## Feature Description

`_extract_sections()` is only called when an email has HTML but no plain-text part. Most real newsletters are sent as `multipart/alternative` — they have **both** a plain-text part and an HTML part. The current code takes the `if plain_text is not None:` branch in `parse_emails()`, leaving `sections = []`. `_segment_email()` then falls back to plain-text body splitting, producing chunks with `links=[]`. Every cluster becomes sourceless and is dropped before reaching Claude.

The fix is a single change: also call `_extract_sections(html_text)` inside the plain-text branch when HTML is available alongside plain text.

## User Story

As the pipeline, I want section-level link extraction to run for all HTML emails (including multipart/alternative emails), so that story chunks carry their local links and source attribution is preserved.

## Problem Statement

`parse_emails()` has three branches:
1. `if plain_text is not None:` — sets `body = plain_text`; calls `_extract_links()` from HTML if present; does NOT call `_extract_sections()`
2. `elif html_text is not None:` — HTML-only path; calls `_extract_sections(html_text)` ✓
3. `else:` — no body; skipped

Branch 1 is the path taken for every `multipart/alternative` newsletter. Because `sections` stays `[]`, the sections-first path in `_segment_email()` is never reached for these emails.

## Scope

- In scope: `ingestion/email_parser.py` — one code block in `parse_emails()`
- Out of scope: `embedder.py`, `deduplicator.py`, all other files

## Solution Statement

In the `if plain_text is not None:` branch, when `html_text is not None`, add a call to `_extract_sections(html_text)` (wrapped in the same `try/except` pattern already used in the HTML-only branch). This populates `sections` so `_segment_email()` uses the sections-first path with per-section links.

## Feature Metadata

**Feature Type**: Bug Fix
**Estimated Complexity**: Low
**Primary Systems Affected**: `ingestion/email_parser.py`
**Dependencies**: None
**Assumptions**: `_extract_sections()` is safe to call on the original HTML before `_strip_noise()`.

---

## CONTEXT REFERENCES

### Relevant Codebase Files — READ BEFORE IMPLEMENTING

- `ingestion/email_parser.py` (lines 269–294) — the three-branch body extraction block in `parse_emails()`

### Patterns to Follow

**Existing try/except pattern for `_extract_sections()` call (HTML-only branch, lines ~289–292):**
```python
try:
    sections = _extract_sections(html_text)
except Exception:
    sections = []
```

---

## STEP-BY-STEP TASKS

### TASK 1: UPDATE `ingestion/email_parser.py` — call `_extract_sections()` in plain-text branch

In the `if plain_text is not None:` branch, extend the inner `if html_text is not None:` block to also call `_extract_sections()`.

**Current code:**
```python
        if plain_text is not None:
            body = plain_text
            # Still extract links from HTML part if it exists alongside plain text
            if html_text is not None:
                try:
                    html_soup = BeautifulSoup(html_text, "lxml")
                    links = _extract_links(html_soup)
                except Exception:
                    pass
```

**Replace with:**
```python
        if plain_text is not None:
            body = plain_text
            # Still extract links and sections from HTML part if present alongside plain text
            if html_text is not None:
                try:
                    html_soup = BeautifulSoup(html_text, "lxml")
                    links = _extract_links(html_soup)
                except Exception:
                    pass
                try:
                    sections = _extract_sections(html_text)
                except Exception:
                    sections = []
```

- **VALIDATE**: `python -c "import ingestion.email_parser; print('ok')"`

### TASK 2: DIAGNOSTIC SCRIPT — confirm sections are populated for a real email

Run this to inspect how many emails produce sections and how many links they contain:

```bash
python -c "
import sys, os
sys.path.insert(0, '.')
from config import settings
from ingestion.imap_client import fetch_emails
from ingestion.email_parser import parse_emails
import asyncio
from datetime import date

async def check():
    raw = await fetch_emails(settings.imap_folder or 'AI Newsletters', date(2026,3,16), date(2026,3,17))
    parsed = parse_emails(raw)
    for p in parsed:
        total_links = sum(len(s['links']) for s in p.sections)
        print(f'{p.sender[:40]:40s}  sections={len(p.sections):3d}  links={total_links:3d}')

asyncio.run(check())
"
```

Expected: most emails show `sections > 0` and `links > 0`.

- **VALIDATE**: at least one email shows `sections > 0` and `links > 0`

### TASK 3: SMOKE TEST — run full pipeline

```bash
python -m processing.digest_builder --folder "AI Newsletters" --start 2026-03-16 --end 2026-03-17
```

Expected: Stage 4 produces > 0 story groups; no "Dropped N sourceless story group(s)" log line covering all groups.

---

## VALIDATION COMMANDS

### Level 1: Import check

```bash
python -c "import ingestion.email_parser; print('email_parser OK')"
```

### Level 2: Full import chain

```bash
python -c "
from ingestion.email_parser import parse_emails, ParsedEmail
from processing.embedder import embed_and_cluster
from processing.deduplicator import deduplicate
print('All imports OK')
"
```

### Level 3: Diagnostic — sections populated for real emails

```bash
python -c "
import sys
sys.path.insert(0, '.')
from config import settings
from ingestion.imap_client import fetch_emails
from ingestion.email_parser import parse_emails
import asyncio
from datetime import date

async def check():
    raw = await fetch_emails(settings.imap_folder or 'AI Newsletters', date(2026,3,16), date(2026,3,17))
    parsed = parse_emails(raw)
    for p in parsed:
        total_links = sum(len(s['links']) for s in p.sections)
        print(f'{p.sender[:40]:40s}  sections={len(p.sections):3d}  links={total_links:3d}')

asyncio.run(check())
"
```

Expected: at least one email shows `sections > 0` and `links > 0`.

### Level 4: Full pipeline run

```bash
python -m processing.digest_builder --folder "AI Newsletters" --start 2026-03-16 --end 2026-03-17
```

Expected: Stage 4 and Stage 5 complete with > 0 story groups; digest entries have non-empty `sources`.

---

## MANUAL VERIFICATION CHECKLIST

- [ ] At least one email in the diagnostic output shows `sections > 0` and `links > 0`
- [ ] The pipeline run produces > 0 final stories (Stage 5 not empty)
- [ ] No log line reads "Dropped N sourceless story group(s)" where N equals the total cluster count
- [ ] Each digest entry has a non-empty `sources` array
- [ ] Source links are topically related to their digest entry

---

## VALIDATION OUTPUT REFERENCE — EXACT OUTPUTS TO CHECK

- Item to check:
  `python -c "import ingestion.email_parser; print('email_parser OK')"`
  Expected output or result:
  ```
  email_parser OK
  ```

- Item to check:
  ```
  python -c "
  from ingestion.email_parser import parse_emails, ParsedEmail
  from processing.embedder import embed_and_cluster
  from processing.deduplicator import deduplicate
  print('All imports OK')
  "
  ```
  Expected output or result:
  ```
  All imports OK
  ```

- Item to check:
  File `ingestion/email_parser.py` was modified — `_extract_sections()` is now also called inside the `if plain_text is not None: if html_text is not None:` block.
  Expected output or result:
  Import passes (confirmed by Level 1 above) and the diagnostic script (Level 3) shows `sections > 0` for at least one email.

- Item to check:
  Diagnostic script: at least one email shows `sections > 0` and `links > 0`
  Expected output or result:
  At least one output line from the diagnostic has a non-zero `sections=` value and a non-zero `links=` value, e.g.:
  ```
  Some Newsletter Name                      sections= 12  links=  8
  ```

- Item to check:
  The pipeline run does not drop all story groups as sourceless (manual run: `python -m processing.digest_builder --folder "AI Newsletters" --start 2026-03-16 --end 2026-03-17`)
  Expected output or result:
  The log does NOT contain a line like `Dropped 37 sourceless story group(s) (no valid links)` where 37 equals the total cluster count. Stage 5 produces > 0 digest entries.

- Item to check:
  Each digest entry has a non-empty `sources` array (manual run: `python -m processing.digest_builder --folder "AI Newsletters" --start 2026-03-16 --end 2026-03-17`)
  Expected output or result:
  Every entry in the printed digest JSON has `"sources": [...]` with at least one item.

- Item to check:
  Source links are topically related to their digest entry (manual run: `python -m processing.digest_builder --folder "AI Newsletters" --start 2026-03-16 --end 2026-03-17`)
  Expected output or result:
  For each entry, the source URLs and anchor text visibly relate to the topic described in the entry's headline and summary.

## NOTES

- `_extract_sections()` is called on the **original** `html_text`, not the noise-stripped version. This is intentional and consistent with the HTML-only branch.
- The two `try/except` blocks are kept separate so a failure in `_extract_links()` does not prevent `_extract_sections()` from running, and vice versa.
- If the diagnostic still shows `sections=0` for all emails after the fix, the next investigation target is whether `_extract_sections()` is silently raising and returning `[]` — add `import traceback; traceback.print_exc()` inside the except to check.
