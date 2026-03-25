# Feature: ingestion/email_parser.py

The following plan should be complete, but validate codebase patterns before starting.

Pay special attention to: `email.policy.default` vs `policy.compat32`, BeautifulSoup hidden-element detection patterns, html2text configuration, and the exact shape of `ParsedEmail` that downstream consumers expect.

## Feature Description

Create `ingestion/email_parser.py` — the module that converts a list of raw MIME email bytes (from `imap_client.py`) into a list of `ParsedEmail` dataclass instances. Each `ParsedEmail` contains: sender display name, subject, date, cleaned plain-text body, and a structured list of hyperlinks. This is the second stage of the pipeline and the most likely source of extraction issues (PRD §14 Risk 2).

## User Story

As the digest pipeline,
I want a function that accepts raw MIME bytes and returns structured email data,
So that the embedder and AI client can work with clean text and source links without knowing anything about MIME or HTML.

## Problem Statement

Raw MIME bytes are unusable for embedding or summarization. Newsletter HTML contains tracking pixels, hidden pre-header text, navigation boilerplate, and encoded content that would corrupt deduplication and AI quality if not stripped first.

## Scope

- In scope: MIME parsing, text/plain + text/html body extraction, BeautifulSoup pre-processing, html2text conversion, link extraction, hidden element stripping, sender/subject/date extraction, short-body warning
- Out of scope: story segmentation (done in `processing/`), deduplication, any network calls

## Solution Statement

Use Python's `email.message_from_bytes` with `policy.default` (auto-decodes QP/base64, returns `EmailMessage`). Prefer `text/plain` body; fall back to `text/html`. For HTML, run a two-pass pipeline: (1) BeautifulSoup strips noise, (2) html2text converts cleaned HTML to plain text. Extract links from BeautifulSoup before stripping, preserving `url` + `anchor_text` as structured dicts. Return a `list[ParsedEmail]`, skipping emails that produce no body.

## Feature Metadata

**Feature Type**: New Capability
**Estimated Complexity**: Medium
**Primary Systems Affected**: `ingestion/email_parser.py`
**Dependencies**: `beautifulsoup4==4.14.3`, `lxml==6.0.2`, `html2text==(2025, 4, 15)` — all installed
**Assumptions**: Input is `list[bytes]` as returned by `fetch_emails()`; downstream consumers (`embedder.py`, `digest_builder.py`) access `.body`, `.sender`, `.subject`, `.date`, `.links` attributes

---

## CONTEXT REFERENCES

### Relevant Codebase Files — READ BEFORE IMPLEMENTING

- `ingestion/imap_client.py` (whole file, 69 lines) — establishes module pattern: `from __future__ import annotations`, top-level functions only, no class except custom exceptions, docstrings with Args/Returns/Raises
- `config.py` (whole file, 29 lines) — confirm `settings` import pattern; no config fields needed for this module (html2text and BS4 config is hardcoded)
- `PRD.md` §7 Feature 2 (lines 255–272) — full extraction spec and pitfall list
- `PRD.md` §14 Risk 2 (lines 701–705) — "Log the character count of extracted text per email; extractions under 200 characters are flagged as suspected parse failures in server logs"
- `PRD.md` §10 API spec (lines 536–541) — shows the `sources` shape: `{"newsletter": "TLDR AI", "url": "https://...", "anchor_text": "..."}` — `newsletter` maps to `ParsedEmail.sender`

### New Files to Create

- `ingestion/email_parser.py` — `ParsedEmail` dataclass + `parse_emails()` function

### Relevant Documentation — READ BEFORE IMPLEMENTING

- Python email policy.default: https://docs.python.org/3/library/email.policy.html#email.policy.default
  - Why: `policy.default` decodes QP/base64 automatically; `EmailMessage.get_body()` for MIME traversal
