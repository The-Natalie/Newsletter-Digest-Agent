# Feature: email-parser-story-records

The following plan should be complete, but validate codebase patterns and task sanity before implementing.

Pay special attention to the existing extraction helpers — most of them are correct and reusable. The scope of this plan is strictly `ingestion/email_parser.py` and its tests.

## Feature Description

Refactor `ingestion/email_parser.py` so that `parse_emails()` returns a flat list of `StoryRecord` objects — one per extracted story section — instead of `list[ParsedEmail]`. Each `StoryRecord` carries the fields the new pipeline needs: `title`, `body`, `link`, `newsletter`, and `date`.

**Phase 1 (implemented):** Structural refactor — StoryRecord dataclass, flattened parse_emails(), title/link extraction, date formatting, _MIN_SECTION_CHARS lowered to 20.

**Phase 2 (new):** Extraction quality filters — three targeted fixes revealed by real-email testing that allow structural noise to pass through Phase 1:

1. `_MD_LINK_RE` does not match empty-anchor image links `[](url)` (anchor is `[^\]]+`, requiring ≥1 char). These pass through unstripped, leaving raw link syntax in `body` text.
2. Email template table rows (`| | | | March 17, 2026 | Read online`) survive the `_MIN_SECTION_CHARS = 20` floor because they contain enough characters, but have no story content.
3. Table-of-contents / preview sections (numbered lists of article headline links with minimal prose between) are retained as story records even though they are navigation, not stories.

The fixes target these three root causes specifically. Short valid story items (one sentence, a few words + a link) must still be preserved — length is not a valid filter criterion.

## User Story

As the pipeline orchestrator (`digest_builder.py`),
I want `parse_emails()` to return a flat list of story records
So that downstream stages (embedder, deduplicator, LLM filter) receive individually addressable story items without needing to unpack per-email sections themselves.

## Problem Statement

**Phase 1 (resolved):** The old `ParsedEmail` dataclass bundled all sections from one email into a single object. The new pipeline requires a flat list of `{title, body, link, newsletter, date}` records. Additionally, `_MIN_SECTION_CHARS = 100` was dropping valid short stories.

**Phase 2 (new):** Real-email testing against `the_deep_view.eml` produced 49 records. Several categories of records are structural noise, not stories:

- **Table artifact records:** `body = '| | | |  March 17, 2026 | Read online'` — email template table rows surviving the 20-char floor.
- **Raw link syntax in body:** `body = '| [](https://long-tracking-url...)'` — empty-anchor image links (`[](url)`) not matched by `_MD_LINK_RE` (which requires `[^\]]+`, i.e. ≥1 anchor char), so the raw markdown syntax appears verbatim in body text.
- **ToC / preview sections:** Numbered lists of article headline links (`1. [GPT-5 is here](url)  2. [Nvidia GTC](url)...`) treated as story records despite containing no prose — they are navigation aids that duplicate the actual articles later in the email.
- **Newsletter intro sections:** Short greetings or "what's inside" intros with no story content.

## Scope

- **In scope:** `ingestion/email_parser.py` — Phase 2: fix `_MD_LINK_RE`, add `_is_table_artifact()`, add `_is_sparse_link_section()`, extend `_BOILERPLATE_SEGMENT_SIGNALS`. `tests/test_email_parser.py` — tests for Phase 2 filters.
- **Out of scope:** `processing/embedder.py` (downstream update — separate plan), `processing/deduplicator.py`, `processing/digest_builder.py`, any API or frontend changes. `_split_list_section` and boilerplate URL/anchor filters are not changed.

## Solution Statement

Three targeted changes to `_extract_sections()` and one regex fix:

1. **Fix `_MD_LINK_RE`:** Change anchor quantifier from `+` to `*` so `[](url)` is matched and stripped. Empty-anchor links produce `""` on substitution — their sections collapse to near-empty and are dropped by `_MIN_SECTION_CHARS = 20`.

2. **Add `_is_table_artifact(clean_text)`:** Returns True when pipe characters make up >15% of non-whitespace characters. Applied after `clean_text` is computed, before appending to sections.

3. **Add `_is_sparse_link_section(raw_sec, links)`:** Returns True when a section has ≥3 links and fewer than 30 non-marker prose characters outside all link syntax. Applied after links are extracted, to non-split sections only. This catches ToC and preview link lists without affecting valid story sections with multiple inline links.

4. **Extend `_BOILERPLATE_SEGMENT_SIGNALS`:** Add unambiguous newsletter-intro signals: `"in today's issue"`, `"in this issue"`, `"what's inside"`, `"today's top stories"`. These appear only in navigation/intro sections, not story bodies.

Short valid stories (one sentence + link, < 100 chars) remain unaffected — none of these filters use length as a criterion.

## Feature Metadata