- BeautifulSoup find/decompose: https://www.crummy.com/software/BeautifulSoup/bs4/doc/#decompose
  - Why: `tag.decompose()` removes element and contents; use for stripping `<img>`, `<style>`, `<script>`, hidden elements
- html2text config: https://github.com/Alir3z4/html2text/blob/master/docs/usage.md
  - Why: `ignore_links`, `ignore_images`, `body_width=0`, `unicode_snob` settings

### Patterns to Follow

**Module structure** (mirror `ingestion/imap_client.py`):
```python
from __future__ import annotations

import logging
from dataclasses import dataclass, field
from datetime import datetime
# stdlib and third-party imports
```

**Dataclass pattern** — use `@dataclass` with type hints:
```python
@dataclass
class ParsedEmail:
    subject: str
    sender: str
    date: datetime | None
    body: str
    links: list[dict] = field(default_factory=list)
```

**Private helper functions** — `_` prefix, not exported:
- `_get_html_part()`, `_get_plain_part()`, `_strip_noise()`, `_extract_links()`, `_html_to_text()`

**Logging** — module-level logger (standard Python pattern for library code):
```python
logger = logging.getLogger(__name__)
```
Warn on short body: `logger.warning("Short extraction (%d chars) for email from %s", len(body), sender)`

---

## IMPLEMENTATION PLAN

### Phase 1: Data model

Define `ParsedEmail` dataclass — the contract between ingestion and processing.

### Phase 2: MIME traversal helpers

Implement private helpers for extracting the plain-text part and the HTML part from a parsed `EmailMessage`.

### Phase 3: HTML processing pipeline

Implement BeautifulSoup pre-processing (`_strip_noise`) and html2text conversion (`_html_to_text`). Implement link extraction (`_extract_links`).

### Phase 4: Top-level parse function

Implement `parse_emails(raw_messages: list[bytes]) -> list[ParsedEmail]` that orchestrates all helpers per email.

---

## STEP-BY-STEP TASKS

### TASK 1 — CREATE `ingestion/email_parser.py` — Data model + imports

- **IMPLEMENT**: File header, all imports, module-level logger, `ParsedEmail` dataclass
- **IMPORTS**:
  ```python
  from __future__ import annotations

  import email
  import email.utils
  import logging
  from dataclasses import dataclass, field
  from datetime import datetime
  from email import policy

  import html2text
  from bs4 import BeautifulSoup
  ```
- **IMPLEMENT `ParsedEmail` dataclass**:
  ```python
  @dataclass
  class ParsedEmail:
      subject: str
      sender: str           # Display name from From header (or email address if no display name)
      date: datetime | None # Parsed from Date header; None if missing or unparseable
      body: str             # Cleaned plain text; empty string if extraction failed
      links: list[dict]     # [{"url": "...", "anchor_text": "..."}, ...]
  ```
  - Use `field(default_factory=list)` for `links`
- **VALIDATE**: `python -c "from ingestion.email_parser import ParsedEmail; print(ParsedEmail.__dataclass_fields__.keys())"`
  Expected: `dict_keys(['subject', 'sender', 'date', 'body', 'links'])`

---

### TASK 2 — ADD private helper `_get_body_parts(msg)`

- **IMPLEMENT**: Extracts `(plain_text, html_bytes)` from a parsed `EmailMessage`
- **LOGIC**:
  1. Try `msg.get_body(preferencelist=('plain',))` → if found, call `.get_content()` → `plain_text: str`
  2. Try `msg.get_body(preferencelist=('html',))` → if found, call `.get_content()` → `html_text: str`
  3. Return `(plain_text or None, html_text or None)`
- **GOTCHA**: `get_body()` requires `policy.default` on the message object — it does NOT exist on `email.policy.compat32` (default policy). Always parse with `policy=policy.default`.
- **GOTCHA**: `get_content()` (not `get_payload()`) is the `EmailMessage`-specific method that handles charset decoding. `get_payload(decode=True)` returns `bytes` and requires manual charset decoding — avoid it.
- **GOTCHA**: `get_body()` can return `None` if the part doesn't exist — always null-check before calling `.get_content()`.