**Feature Type:** Refactor
**Estimated Complexity:** Low
**Primary Systems Affected:** `ingestion/email_parser.py`, `tests/test_email_parser.py`
**Dependencies:** None new — html2text, BeautifulSoup4 already used
**Assumptions:**
- Phase 1 is fully implemented — `StoryRecord`, `parse_emails()`, `_extract_title`, `_select_link`, `_MIN_SECTION_CHARS = 20` are all in place
- Downstream callers (`embedder.py`) will be updated in a separate plan
- The 15% pipe-char ratio threshold catches email template table rows without affecting valid story text (which rarely contains `|` characters)
- The 30-char prose threshold for sparse link sections is conservative: real story sections with inline links always have more prose than this around the link

---

## CONTEXT REFERENCES

### Relevant Codebase Files — MUST READ BEFORE IMPLEMENTING

- `ingestion/email_parser.py` (full file) — current state post-Phase-1: `StoryRecord`, `parse_emails()`, `_extract_sections()`, `_split_list_section()`, `_MD_LINK_RE`, `_MIN_SECTION_CHARS = 20`, `_BOILERPLATE_SEGMENT_SIGNALS`
- `tests/test_email_parser.py` (full file) — Phase 1 tests in place; add Phase 2 tests without removing existing ones
- `CLAUDE.md` — logic filter rules, "never filter by length" constraint
- `PRD.md` §7 Feature 3 (Logic Filter) — what may and may not be dropped

### Files to Modify

- `ingestion/email_parser.py` — fix `_MD_LINK_RE`, add two filter functions, extend boilerplate signals, apply filters in `_extract_sections()`
- `tests/test_email_parser.py` — add Phase 2 filter tests

### New Files

None.

### Relevant Documentation

- html2text usage already established in file — no new docs needed
- BeautifulSoup already used — no new docs needed

### Patterns to Follow

**Dataclass pattern** (`ingestion/email_parser.py:209–216`):
```python
@dataclass
class ParsedEmail:
    subject: str
    sender: str
    date: datetime | None
    body: str
    links: list[dict] = field(default_factory=list)
    sections: list[dict] = field(default_factory=list)
```
Mirror this pattern for `StoryRecord` — same module, same imports (`dataclass`, `field`).

**Logging pattern** (throughout file):
```python
logger = logging.getLogger(__name__)
logger.warning("Short extraction (%d chars) for email from %s ...", len(body), sender)
```

**Date parsing** (`ingestion/email_parser.py:425–430`):
```python
date_parsed: datetime | None = None
date_str = msg.get("Date")
if date_str:
    try:
        date_parsed = email.utils.parsedate_to_datetime(date_str)
    except (TypeError, ValueError):
        pass
```
For the `StoryRecord.date` field, format this as: `date_parsed.strftime("%Y-%m-%d") if date_parsed else ""`

**Test helper pattern** (`tests/test_email_parser.py:14–22`):
```python
def _html(body: str) -> str:
    return f"<html><body>{body}</body></html>"
```
Add a `_make_raw_email()` helper for `parse_emails()` tests using `email.mime.text.MIMEText`.

**Section links shape** — `_extract_sections()` returns `[{"text": str, "links": [{"url": str, "anchor_text": str}]}]`. The `links` list is already boilerplate-filtered. `link` field on `StoryRecord` = `links[0]["url"]` if `links` else `None`.

---

## IMPLEMENTATION PLAN

### Phase 1: StoryRecord Dataclass ✅ COMPLETE

Replace `ParsedEmail` with `StoryRecord`. The new dataclass is exported from this module and will be imported by `embedder.py` in the next plan.

### Phase 2: Title Extraction Helper ✅ COMPLETE

Add `_extract_title(text: str) -> tuple[str | None, str]` that returns `(title, body_without_title)`. Detects `#`-prefixed first lines.

### Phase 3: Link Selection Helper ✅ COMPLETE

Add `_select_link(links: list[dict]) -> str | None` that returns the first URL from a section's already-filtered links list, or `None` if empty.

### Phase 4: parse_emails() Refactor ✅ COMPLETE

Rewrite `parse_emails()` to return `list[StoryRecord]`. Internal section extraction is unchanged.

### Phase 5: _MIN_SECTION_CHARS Adjustment ✅ COMPLETE

Lower from 100 to 20. Update the inline comment to explain why.

### Phase 6: Tests

Add tests for the new output shape to `tests/test_email_parser.py`.

---

## STEP-BY-STEP TASKS

### TASK 1 — UPDATE `_MIN_SECTION_CHARS` in `ingestion/email_parser.py`

- **IMPLEMENT:** Change `_MIN_SECTION_CHARS = 100` → `_MIN_SECTION_CHARS = 20`
- **IMPLEMENT:** Update the inline comment: `# Minimum chars to keep a section. Set low so short valid story items are preserved;\n# the LLM filter handles any remaining noise. Only truly empty/whitespace sections are dropped.`
- **GOTCHA:** Do NOT change `_MIN_LIST_ITEM_CHARS = 30` — bullet-item threshold stays.
- **VALIDATE:** `python -c "from ingestion.email_parser import _extract_sections; print('ok')"`

---

### TASK 2 — REPLACE `ParsedEmail` with `StoryRecord` in `ingestion/email_parser.py`

- **REMOVE:** The entire `ParsedEmail` dataclass (lines 209–216 in current file).
- **ADD:** New `StoryRecord` dataclass immediately after the `_is_heading_only` function and before `_split_list_section`:

```python
@dataclass
class StoryRecord:
    title: str | None    # first #-heading line, stripped of # markers; None if absent
    body: str            # section text without the title line; primary dedup signal
    link: str | None     # first non-boilerplate URL from the section; None if absent
    newsletter: str      # sender display name or email address
    date: str            # YYYY-MM-DD; empty string if email Date header missing/unparseable
```

- **IMPORTS:** `dataclass` and `field` are already imported — no new imports needed. Remove `field` from the import if `StoryRecord` doesn't use it (check if anything else uses `field`; `ParsedEmail` used it for `default_factory` — `StoryRecord` does not).
- **GOTCHA:** `field` is only used by `ParsedEmail`. Once `ParsedEmail` is removed, `field` can be removed from the `from dataclasses import dataclass, field` import. Change to `from dataclasses import dataclass`.
- **VALIDATE:** `python -c "from ingestion.email_parser import StoryRecord; print(StoryRecord.__dataclass_fields__.keys())"`

---

### TASK 3 — ADD `_extract_title()` helper in `ingestion/email_parser.py`

Add this function after the `StoryRecord` dataclass:

```python
def _extract_title(text: str) -> tuple[str | None, str]:
    """Extract a heading title from section text.

    If the first non-empty line begins with one or more '#' characters (markdown
    heading), it is treated as the title. Returns (title_text, body_without_title).
    Otherwise returns (None, original_text).

    The '#' markers and leading/trailing whitespace are stripped from the title.
    The returned body is the text after the title line with leading blank lines removed.
    """
    lines = text.split("\n")
    for i, line in enumerate(lines):
        stripped = line.strip()
        if not stripped:
            continue
        if stripped.startswith("#"):
            title = stripped.lstrip("#").strip()
            body = "\n".join(lines[i + 1:]).lstrip("\n").strip()
            return title or None, body
        # First non-empty line is not a heading
        break
    return None, text
```

- **GOTCHA:** `title or None` handles the case where the heading line is `# ` with no text.
- **VALIDATE:** `python -c "from ingestion.email_parser import _extract_title; print(_extract_title('# Hello\nBody text'))"`
  Expected: `('Hello', 'Body text')`

---

### TASK 4 — ADD `_select_link()` helper in `ingestion/email_parser.py`

Add immediately after `_extract_title()`:

```python
def _select_link(links: list[dict]) -> str | None:
    """Return the first URL from a section's filtered links list, or None if empty.

    The links list is already boilerplate-filtered by _extract_sections() — every
    entry is a non-boilerplate, non-social URL. The first entry is selected as the
    representative link for this story record.
    """
    return links[0]["url"] if links else None
```

- **VALIDATE:** `python -c "from ingestion.email_parser import _select_link; print(_select_link([{'url': 'https://example.com', 'anchor_text': 'x'}]))"`
  Expected: `https://example.com`

---

### TASK 5 — REWRITE `parse_emails()` in `ingestion/email_parser.py`

Replace the existing `parse_emails()` function entirely:

```python
def parse_emails(raw_messages: list[bytes]) -> list[StoryRecord]:
    """Parse raw MIME email bytes into a flat list of StoryRecord objects.

    Each record represents one story section extracted from one email. Sections are
    produced by _extract_sections() which handles HTML conversion, boilerplate filtering,
    and bullet-list splitting internally.

    Args:
        raw_messages: List of raw MIME email byte strings, as returned by fetch_emails().

    Returns:
        Flat list of StoryRecord instances. Emails with no extractable body or no
        sections are silently skipped. The list is ordered: all sections from the
        first email, then all sections from the second, etc.
    """
    results: list[StoryRecord] = []

    for raw in raw_messages:
        msg = email.message_from_bytes(raw, policy=policy.default)

        # Sender — prefer display name, fall back to email address
        display_name, addr = email.utils.parseaddr(msg.get("From", ""))
        newsletter = display_name.strip() if display_name.strip() else addr

        # Date — format as YYYY-MM-DD; empty string if header missing or unparseable
        date_str_raw = msg.get("Date")
        date_formatted = ""
        if date_str_raw:
            try:
                date_formatted = email.utils.parsedate_to_datetime(date_str_raw).strftime("%Y-%m-%d")
            except (TypeError, ValueError):
                pass

        # Body extraction
        plain_text, html_text = _get_body_parts(msg)

        sections: list[dict] = []

        if plain_text is not None:
            if html_text is not None:
                try:
                    sections = _extract_sections(html_text)
                except Exception:
                    sections = []
            # If no HTML, plain-text emails produce no sections — skipped
        elif html_text is not None:
            soup = BeautifulSoup(html_text, "lxml")
            _strip_noise(soup)
            # Log short extractions for debugging
            raw_body = _html_to_text(str(soup)).strip()
            if raw_body and len(raw_body) < 200:
                logger.warning(
                    "Short extraction (%d chars) for email from %s — possible parse failure",
                    len(raw_body),
                    newsletter,
                )
            if not raw_body:
                continue
            try:
                sections = _extract_sections(html_text)
            except Exception:
                sections = []
        else:
            continue  # no body at all

        for section in sections:
            section_text = section.get("text", "").strip()
            if not section_text:
                continue
            title, body = _extract_title(section_text)
            if not body.strip():
                body = section_text  # fallback: if body is empty after title strip, use full text
            link = _select_link(section.get("links", []))
            results.append(StoryRecord(
                title=title,
                body=body,
                link=link,
                newsletter=newsletter,
                date=date_formatted,
            ))

    return results
```

- **REMOVE:** The old `parse_emails()` completely (it returns `list[ParsedEmail]`).
- **GOTCHA:** `_get_body_parts`, `_strip_noise`, `_html_to_text`, `_extract_sections` are all kept unchanged.
- **GOTCHA:** The `subject` field is no longer extracted — it is not part of `StoryRecord`. Remove any subject-related code.
- **GOTCHA:** Plain-text-only emails have no HTML to pass through `_extract_sections()`, so they produce no story records and are skipped silently. This matches previous behavior where `text/html` is the default case.
- **VALIDATE:** `python -c "from ingestion.email_parser import parse_emails, StoryRecord; print('ok')"`

---

### TASK 6 — CLEAN UP UNUSED IMPORTS AND CODE in `ingestion/email_parser.py`

After the above changes:
- Remove `field` from `from dataclasses import dataclass, field` → `from dataclasses import dataclass`
- `datetime` import (`from datetime import datetime`) — still needed for `email.utils.parsedate_to_datetime` call inside `parse_emails()`. Keep it.
- Remove any remaining reference to `ParsedEmail` (search for `ParsedEmail` in the file).
- **VALIDATE:** `python -m py_compile ingestion/email_parser.py && echo "syntax ok"`

---

### TASK 7 — UPDATE `tests/test_email_parser.py`

Add a `_make_raw_email()` helper and new test cases for the `parse_emails()` output. **Do not remove or modify existing tests** — they all test `_extract_sections` and `_split_list_section` which are unchanged.

Add at the top of the file (after existing imports):
```python
import email as _email_stdlib
from email.mime.text import MIMEText
from email.mime.multipart import MIMEMultipart
from ingestion.email_parser import parse_emails, StoryRecord
```

Add helper after existing helpers:
```python
def _make_raw_email(
    html_body: str,
    sender: str = "Test Newsletter <test@example.com>",
    date: str = "Mon, 14 Mar 2026 10:00:00 +0000",
) -> bytes:
    """Build a minimal raw MIME email with an HTML body for parse_emails() tests."""
    msg = MIMEMultipart("alternative")
    msg["From"] = sender
    msg["Subject"] = "Test Issue"
    msg["Date"] = date
    msg.attach(MIMEText(html_body, "html"))
    return msg.as_bytes()
```

Add the following test functions:

```python
# ---------------------------------------------------------------------------
# parse_emails() — StoryRecord output shape tests
# ---------------------------------------------------------------------------

def test_parse_emails_returns_story_records():
    """parse_emails() returns a list of StoryRecord instances."""
    html = _html("<p>Google released a new AI model with improved reasoning capabilities this week.</p>")
    raw = _make_raw_email(html)
    records = parse_emails([raw])
    assert isinstance(records, list)
    assert all(isinstance(r, StoryRecord) for r in records)


def test_parse_emails_newsletter_field():
    """StoryRecord.newsletter is set from the From display name."""
    html = _html("<p>OpenAI announced a new API update with lower pricing for GPT-4o.</p>")
    raw = _make_raw_email(html, sender="TLDR AI <tldr@example.com>")
    records = parse_emails([raw])
    assert len(records) >= 1
    assert records[0].newsletter == "TLDR AI"


def test_parse_emails_date_field_format():
    """StoryRecord.date is formatted as YYYY-MM-DD."""
    html = _html("<p>Anthropic released Claude 3.7 Sonnet with extended thinking capability.</p>")
    raw = _make_raw_email(html, date="Fri, 14 Mar 2026 10:00:00 +0000")
    records = parse_emails([raw])
    assert len(records) >= 1
    assert records[0].date == "2026-03-14"


def test_parse_emails_title_extracted_from_heading():
    """StoryRecord.title is extracted from a markdown heading; body excludes the heading line."""
    html = _html(
        "<h2>New AI chip breaks benchmark records</h2>"
        "<p>Nvidia unveiled a new data-center GPU at GTC 2026 that outperforms the H100 on "
        "all major inference benchmarks by more than 40 percent.</p>"
    )
    raw = _make_raw_email(html)
    records = parse_emails([raw])
    assert len(records) >= 1
    r = records[0]
    assert r.title == "New AI chip breaks benchmark records"
    assert "New AI chip breaks benchmark records" not in r.body


def test_parse_emails_title_none_when_no_heading():
    """StoryRecord.title is None when the section has no markdown heading."""
    html = _html(
        "<p>Google DeepMind published Gemini 2.0 Ultra benchmarks showing SOTA on MMLU.</p>"
    )
    raw = _make_raw_email(html)
    records = parse_emails([raw])
    assert len(records) >= 1
    assert records[0].title is None


def test_parse_emails_link_extracted():
    """StoryRecord.link is the first content URL from the section."""
    html = _html(
        '<p>OpenAI cut API prices. <a href="https://openai.com/pricing">See pricing</a>.</p>'
    )
    raw = _make_raw_email(html)
    records = parse_emails([raw])
    assert len(records) >= 1
    assert records[0].link == "https://openai.com/pricing"


def test_parse_emails_link_none_when_no_link():
    """StoryRecord.link is None when the section contains no content URLs."""
    html = _html("<p>AI safety researchers published a new alignment paper this week.</p>")
    raw = _make_raw_email(html)
    records = parse_emails([raw])
    assert len(records) >= 1
    assert records[0].link is None


def test_parse_emails_short_item_preserved():
    """A one-sentence story item under 100 chars is NOT dropped (short items are valid)."""
    html = _html(
        '<p>GPT-5 is live. <a href="https://openai.com/gpt-5">Details here.</a></p>'
    )
    raw = _make_raw_email(html)
    records = parse_emails([raw])
    # Should produce at least one record — short valid items must not be dropped
    assert len(records) >= 1


def test_parse_emails_empty_email_skipped():
    """An email with no extractable body produces no story records."""
    msg = MIMEMultipart("alternative")
    msg["From"] = "Newsletter <test@example.com>"
    msg["Subject"] = "Empty"
    msg["Date"] = "Mon, 14 Mar 2026 10:00:00 +0000"
    # No body attached
    records = parse_emails([msg.as_bytes()])
    assert records == []


def test_parse_emails_multiple_emails_flat_list():
    """Two emails each producing one section → flat list of 2 StoryRecord objects."""
    html1 = _html("<p>Google launched a new search AI feature with visual understanding.</p>")
    html2 = _html("<p>Meta released Llama 4, a 400-billion parameter open-weights model.</p>")
    raw1 = _make_raw_email(html1, sender="Newsletter A <a@example.com>")
    raw2 = _make_raw_email(html2, sender="Newsletter B <b@example.com>")
    records = parse_emails([raw1, raw2])
    newsletters = [r.newsletter for r in records]
    assert "Newsletter A" in newsletters
    assert "Newsletter B" in newsletters
```