```python
def _get_body_parts(msg) -> tuple[str | None, str | None]:
    plain_part = msg.get_body(preferencelist=("plain",))
    html_part = msg.get_body(preferencelist=("html",))
    plain_text = plain_part.get_content() if plain_part is not None else None
    html_text = html_part.get_content() if html_part is not None else None
    return plain_text, html_text
```

---

### TASK 3 — ADD private helper `_extract_links(soup)`

- **IMPLEMENT**: Extract all hyperlinks from a BeautifulSoup tree before noise is stripped
- **LOGIC**: Find all `<a href="...">` tags; skip anchors with empty/None href or `mailto:` scheme; return `list[dict]`
- **IMPLEMENT**:
  ```python
  def _extract_links(soup: BeautifulSoup) -> list[dict]:
      links = []
      for a in soup.find_all("a", href=True):
          url = a["href"].strip()
          if not url or url.startswith("mailto:"):
              continue
          anchor_text = a.get_text(strip=True)
          if anchor_text:  # skip links with no visible text
              links.append({"url": url, "anchor_text": anchor_text})
      return links
  ```
- **GOTCHA**: Extract links BEFORE calling `_strip_noise()` — stripping removes elements and their children. The `<a>` tags may be inside elements that get stripped.
- **VALIDATE** (inline with TASK 5's end-to-end test)

---

### TASK 4 — ADD private helper `_strip_noise(soup)`

- **IMPLEMENT**: Mutate the BeautifulSoup tree in-place to remove all noise elements
- **REMOVE these tag types** using `tag.decompose()`:
  - `<img>` — tracking pixels and inline images
  - `<style>` — CSS blocks
  - `<script>` — JavaScript
  - `<head>` — metadata not visible in email body
- **REMOVE hidden elements** — iterate over all tags and decompose if they match any of:
  - `style` attribute contains `display:none` or `display: none`
  - `style` attribute contains `visibility:hidden` or `visibility: hidden`
  - `style` attribute contains `font-size:0` or `font-size: 0`
  - `style` attribute contains `color:#fff` or `color:#ffffff` or `color:white` (white-on-white)
  - `class` attribute contains `preheader`, `preview-text`, or `preview` (case-insensitive)
- **GOTCHA**: Use `soup.find_all(True)` to iterate all tags. Collect matches first into a list, then call `decompose()` — do NOT decompose while iterating the find_all generator (modifying the tree during iteration causes skips).
- **GOTCHA**: `tag.get("style", "")` returns `""` not `None` when the attribute is absent — safe for string operations.
- **GOTCHA**: The `class` attribute in BeautifulSoup is a `list`, not a string. Use `" ".join(tag.get("class", []))` to get a space-joined string for substring matching.

```python
_NOISE_TAGS = {"img", "style", "script", "head"}
_HIDDEN_STYLE_PATTERNS = (
    "display:none", "display: none",
    "visibility:hidden", "visibility: hidden",
    "font-size:0", "font-size: 0",
    "color:#fff", "color:#ffffff", "color:white",
)
_HIDDEN_CLASS_KEYWORDS = ("preheader", "preview-text", "preview")

def _strip_noise(soup: BeautifulSoup) -> None:
    # Remove structural noise tags
    for tag in soup.find_all(_NOISE_TAGS):
        tag.decompose()

    # Remove hidden elements
    to_remove = []
    for tag in soup.find_all(True):
        style = tag.get("style", "").lower().replace(" ", "")
        classes = " ".join(tag.get("class", [])).lower()
        if any(p.replace(" ", "") in style for p in _HIDDEN_STYLE_PATTERNS):
            to_remove.append(tag)
        elif any(k in classes for k in _HIDDEN_CLASS_KEYWORDS):
            to_remove.append(tag)
    for tag in to_remove:
        tag.decompose()
```

---

### TASK 5 — ADD private helper `_html_to_text(html_str)`

- **IMPLEMENT**: Configure and run html2text on a cleaned HTML string
- **CONFIGURATION**:
  ```python
  def _html_to_text(html_str: str) -> str:
      h = html2text.HTML2Text()
      h.ignore_links = True    # links already extracted separately
      h.ignore_images = True   # images already stripped by BS4
      h.body_width = 0         # no line wrapping
      h.unicode_snob = True    # use unicode characters (e.g. em-dash) not ASCII approximations
      return h.handle(html_str)
  ```
- **GOTCHA**: `h.handle()` accepts a `str`, not `bytes`. Always pass a decoded string.
- **GOTCHA**: `body_width = 0` is essential — default wrapping at 78 chars inserts newlines in the middle of sentences, which degrades embedding quality.

---

### TASK 6 — IMPLEMENT top-level `parse_emails()`

- **IMPLEMENT**: Main public function — orchestrates all helpers for each raw message
- **SIGNATURE**: `def parse_emails(raw_messages: list[bytes]) -> list[ParsedEmail]:`
- **PER-EMAIL LOGIC**:
  1. `msg = email.message_from_bytes(raw, policy=policy.default)`
  2. Extract subject: `msg.get("Subject", "")` — with `policy.default`, this is already decoded (no `=?utf-8?...?=` encodings)
  3. Extract sender: `email.utils.parseaddr(msg.get("From", ""))` returns `(display_name, addr)` — use `display_name` if non-empty, else `addr`
  4. Extract date: `email.utils.parsedate_to_datetime(msg.get("Date", ""))` — wrap in try/except, set to `None` on failure
  5. Get body parts: `plain_text, html_text = _get_body_parts(msg)`
  6. If `plain_text` is not None → `body = plain_text` (already clean text)
  7. Else if `html_text` is not None →
     - `soup = BeautifulSoup(html_text, "lxml")`
     - `links = _extract_links(soup)` (BEFORE stripping)
     - `_strip_noise(soup)` (mutates soup)
     - `body = _html_to_text(str(soup))`
  8. Else → `body = ""`, `links = []`
  9. If `plain_text` path: links must still be extracted. For plain/html multipart emails, HTML part may still exist — check `html_text` for link extraction even when using `plain_text` as body.
  10. Warn if `len(body.strip()) < 200`: `logger.warning(...)`
  11. Skip emails with empty body entirely: `if not body.strip(): continue`
  12. Append `ParsedEmail(subject=subject, sender=sender, date=date_parsed, body=body.strip(), links=links)`
- **RETURN**: `list[ParsedEmail]`
- **GOTCHA**: For multipart emails with both `text/plain` and `text/html`, use `text/plain` as body BUT extract links from `text/html` (plain text has no structured link data). So the logic is: `body = plain_text`, `links = _extract_links(BeautifulSoup(html_text, "lxml"))` when both parts exist.
- **GOTCHA**: `email.utils.parsedate_to_datetime` raises `TypeError` if the Date header is `None` and `ValueError` if the date string is malformed. Wrap in `try/except (TypeError, ValueError)` and default to `None`.
- **GOTCHA**: `policy.default` decodes RFC 2047 encoded subject/sender headers automatically — do NOT use `email.header.decode_header()` or `make_header()` — that is the old `compat32` approach.
- **VALIDATE**: End-to-end test with synthetic MIME bytes (see Testing Strategy)

---

## TESTING STRATEGY

No separate test file is required for Phase 1. Validation uses synthetic MIME byte fixtures inline as one-liners or short scripts.

### Smoke Test — Minimal HTML email

Build a minimal but realistic HTML-only MIME email in Python and run it through `parse_emails`:

```python
import textwrap
from ingestion.email_parser import parse_emails

RAW = textwrap.dedent("""\
    MIME-Version: 1.0
    From: TLDR AI <hello@tldr.tech>
    To: user@example.com
    Subject: AI Newsletter - March 25
    Date: Tue, 25 Mar 2026 08:00:00 +0000
    Content-Type: text/html; charset=utf-8

    <html><body>
    <span style="display:none">Pre-header preview text here</span>
    <img src="track.png" width="1" height="1">
    <h1>OpenAI releases GPT-5</h1>
    <p>OpenAI launched GPT-5 on March 14. <a href="https://openai.com/gpt5">Read more</a></p>
    </body></html>
""").encode()

results = parse_emails([RAW])
print(len(results))           # 1
print(results[0].sender)      # TLDR AI
print(results[0].subject)     # AI Newsletter - March 25
print(results[0].date)        # datetime object
print(results[0].body[:80])   # OpenAI releases GPT-5  (no pre-header, no img)
print(results[0].links)       # [{'url': 'https://openai.com/gpt5', 'anchor_text': 'Read more'}]
```

### Smoke Test — Plain text preferred over HTML

```python
import textwrap
from ingestion.email_parser import parse_emails

RAW = textwrap.dedent("""\
    MIME-Version: 1.0
    From: The Rundown <news@therundown.ai>
    Subject: Today's AI News
    Date: Tue, 25 Mar 2026 09:00:00 +0000
    Content-Type: multipart/alternative; boundary="boundary42"

    --boundary42
    Content-Type: text/plain; charset=utf-8

    OpenAI releases GPT-5. This is the plain text version.

    --boundary42
    Content-Type: text/html; charset=utf-8

    <html><body><p>OpenAI releases GPT-5. <a href="https://openai.com">Link</a></p></body></html>
    --boundary42--
""").encode()

results = parse_emails([RAW])
print(results[0].body)       # plain text version (not HTML)
print(results[0].links)      # [{'url': 'https://openai.com', 'anchor_text': 'Link'}]  (from HTML part)
```

### Edge Cases

- Empty message list: `parse_emails([])` → `[]`
- Email with no body parts: produces no result (skipped)
- Missing Date header: `parsed.date is None`
- Missing From display name: `sender` = email address string
- Pre-header `display:none` span: stripped from body text
- Tracking `<img>`: removed before html2text
- `mailto:` links: excluded from `links` list
- Links with no anchor text: excluded from `links` list

---

## VALIDATION COMMANDS

### Level 1: Syntax & Import Check

```bash
cd "/Users/natalie/Documents/Agentic AI/Newsletter Digest Agent" && .venv/bin/python -c "from ingestion.email_parser import parse_emails, ParsedEmail; print('import OK')"
```
Expected output: `import OK`

### Level 2: Dataclass fields check

```bash
cd "/Users/natalie/Documents/Agentic AI/Newsletter Digest Agent" && .venv/bin/python -c "from ingestion.email_parser import ParsedEmail; print(list(ParsedEmail.__dataclass_fields__.keys()))"
```
Expected output: `['subject', 'sender', 'date', 'body', 'links']`

### Level 3: HTML-only email smoke test

```bash
cd "/Users/natalie/Documents/Agentic AI/Newsletter Digest Agent" && .venv/bin/python -c "
import textwrap
from ingestion.email_parser import parse_emails

RAW = textwrap.dedent('''
    MIME-Version: 1.0
    From: TLDR AI <hello@tldr.tech>
    Subject: AI Newsletter - March 25
    Date: Tue, 25 Mar 2026 08:00:00 +0000
    Content-Type: text/html; charset=utf-8

    <html><body>
    <span style=\"display:none\">Pre-header preview text here</span>
    <img src=\"track.png\" width=\"1\" height=\"1\">
    <h1>OpenAI releases GPT-5</h1>
    <p>OpenAI launched GPT-5 on March 14. <a href=\"https://openai.com/gpt5\">Read more</a></p>
    </body></html>
''').strip().encode()

results = parse_emails([RAW])
assert len(results) == 1, f'Expected 1 result, got {len(results)}'
e = results[0]
assert e.sender == 'TLDR AI', f'sender={e.sender!r}'
assert e.subject == 'AI Newsletter - March 25', f'subject={e.subject!r}'
assert e.date is not None, 'date should not be None'
assert 'Pre-header' not in e.body, 'pre-header should be stripped'
assert 'OpenAI' in e.body, f'body={e.body!r}'
assert e.links == [{'url': 'https://openai.com/gpt5', 'anchor_text': 'Read more'}], f'links={e.links}'
print('HTML-only smoke test PASSED')
print('sender:', e.sender)
print('subject:', e.subject)
print('body preview:', e.body[:80].strip())
print('links:', e.links)
"
```
Expected output:
```
HTML-only smoke test PASSED
sender: TLDR AI
subject: AI Newsletter - March 25
body preview: # OpenAI releases GPT-5
links: [{'url': 'https://openai.com/gpt5', 'anchor_text': 'Read more'}]
```

### Level 4: Multipart (plain preferred, links from HTML)

```bash
cd "/Users/natalie/Documents/Agentic AI/Newsletter Digest Agent" && .venv/bin/python -c "
import textwrap
from ingestion.email_parser import parse_emails

RAW = textwrap.dedent('''
    MIME-Version: 1.0
    From: The Rundown <news@therundown.ai>
    Subject: Today AI News
    Date: Tue, 25 Mar 2026 09:00:00 +0000
    Content-Type: multipart/alternative; boundary=boundary42

    --boundary42
    Content-Type: text/plain; charset=utf-8

    OpenAI releases GPT-5. This is the plain text version.

    --boundary42
    Content-Type: text/html; charset=utf-8

    <html><body><p>OpenAI releases GPT-5. <a href=\"https://openai.com\">Read more</a></p></body></html>
    --boundary42--
''').strip().encode()

results = parse_emails([RAW])
e = results[0]
assert 'plain text version' in e.body, f'body={e.body!r}'
assert e.links == [{'url': 'https://openai.com', 'anchor_text': 'Read more'}], f'links={e.links}'
print('Multipart test PASSED')
print('body:', e.body.strip())
print('links:', e.links)
"
```
Expected output:
```
Multipart test PASSED
body: OpenAI releases GPT-5. This is the plain text version.
links: [{'url': 'https://openai.com', 'anchor_text': 'Read more'}]
```

### Level 5: Edge cases — empty list, missing Date, mailto filtering

```bash
cd "/Users/natalie/Documents/Agentic AI/Newsletter Digest Agent" && .venv/bin/python -c "
import textwrap
from ingestion.email_parser import parse_emails

# Empty input
assert parse_emails([]) == [], 'empty list should return []'

# Missing Date header
RAW_NO_DATE = textwrap.dedent('''
    MIME-Version: 1.0
    From: sender@example.com
    Subject: Test
    Content-Type: text/plain; charset=utf-8

    Some body text that is long enough to not be flagged as short.
    This is a second sentence to make the body longer.
    This is a third sentence to ensure we pass the 200-char threshold check.
''').strip().encode()
results = parse_emails([RAW_NO_DATE])
assert results[0].date is None, f'date={results[0].date}'

# mailto: links are excluded
RAW_MAILTO = textwrap.dedent('''
    MIME-Version: 1.0
    From: sender@example.com
    Subject: Test
    Date: Tue, 25 Mar 2026 09:00:00 +0000
    Content-Type: text/html; charset=utf-8

    <html><body><p>Hello. <a href=\"mailto:foo@bar.com\">Contact us</a> <a href=\"https://real.com\">Real link</a></p></body></html>
''').strip().encode()
results = parse_emails([RAW_MAILTO])
assert all(l['url'] != 'mailto:foo@bar.com' for l in results[0].links), 'mailto should be excluded'
assert any(l['url'] == 'https://real.com' for l in results[0].links), 'real link should be included'

# No display name — fall back to email address
RAW_NO_NAME = textwrap.dedent('''
    MIME-Version: 1.0
    From: sender@example.com
    Subject: Test
    Date: Tue, 25 Mar 2026 09:00:00 +0000
    Content-Type: text/plain; charset=utf-8

    Some body text to pass the length check. This is a second sentence to make the body longer.
''').strip().encode()
results = parse_emails([RAW_NO_NAME])
assert results[0].sender == 'sender@example.com', f'sender={results[0].sender!r}'

print('Edge case tests PASSED')
"
```
Expected output: `Edge case tests PASSED`

---

## MANUAL VERIFICATION CHECKLIST

- [ ] `ingestion/email_parser.py` imports cleanly
- [ ] `ParsedEmail` has exactly 5 fields: `subject`, `sender`, `date`, `body`, `links`
- [ ] `parse_emails([])` returns `[]` without error
- [ ] HTML smoke test passes (pre-header stripped, img removed, link extracted)
- [ ] Multipart test passes (plain text body preferred, links from HTML part)
- [ ] Edge cases test passes (missing Date → None, mailto filtered, no display name → email address)
- [ ] `parse_emails` uses `policy.default` (not `policy.compat32`)
- [ ] `body_width = 0` set on html2text (no line wrapping)
- [ ] Links extracted BEFORE `_strip_noise()` is called
- [ ] `logger.warning()` present for body shorter than 200 chars

## ROLLBACK CONSIDERATIONS

- New file only; rollback = delete `ingestion/email_parser.py`
- No database changes, migrations, or config changes

## ACCEPTANCE CRITERIA

- [ ] `parse_emails` accepts `list[bytes]` and returns `list[ParsedEmail]`
- [ ] `ParsedEmail` dataclass has fields: `subject`, `sender`, `date`, `body`, `links`
- [ ] `text/plain` preferred over `text/html` for body
- [ ] Links extracted from HTML even when plain text is used as body
- [ ] `<img>`, `<style>`, `<script>` removed before conversion
- [ ] `display:none` / hidden pre-header elements removed
- [ ] `mailto:` links excluded from `links` list
- [ ] Links with no anchor text excluded from `links` list
- [ ] Missing or malformed Date header → `date = None` (no crash)
- [ ] Missing From display name → fall back to email address string
- [ ] Body shorter than 200 chars → `logger.warning()` emitted
- [ ] Empty body emails skipped (not appended to results)
- [ ] All 5 validation commands pass

---

## COMPLETION CHECKLIST

- [ ] Task 1: `ParsedEmail` dataclass and imports implemented
- [ ] Task 2: `_get_body_parts()` implemented
- [ ] Task 3: `_extract_links()` implemented
- [ ] Task 4: `_strip_noise()` implemented
- [ ] Task 5: `_html_to_text()` implemented
- [ ] Task 6: `parse_emails()` implemented
- [ ] Level 1 validation passed
- [ ] Level 2 validation passed
- [ ] Level 3 validation passed
- [ ] Level 4 validation passed
- [ ] Level 5 validation passed

---

## NOTES

**Why `policy.default` is mandatory:**
`email.policy.compat32` (the historical default) returns `Message` objects. `get_body()` does not exist on `Message`. `policy.default` returns `EmailMessage` objects with `get_body()`, `get_content()`, and automatic charset/QP/base64 decoding. Always pass `policy=policy.default` to `email.message_from_bytes()`.

**Why links are extracted before stripping:**
`_strip_noise()` calls `decompose()` which permanently removes elements. If an `<a>` tag is inside a `<style>` element or a hidden span (unlikely but possible), it would be lost. More importantly, links in the pre-header or tracking sections may exist inside hidden `<span>` elements — extracting first, then filtering by the mailto/no-text rules, is the correct order. (In practice, hidden element children are unlikely to contain useful links anyway, but the ordering is correct.)

**Why `ignore_links=True` in html2text:**
Links are already extracted as structured `{"url", "anchor_text"}` dicts. Including `[text](url)` markdown in the body would add URL noise that degrades embedding quality for the deduplication step. The two representations (structured links list + clean text body) serve different downstream consumers.

**Why emails with empty body are skipped:**
An empty-body ParsedEmail would produce empty embeddings (all zeros or random noise) and pass garbage to the AI. Skipping silently is safer than propagating a malformed record through the pipeline.

---

## VALIDATION OUTPUT REFERENCE — EXACT OUTPUTS TO CHECK

- Item to check:
  `from ingestion.email_parser import parse_emails, ParsedEmail; print('import OK')`
  Expected output or result:
  `import OK`

- Item to check:
  `from ingestion.email_parser import ParsedEmail; print(list(ParsedEmail.__dataclass_fields__.keys()))`
  Expected output or result:
  `['subject', 'sender', 'date', 'body', 'links']`

- Item to check:
  HTML-only email smoke test assertion block
  Expected output or result:
  ```
  HTML-only smoke test PASSED
  sender: TLDR AI
  subject: AI Newsletter - March 25
  body preview: # OpenAI releases GPT-5
  links: [{'url': 'https://openai.com/gpt5', 'anchor_text': 'Read more'}]
  ```

- Item to check:
  Multipart email test assertion block
  Expected output or result:
  ```
  Multipart test PASSED
  body: OpenAI releases GPT-5. This is the plain text version.
  links: [{'url': 'https://openai.com', 'anchor_text': 'Read more'}]
  ```

- Item to check:
  Edge cases assertion block (empty list, missing Date, mailto filtering, no display name)
  Expected output or result:
  `Edge case tests PASSED`

- Item to check:
  `ingestion/email_parser.py` file exists at the correct path
  Expected output or result:
  File present at `ingestion/email_parser.py`

- Item to check:
  `ParsedEmail` has exactly 5 fields: `subject`, `sender`, `date`, `body`, `links`
  Expected output or result:
  Confirmed by Level 2 validation output

- Item to check:
  `parse_emails([])` returns `[]` without error
  Expected output or result:
  Confirmed by Level 5 edge cases test

- Item to check:
  HTML smoke test: pre-header span with `display:none` is stripped from body
  Expected output or result:
  `'Pre-header' not in e.body` assertion passes (confirmed by Level 3)

- Item to check:
  HTML smoke test: link `https://openai.com/gpt5` with anchor text `Read more` is in `links`
  Expected output or result:
  `e.links == [{'url': 'https://openai.com/gpt5', 'anchor_text': 'Read more'}]` assertion passes

- Item to check:
  Multipart test: plain text body is used (not HTML body)
  Expected output or result:
  `'plain text version' in e.body` assertion passes

- Item to check:
  Multipart test: links extracted from HTML part even when plain text body is used
  Expected output or result:
  `e.links == [{'url': 'https://openai.com', 'anchor_text': 'Read more'}]` assertion passes

- Item to check:
  Missing Date header → `date` field is `None`
  Expected output or result:
  `results[0].date is None` assertion passes (confirmed by Level 5)

- Item to check:
  `mailto:` links are excluded from `links` list
  Expected output or result:
  `all(l['url'] != 'mailto:foo@bar.com' for l in results[0].links)` assertion passes

- Item to check:
  Real (non-mailto) links are included in `links` list
  Expected output or result:
  `any(l['url'] == 'https://real.com' for l in results[0].links)` assertion passes

- Item to check:
  Missing From display name falls back to email address string
  Expected output or result:
  `results[0].sender == 'sender@example.com'` assertion passes (confirmed by Level 5)