- **VALIDATE:** `python -m pytest tests/test_email_parser.py -v`

---

## PHASE 2 TASKS — Extraction Quality Filters

> Tasks 1–7 above are complete. Tasks 8–11 below address extraction quality issues found in real-email testing.

---

### TASK 8 — FIX `_MD_LINK_RE` to match empty-anchor image links

**Root cause:** `_MD_LINK_RE = re.compile(r'\[([^\]]+)\]\((https?://[^\)]+)\)')` uses `[^\]]+` (one or more chars) for the anchor group, so `[](url)` (empty anchor, used for images) is not matched. Raw link syntax appears verbatim in `body` text.

- **UPDATE** `ingestion/email_parser.py` — change `_MD_LINK_RE`:

```python
# Before:
_MD_LINK_RE = re.compile(r'\[([^\]]+)\]\((https?://[^\)]+)\)')

# After:
_MD_LINK_RE = re.compile(r'\[([^\]]*)\]\((https?://[^\)]+)\)')
#                                   ^ changed + to * (zero or more anchor chars)
```

- **GOTCHA:** `_MD_LINK_RE` is also used in `_split_list_section` to extract links per list item. After this change, `[](url)` entries will appear in `findall()` results with `anchor=''`. Skip zero-length anchors when building the `best_by_norm` dict in both `_extract_sections()` and `_split_list_section()`:

```python
for anchor, url in _MD_LINK_RE.findall(sec):
    if not anchor:          # skip empty-anchor image links
        continue
    if _is_boilerplate_url(url):
        continue
    # ... rest of dedup logic
```

Apply this `if not anchor: continue` guard in both places where `_MD_LINK_RE.findall` is called.

- **EFFECT:** Empty-anchor links are stripped from `clean_text` (substitution produces `''`). Sections that consist mostly of image links now collapse to near-empty text and are dropped by `_MIN_SECTION_CHARS = 20`.
- **VALIDATE:** `python -m py_compile ingestion/email_parser.py && echo "syntax ok"`

---

### TASK 9 — ADD `_is_table_artifact(clean_text: str) -> bool`

**Root cause:** Email template table rows like `| | | |  March 17, 2026 | Read online` survive the 20-char floor because they contain enough characters. These are layout elements, not story content.

- **ADD** to `ingestion/email_parser.py`, after `_is_boilerplate_segment()`:

```python
def _is_table_artifact(clean_text: str) -> bool:
    """Return True if text is a formatting artifact rather than story content.

    Detects email template table rows where pipe characters dominate — e.g.
    '| | | | March 17, 2026 | Read online'. These are layout elements that
    survive the _MIN_SECTION_CHARS floor but contain no story content.

    Threshold: pipe chars > 15% of all non-whitespace characters.
    """
    non_ws = re.sub(r'\s', '', clean_text)
    if not non_ws:
        return True
    return non_ws.count('|') / len(non_ws) > 0.15
```

- **ADD** the filter call inside `_extract_sections()`, immediately after `clean_text` is computed and before `_is_boilerplate_segment()`:

```python
clean_text = _MD_LINK_RE.sub(r'\1', sec).strip()

if len(clean_text) < _MIN_SECTION_CHARS:
    continue
if _is_table_artifact(clean_text):      # NEW — drop table/layout fragments
    continue
if _is_boilerplate_segment(clean_text):
    continue
```

- **GOTCHA:** Do NOT apply `_is_table_artifact` to list items from `_split_list_section` — those have already been filtered by `_MIN_LIST_ITEM_CHARS` and contain real prose.
- **VALIDATE:** `python -m py_compile ingestion/email_parser.py && echo "syntax ok"`

---

### TASK 10 — ADD `_is_sparse_link_section(raw_sec: str, links: list[dict]) -> bool`

**Root cause:** Table-of-contents and preview sections consist almost entirely of link anchors (headline titles) with no surrounding prose. They have ≥3 links but the text outside the link syntax is just list markers (`1.`, `2.`, `-`).

- **ADD** to `ingestion/email_parser.py`, after `_is_table_artifact()`:

```python
_SPARSE_LINK_STRIP_RE = re.compile(r'\[([^\]]*)\]\([^\)]+\)|[\d\.\-\*\#\:\s]')

def _is_sparse_link_section(raw_sec: str, links: list[dict]) -> bool:
    """Return True if this section is a link list (ToC, preview) with minimal prose.

    Detects sections where the text outside link syntax consists only of list
    markers and whitespace — i.e. the section IS the links, with no prose around
    them. Requires at least 3 links to avoid false-positives on short story items
    that happen to have minimal surrounding text.

    Does not affect story sections with inline links — those always have
    substantial prose outside the link anchors.
    """
    if len(links) < 3:
        return False
    # Strip all link syntax (including empty anchors) and list markers/whitespace
    bare = _SPARSE_LINK_STRIP_RE.sub('', raw_sec)
    return len(bare) < 30
```

- **ADD** the filter call inside `_extract_sections()`, after `links` is built and before `clean_text` is computed:

```python
links = list(best_by_norm.values())

if _is_sparse_link_section(sec, links):   # NEW — drop ToC / preview link lists
    continue

clean_text = _MD_LINK_RE.sub(r'\1', sec).strip()
```

- **GOTCHA:** This filter must run on `sec` (raw markdown with link syntax intact), not `clean_text`. Applying it after `_split_list_section` means it only catches non-split sections — correct, since `_split_list_section` already handles multi-item sections that qualify as separate stories.
- **VALIDATE:** `python -m py_compile ingestion/email_parser.py && echo "syntax ok"`

---

### TASK 11 — EXTEND `_BOILERPLATE_SEGMENT_SIGNALS` with intro signals

**Root cause:** Newsletter intro sections containing phrases like "In today's issue:" are not currently matched by any boilerplate signal.

- **UPDATE** `_BOILERPLATE_SEGMENT_SIGNALS` in `ingestion/email_parser.py` — add to the existing tuple:

```python
# Newsletter intro / table-of-contents headers
"in today's issue",
"in this issue",
"what's inside",
"today's top stories",
```

- **PLACEMENT:** Add these after the `# Navigation / sharing infrastructure` block.
- **RATIONALE:** These phrases appear only in navigation/intro headers, never in actual story bodies. They are conservative additions — each phrase is unambiguous enough that false positive risk is negligible.
- **GOTCHA:** Do NOT add "welcome back" — it appears in sections where a greeting prefix is followed by real story content (e.g. "Welcome back. Nvidia announced..."). The greeting prefix does not disqualify the section.
- **VALIDATE:** `python -m py_compile ingestion/email_parser.py && echo "syntax ok"`

---

### TASK 12 — ADD Phase 2 tests to `tests/test_email_parser.py`

Add the following tests after the existing Phase 1 tests. Do not remove or modify anything already there.

```python
# ---------------------------------------------------------------------------
# Phase 2: Extraction quality filter tests
# ---------------------------------------------------------------------------

def test_table_artifact_dropped():
    """A section consisting mainly of pipe characters is dropped as a table artifact."""
    from ingestion.email_parser import _is_table_artifact
    assert _is_table_artifact("| | | |  March 17, 2026  | Read online")
    assert not _is_table_artifact("Nvidia announced new robotics platforms at GTC 2026.")


def test_empty_anchor_link_stripped_from_body():
    """An image link [](url) does not appear as raw syntax in StoryRecord.body."""
    html = _html(
        '<img src="https://example.com/img.png" alt="">'  # becomes [](url) in markdown
        '<p>OpenAI cut API prices for all GPT-4o users starting this month.</p>'
    )
    raw = _make_raw_email(html)
    records = parse_emails([raw])
    for r in records:
        assert "[](https://" not in r.body, (
            f"Raw empty-anchor link syntax found in body: {r.body[:100]}"
        )


def test_toc_section_dropped():
    """A numbered list of headline links with no prose is dropped as a ToC section."""
    html = _html(
        "<ol>"
        "<li><a href='https://example.com/story-1'>GPT-5 launches with multimodal reasoning</a></li>"
        "<li><a href='https://example.com/story-2'>Nvidia unveils Blackwell Ultra GPU chip</a></li>"
        "<li><a href='https://example.com/story-3'>Meta releases Llama 4 open weights model</a></li>"
        "</ol>"
    )
    raw = _make_raw_email(html)
    records = parse_emails([raw])
    # The ToC section (3 links, no prose) should not produce records
    # Any record that IS produced must have meaningful prose beyond just headline text
    for r in records:
        # If any record was emitted, it must have substantial body prose
        prose_words = len(r.body.split())
        assert prose_words >= 6, (
            f"ToC-like section produced a sparse record ({prose_words} words): {r.body[:100]}"
        )


def test_story_with_multiple_inline_links_not_dropped():
    """A story section with 3+ inline links and substantial prose is NOT dropped as a ToC."""
    html = _html(
        "<p>Nvidia announced the <a href='https://nvidia.com/blackwell'>Blackwell Ultra</a> GPU at GTC. "
        "The new chip offers <a href='https://nvidia.com/perf'>40% better inference performance</a> than H100. "
        "It will be available from <a href='https://nvidia.com/partners'>certified partners</a> in Q3 2026.</p>"
    )
    raw = _make_raw_email(html)
    records = parse_emails([raw])
    assert len(records) >= 1, "Story section with multiple inline links must not be dropped"
    assert any("Nvidia" in r.body or "Blackwell" in r.body for r in records)


def test_intro_signal_section_dropped():
    """A section containing 'in today's issue' with no story content is dropped."""
    html = _html(
        "<p>In today's issue: AI funding, chip announcements, and open-source releases.</p>"
    )
    raw = _make_raw_email(html)
    records = parse_emails([raw])
    # This is a navigation/preview intro — should not appear as a story record
    intro_records = [r for r in records if "in today" in r.body.lower()]
    assert intro_records == [], (
        f"Intro section produced {len(intro_records)} record(s): {[r.body[:80] for r in intro_records]}"
    )


def test_short_valid_story_still_preserved_after_phase2():
    """Phase 2 filters do not drop short valid story items."""
    html = _html(
        '<p>GPT-5 is live. <a href="https://openai.com/gpt-5">Details here.</a></p>'
    )
    raw = _make_raw_email(html)
    records = parse_emails([raw])
    assert len(records) >= 1, "Short valid story must not be dropped by Phase 2 filters"
```

- **VALIDATE:** `python -m pytest tests/test_email_parser.py -v`

---

## TESTING STRATEGY

### Unit Tests (new additions)

Test each `StoryRecord` field independently against minimal synthetic HTML. Use `_make_raw_email()` to build valid MIME bytes. Do not mock — test against the real parsing pipeline.

### Existing Tests (must continue to pass)

All existing `_extract_sections` and `_split_list_section` tests are unchanged. Run them alongside new tests. These cover: list splitting, link non-contamination, sponsor section handling, paragraph pass-through.

### Edge Cases

- Empty email (no body) → empty list, no crash
- Email with HTML body but no story sections (all filtered) → empty list
- Email with missing Date header → `date` field is empty string `""`
- Section whose entire text is a single `#` heading with no body → `body = full_text` fallback applies
- Section with only boilerplate links → `link = None`
- Short story (under 100 chars) → must produce a record (critical regression test)

---

## VALIDATION COMMANDS

### Level 1: Syntax

```bash
python -m py_compile ingestion/email_parser.py && echo "syntax ok"
```

### Level 2: Unit Tests

```bash
python -m pytest tests/test_email_parser.py -v
```

Expected: all existing tests pass + all new tests pass.

### Level 3: Smoke Test

```bash
python -c "
from ingestion.email_parser import StoryRecord, parse_emails, _extract_title, _select_link
print('StoryRecord fields:', list(StoryRecord.__dataclass_fields__.keys()))
title, body = _extract_title('# My Headline\nBody text here.')
print('title:', title, '| body:', body)
link = _select_link([{'url': 'https://example.com', 'anchor_text': 'x'}])
print('link:', link)
print('All imports ok')
"
```

Expected output:
```
StoryRecord fields: ['title', 'body', 'link', 'newsletter', 'date']
title: My Headline | body: Body text here.
link: https://example.com
All imports ok
```

### Level 4: Manual — Real Email

```bash
python -c "
import sys
sys.path.insert(0, '.')
from ingestion.email_parser import parse_emails
with open('debug_samples/the_deep_view.eml', 'rb') as f:
    raw = f.read()
records = parse_emails([raw])
print(f'Total story records: {len(records)}')
for i, r in enumerate(records[:5], 1):
    print(f'  [{i}] title={r.title!r}  date={r.date}  link={r.link}')
    print(f'       body preview: {r.body[:80]!r}')
"
```

Expected: 10+ records, each with newsletter set, date as `YYYY-MM-DD`, title either a string or None, link either a URL or None.

---

## MANUAL VERIFICATION CHECKLIST

- [ ] `StoryRecord` is importable from `ingestion.email_parser`
- [ ] `ParsedEmail` no longer exists in `ingestion/email_parser.py`
- [ ] `parse_emails()` return type is `list[StoryRecord]`
- [ ] `_MIN_SECTION_CHARS` is set to `20` (not `100`)
- [ ] A one-sentence story item under 100 chars produces a `StoryRecord` (not dropped)
- [ ] `StoryRecord.title` is `None` for sections with no `#` heading
- [ ] `StoryRecord.title` contains the heading text (without `#`) when heading is present
- [ ] `StoryRecord.date` is formatted as `YYYY-MM-DD`
- [ ] `StoryRecord.link` is `None` when section has no content URLs
- [ ] All existing `_extract_sections` and `_split_list_section` tests still pass
- [ ] All new `parse_emails()` tests pass

## ROLLBACK CONSIDERATIONS

All changes are in a single file (`ingestion/email_parser.py`). Git revert restores the file. No database migrations, no config changes. Downstream callers (`embedder.py`) will fail with a type error until updated in the next plan — this is expected.

## ACCEPTANCE CRITERIA

- [ ] `StoryRecord` dataclass defined with fields: `title: str | None`, `body: str`, `link: str | None`, `newsletter: str`, `date: str`
- [ ] `parse_emails()` returns `list[StoryRecord]` (flat — sections expanded, not per-email)
- [ ] `_extract_title()` correctly identifies `#`-prefixed first lines as titles
- [ ] `_select_link()` returns first URL or None
- [ ] `_MIN_SECTION_CHARS = 20`
- [ ] All new tests pass; all existing tests pass
- [ ] Syntax check passes

---

## COMPLETION CHECKLIST

- [ ] All tasks completed in order
- [ ] `python -m py_compile ingestion/email_parser.py` passes
- [ ] `python -m pytest tests/test_email_parser.py -v` — all tests pass
- [ ] Smoke test output matches expected
- [ ] Manual real-email test produces 10+ records with correct field shapes
- [ ] `ParsedEmail` not found anywhere in `ingestion/email_parser.py`
- [ ] `_MIN_SECTION_CHARS = 20` confirmed in file

---

## NOTES

**Downstream dependency:** After this plan, `processing/embedder.py` imports `ParsedEmail` and accepts `list[ParsedEmail]`. It will fail with an `ImportError` until updated in the next plan to import `StoryRecord` and accept `list[StoryRecord]`. This is expected and acceptable — the pipeline is being rewritten stage by stage.

**Plain-text-only emails:** The existing behavior is preserved — `text/plain` emails without an HTML part produce no sections because `_extract_sections()` operates on HTML. Plain-text emails are rare for newsletters; this is an acceptable MVP limitation.

**`_BOILERPLATE_SEGMENT_SIGNALS` and the logic filter:** The existing `_is_boilerplate_segment()` function is the logic filter described in PRD §7 Feature 3. It is called inside `_extract_sections()` and is not changed. `_MIN_SECTION_CHARS` lowering is the only change to filtering behavior in this plan.

**`field` import removal:** `ParsedEmail` used `field(default_factory=list)` for its list fields. `StoryRecord` does not use `field`. Once `ParsedEmail` is removed, confirm no other usage of `field` exists before removing the import.

**VALIDATION OUTPUT REFERENCE — EXACT OUTPUTS TO CHECK**

- Item to check:
  `python -m py_compile ingestion/email_parser.py && echo "syntax ok"`
  Expected output or result:
  `syntax ok`

- Item to check:
  `python -m pytest tests/test_email_parser.py -v`
  Expected output or result:
  All existing tests (7 `_split_list_section` tests + 4 `_extract_sections` tests) PASSED, all new tests (10 `parse_emails` tests) PASSED. Zero failures, zero errors.

- Item to check:
  ```
  python -c "
  from ingestion.email_parser import StoryRecord, parse_emails, _extract_title, _select_link
  print('StoryRecord fields:', list(StoryRecord.__dataclass_fields__.keys()))
  title, body = _extract_title('# My Headline\nBody text here.')
  print('title:', title, '| body:', body)
  link = _select_link([{'url': 'https://example.com', 'anchor_text': 'x'}])
  print('link:', link)
  print('All imports ok')
  "
  ```
  Expected output or result:
  ```
  StoryRecord fields: ['title', 'body', 'link', 'newsletter', 'date']
  title: My Headline | body: Body text here.
  link: https://example.com
  All imports ok
  ```

- Item to check:
  Manual real-email test — 10+ records with correct field shapes
  Expected output or result:
  `Total story records: N` (N ≥ 10), followed by 5 records each showing `title=` (string or None), `date=YYYY-MM-DD`, `link=` (URL or None), `body preview=` non-empty string.

- Item to check:
  `ParsedEmail` no longer exists in `ingestion/email_parser.py`
  Expected output or result:
  `grep -n "ParsedEmail" ingestion/email_parser.py` returns no output.

- Item to check:
  `_MIN_SECTION_CHARS` is set to 20
  Expected output or result:
  `grep "_MIN_SECTION_CHARS" ingestion/email_parser.py` shows `_MIN_SECTION_CHARS = 20`
