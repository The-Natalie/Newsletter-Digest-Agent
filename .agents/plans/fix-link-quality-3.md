# Feature: fix-link-quality-3 — Per-Section Link Extraction (Structural Fix)

The following plan should be complete, but validate codebase patterns and task sanity before implementing.

Pay special attention to existing constants, import statements, and dataclass field names.

## Feature Description

Replace the global link extraction + post-hoc anchor-text re-association approach with per-section link extraction performed before html2text conversion. By running html2text with `ignore_links=False`, each section's markdown output contains inline `[anchor](url)` syntax, allowing links to be extracted from the section they actually belong to. This eliminates the root cause of mismatched sources.

## User Story

As the pipeline, I want each story chunk to carry only the links that appeared in its own HTML section, so that source attribution is accurate and no story receives unrelated links from other sections of the same newsletter.

## Problem Statement

The current approach extracts all links globally from the full HTML email, then re-associates them with story chunks by substring-matching anchor text. This fails because:
1. Generic CTA anchor text ("read more") matches many unrelated chunks.
2. Links from sponsor blocks, navigation, and other newsletter sections bleed into story chunks.
3. There is no structural connection between a link and its originating HTML section after html2text conversion.

## Scope

- In scope: `email_parser.py`, `embedder.py`, `deduplicator.py`
- Out of scope: `digest_builder.py`, `ai/claude_client.py`, `api/`, `static/`, database layer, tests

## Solution Statement

Use html2text with `ignore_links=False` to emit markdown with inline `[anchor](url)` links. Split the markdown output at blank-line/HR boundaries into sections. For each section: extract links using regex, strip link syntax from the prose text, apply boilerplate filters, and attach the resulting links directly to the section. Move `_is_boilerplate_segment()` logic into `email_parser.py` so all section-level filtering happens in one place. Add a `sections: list[dict]` field to `ParsedEmail`. Update `_segment_email()` in `embedder.py` to consume `parsed_email.sections` when available. Drop sourceless story groups in `deduplicator.py` before they reach Claude.

## Feature Metadata

**Feature Type**: Refactor / Bug Fix
**Estimated Complexity**: Medium
**Primary Systems Affected**: `ingestion/email_parser.py`, `processing/embedder.py`, `processing/deduplicator.py`
**Dependencies**: None new — uses existing `re`, `html2text`, `BeautifulSoup4`
**Assumptions**: HTML emails are the primary case. Plain-text emails fall back to body splitting with `links=[]`.

---

## CONTEXT REFERENCES

### Relevant Codebase Files — READ BEFORE IMPLEMENTING

- `ingestion/email_parser.py` (full file) — current global link extraction; ParsedEmail dataclass; `_html_to_text()`, `_extract_links()`, `_strip_noise()`, `_is_boilerplate_link()`
- `processing/embedder.py` (full file) — current `_SPLIT_PATTERN`, `_BOILERPLATE_SEGMENT_SIGNALS`, `_is_boilerplate_segment()`, `_links_for_chunk()`, `_segment_email()`
- `processing/deduplicator.py` (full file) — `deduplicate()`, `_build_sources()`

### New Files to Create

None.

### Files to Modify

- `ingestion/email_parser.py`
- `processing/embedder.py`
- `processing/deduplicator.py`

### Patterns to Follow

**Section dict shape** (used in `ParsedEmail.sections` and consumed by `_segment_email()`):
```python
{"text": str, "links": list[dict]}
# text: clean prose (link syntax stripped), links: [{url, anchor_text}]
```

**Existing split regex** (in `embedder.py` line 19 — mirror this in `email_parser.py`):
```python
re.compile(r'\n{2,}|^\s*[-*_]{3,}\s*$', re.MULTILINE)
```

**Existing boilerplate segment signals** (in `embedder.py` lines 23–33 — move to `email_parser.py`, do not duplicate):
```python
_BOILERPLATE_SEGMENT_SIGNALS = (
    "sponsored by", "brought to you by", "presented by",
    "this newsletter is supported by", "this issue is sponsored",
    "our sponsor", "a word from our sponsor", "advertisement", "advertorial",
)
```

**Existing html2text usage** (`email_parser.py` `_html_to_text()`):
```python
h = html2text.HTML2Text()
h.ignore_links = True
h.ignore_images = True
h.body_width = 0
h.unicode_snob = True
return h.handle(html_str)
```

**Logging pattern** — use module-level `logger = logging.getLogger(__name__)` and `logger.debug()`/`logger.info()`/`logger.warning()`.

---

## IMPLEMENTATION PLAN

### Phase 1: email_parser.py — add per-section extraction

Add constants, helper functions, and `sections` field. Update `parse_emails()` to populate sections from HTML.

### Phase 2: embedder.py — consume sections, remove old helpers

Update `_segment_email()` to branch on `parsed_email.sections`. Remove `_BOILERPLATE_SEGMENT_SIGNALS`, `_is_boilerplate_segment()`, `_links_for_chunk()`.

### Phase 3: deduplicator.py — drop sourceless groups

In `deduplicate()`, skip groups where `sources == []` and log how many were dropped.

---

## STEP-BY-STEP TASKS

### TASK 1: UPDATE `ingestion/email_parser.py` — add imports and constants

- **ADD** `import re` at the top of the imports block (after `from __future__ import annotations`, before `import email`)
- **ADD** these constants after the existing `_BOILERPLATE_ANCHORS` block (before the `_is_boilerplate_link` function):

```python
_SECTION_SPLIT_PATTERN = re.compile(r'\n{2,}|^\s*[-*_]{3,}\s*$', re.MULTILINE)
_MIN_SECTION_CHARS = 50
_MD_LINK_RE = re.compile(r'\[([^\]]+)\]\((https?://[^\)]+)\)')

# Substrings that identify sponsor or shell segments — checked against lowercase text.
_BOILERPLATE_SEGMENT_SIGNALS = (
    "sponsored by",
    "brought to you by",
    "presented by",
    "this newsletter is supported by",
    "this issue is sponsored",
    "our sponsor",
    "a word from our sponsor",
    "advertisement",
    "advertorial",
)
```

- **VALIDATE**: `python -c "import ingestion.email_parser"`

### TASK 2: UPDATE `ingestion/email_parser.py` — add helper functions

- **ADD** these three functions after `_is_boilerplate_link()` and before `_get_body_parts()`:

```python
def _is_boilerplate_segment(text: str) -> bool:
    """Return True if this text segment is sponsor or shell content, not a news story."""
    text_lower = text.lower()
    return any(signal in text_lower for signal in _BOILERPLATE_SEGMENT_SIGNALS)


def _is_heading_only(text: str) -> bool:
    """Return True if text is just a markdown heading with no body content."""
    lines = [l for l in text.strip().splitlines() if l.strip()]
    if not lines:
        return True
    # All lines are markdown headings (start with #) or short enough to be a title
    return all(l.startswith('#') for l in lines) or (len(lines) == 1 and len(text.strip()) < 80)


def _extract_sections(html_text: str) -> list[dict]:
    """Convert HTML to per-section dicts with clean prose text and local links.

    Uses html2text with ignore_links=False to produce markdown with inline
    [anchor](url) syntax. Splits at blank-line/HR boundaries, merges heading-only
    sections with the following section, extracts per-section links, strips link
    syntax from prose, and applies boilerplate filters.

    Returns:
        List of dicts: {"text": str (clean prose), "links": list[dict]}
        Only sections that pass boilerplate and length filters are included.
    """
    h = html2text.HTML2Text()
    h.ignore_links = False   # keep [anchor](url) inline so links stay with their section
    h.ignore_images = True
    h.body_width = 0
    h.unicode_snob = True
    md_text = h.handle(html_text)

    raw_sections = _SECTION_SPLIT_PATTERN.split(md_text)

    # Merge heading-only sections with the next section
    merged: list[str] = []
    i = 0
    while i < len(raw_sections):
        sec = raw_sections[i].strip()
        if _is_heading_only(sec) and i + 1 < len(raw_sections):
            # Merge heading with next section
            merged.append(sec + "\n\n" + raw_sections[i + 1].strip())
            i += 2
        else:
            merged.append(sec)
            i += 1

    sections: list[dict] = []
    for sec in merged:
        sec = sec.strip()
        if not sec:
            continue

        # Extract links from inline markdown syntax
        links = []
        seen_urls: set[str] = set()
        for anchor, url in _MD_LINK_RE.findall(sec):
            if url not in seen_urls and not _is_boilerplate_link(url, anchor):
                seen_urls.add(url)
                links.append({"url": url, "anchor_text": anchor})

        # Strip markdown link syntax to get clean prose
        clean_text = _MD_LINK_RE.sub(r'\1', sec).strip()

        if len(clean_text) < _MIN_SECTION_CHARS:
            continue
        if _is_boilerplate_segment(clean_text):
            continue

        sections.append({"text": clean_text, "links": links})

    return sections
```

- **VALIDATE**: `python -c "import ingestion.email_parser"`

### TASK 3: UPDATE `ingestion/email_parser.py` — add `sections` field to `ParsedEmail`

- **UPDATE** the `ParsedEmail` dataclass to add `sections` field:

```python
@dataclass
class ParsedEmail:
    subject: str
    sender: str           # Display name from From header, or email address if no display name
    date: datetime | None # Parsed from Date header; None if missing or unparseable
    body: str             # Cleaned plain text; empty string if extraction failed
    links: list[dict] = field(default_factory=list)  # [{url, anchor_text}] — global, kept for fallback
    sections: list[dict] = field(default_factory=list)  # [{text, links}] — per-section, preferred
```

- **VALIDATE**: `python -c "from ingestion.email_parser import ParsedEmail; p = ParsedEmail('s','sender',None,'body'); print(p.sections)"`

### TASK 4: UPDATE `ingestion/email_parser.py` — populate `sections` in `parse_emails()`

The current flow in `parse_emails()` sets `body` and `links`. We need to also populate `sections` when HTML is available.

- **UPDATE** the HTML branch inside `parse_emails()` (the `elif html_text is not None:` block). After extracting links and converting to text, also call `_extract_sections()`:

Current code (lines ~182–186):
```python
        elif html_text is not None:
            soup = BeautifulSoup(html_text, "lxml")
            links = _extract_links(soup)   # extract BEFORE stripping
            _strip_noise(soup)
            body = _html_to_text(str(soup))
```

Replace with:
```python
        elif html_text is not None:
            soup = BeautifulSoup(html_text, "lxml")
            links = _extract_links(soup)   # extract BEFORE stripping (kept for fallback)
            _strip_noise(soup)
            body = _html_to_text(str(soup))
            try:
                sections = _extract_sections(html_text)
            except Exception:
                sections = []
```

- **ADD** the plain-text branch handling for sections. The `if plain_text is not None:` branch does not call `_extract_sections()` — plain-text emails get `sections=[]` (the default), which triggers the fallback in embedder.

- **UPDATE** the `results.append(ParsedEmail(...))` call to include `sections=sections`. The variable `sections` must be initialized to `[]` before the if/elif chain so it's always defined:

Find the block that starts with `links: list[dict] = []` and add `sections: list[dict] = []` right after it:
```python
        links: list[dict] = []
        sections: list[dict] = []
```

Then update the `results.append(...)` call:
```python
        results.append(
            ParsedEmail(
                subject=subject,
                sender=sender,
                date=date_parsed,
                body=body,
                links=links,
                sections=sections,
            )
        )
```

- **VALIDATE**: `python -c "import ingestion.email_parser; print('ok')"`

### TASK 5: UPDATE `processing/embedder.py` — remove old helpers

- **REMOVE** the `_BOILERPLATE_SEGMENT_SIGNALS` tuple (lines 23–33)
- **REMOVE** the `_is_boilerplate_segment()` function (lines 75–78)
- **REMOVE** the `_links_for_chunk()` function (lines 81–92)

These have moved to `email_parser.py`. Do not leave behind commented-out code.

- **VALIDATE**: `python -c "import processing.embedder"`

### TASK 6: UPDATE `processing/embedder.py` — update `_segment_email()` to use sections

Replace the current `_segment_email()` implementation with one that branches on `parsed_email.sections`:

```python
def _segment_email(parsed_email: ParsedEmail) -> list[StoryChunk]:
    """Split email body into story candidates.

    Preferred path: use pre-extracted sections from email_parser (HTML emails).
    Each section already has local links and boilerplate filtered out.

    Fallback path: split plain-text body at blank-line/HR boundaries with no links.
    """
    if parsed_email.sections:
        chunks = [
            StoryChunk(
                text=section["text"],
                sender=parsed_email.sender,
                links=section["links"],
            )
            for section in parsed_email.sections
            if len(section["text"]) >= _MIN_CHUNK_CHARS
        ]
        logger.debug(
            "Email from %s: used %d pre-extracted sections → %d chunks",
            parsed_email.sender, len(parsed_email.sections), len(chunks),
        )
        return chunks

    # Fallback: plain-text email — split body, no links available
    segments = _SPLIT_PATTERN.split(parsed_email.body)
    chunks = []
    for seg in segments:
        seg = seg.strip()
        if len(seg) >= _MIN_CHUNK_CHARS:
            chunks.append(StoryChunk(
                text=seg,
                sender=parsed_email.sender,
                links=[],
            ))
    logger.debug(
        "Email from %s: plain-text fallback → %d chunks",
        parsed_email.sender, len(chunks),
    )
    return chunks
```

- **VALIDATE**: `python -c "import processing.embedder"`

### TASK 7: UPDATE `processing/deduplicator.py` — drop sourceless groups

In `deduplicate()`, after building `sources`, skip groups where sources is empty.

Replace the loop body:
```python
    groups = []
    for cluster in clusters:
        if len(cluster) > 5:
            senders = [c.sender for c in cluster]
            logger.warning(
                "Large cluster (%d chunks from %s) — possible false positive merge",
                len(cluster),
                senders,
            )
        sources = _build_sources(cluster)
        groups.append(StoryGroup(chunks=cluster, sources=sources))
```

With:
```python
    groups = []
    sourceless_count = 0
    for cluster in clusters:
        if len(cluster) > 5:
            senders = [c.sender for c in cluster]
            logger.warning(
                "Large cluster (%d chunks from %s) — possible false positive merge",
                len(cluster),
                senders,
            )
        sources = _build_sources(cluster)
        if not sources:
            sourceless_count += 1
            continue
        groups.append(StoryGroup(chunks=cluster, sources=sources))

    if sourceless_count:
        logger.info("Dropped %d sourceless story group(s) (no valid links)", sourceless_count)
```

- **VALIDATE**: `python -c "import processing.deduplicator"`

### TASK 8: SMOKE TEST — run full import chain

```bash
python -c "
from ingestion.email_parser import parse_emails, ParsedEmail
from processing.embedder import embed_and_cluster
from processing.deduplicator import deduplicate
print('All imports OK')
"
```

---

## TESTING STRATEGY

### Manual Validation

Run the CLI pipeline with the same smaller date range used in previous test rounds:

```bash
python -m processing.digest_builder --folder "AI Newsletters" --start 2026-03-17 --end 2026-03-17
```

Expected improvements:
- Each digest entry's sources should contain links that appeared in that specific story section
- No "read more" / "click here" / "unsubscribe" links in sources
- No digest entries with `sources: []`
- Sponsor/advertorial sections should not appear as digest entries
- Story text and source links should be thematically consistent

### Unit-level checks (manual inspection)

```bash
python -c "
from ingestion.email_parser import _extract_sections
sample_html = '''<html><body>
<h2>AI Model Released</h2>
<p>Company X released a new model today with major new capabilities. <a href=\"https://example.com/story\">Read the announcement</a>.</p>
<hr/>
<p>Sponsored by Acme Corp. <a href=\"https://acme.com\">Visit us</a></p>
<hr/>
<h2>Another Story</h2>
<p>More news here about the latest developments in the industry. <a href=\"https://example.com/story2\">Details</a></p>
</body></html>'''
sections = _extract_sections(sample_html)
for i, s in enumerate(sections):
    print(f'Section {i}: {repr(s[\"text\"][:60])} | links={s[\"links\"]}')
"
```

Expected: 2 sections (sponsor section dropped), each with its own links only.

---

## VALIDATION COMMANDS

### Level 1: Import checks

```bash
python -c "import ingestion.email_parser; print('email_parser OK')"
python -c "import processing.embedder; print('embedder OK')"
python -c "import processing.deduplicator; print('deduplicator OK')"
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

### Level 3: Section extraction unit test

```bash
python -c "
from ingestion.email_parser import _extract_sections
sample_html = '<html><body><h2>AI Model Released</h2><p>Company X released a new model today with major new capabilities. <a href=\"https://example.com/story\">Read the announcement</a>.</p><hr/><p>Sponsored by Acme Corp. <a href=\"https://acme.com\">Visit us</a></p><hr/><h2>Another Story</h2><p>More news here about the latest developments in the industry. <a href=\"https://example.com/story2\">Details</a></p></body></html>'
sections = _extract_sections(sample_html)
assert len(sections) == 2, f'Expected 2 sections, got {len(sections)}: {sections}'
assert sections[0][\"links\"][0][\"url\"] == \"https://example.com/story\", f'Wrong link: {sections[0][\"links\"]}'
assert sections[1][\"links\"][0][\"url\"] == \"https://example.com/story2\", f'Wrong link: {sections[1][\"links\"]}'
print('Section extraction test PASSED')
"
```

### Level 4: ParsedEmail sections field

```bash
python -c "
from ingestion.email_parser import ParsedEmail
p = ParsedEmail('subject', 'sender', None, 'body')
assert hasattr(p, 'sections')
assert p.sections == []
print('ParsedEmail.sections field PASSED')
"
```

### Level 5: Removed symbols no longer importable from embedder

```bash
python -c "
import processing.embedder as e
assert not hasattr(e, '_BOILERPLATE_SEGMENT_SIGNALS'), 'Should be removed'
assert not hasattr(e, '_is_boilerplate_segment'), 'Should be removed'
assert not hasattr(e, '_links_for_chunk'), 'Should be removed'
print('Removed symbols check PASSED')
"
```

### Level 6: Manual pipeline run

```bash
python -m processing.digest_builder --folder "AI Newsletters" --start 2026-03-17 --end 2026-03-17
```

---

## MANUAL VERIFICATION CHECKLIST

- [ ] Each digest entry's sources contain links that match that entry's topic
- [ ] No unsubscribe / opt-out / manage preferences links in any sources
- [ ] No "read more" / "click here" / "learn more" links in any sources
- [ ] No digest entries with empty `sources` array
- [ ] No sponsor/advertorial content appears as a digest entry
- [ ] Story text and source URLs are thematically consistent

---

## ROLLBACK CONSIDERATIONS

All changes are isolated to three files. To revert: restore `email_parser.py` (remove `sections`, `_extract_sections`, new constants), restore `embedder.py` (re-add `_BOILERPLATE_SEGMENT_SIGNALS`, `_is_boilerplate_segment`, `_links_for_chunk`, old `_segment_email`), restore `deduplicator.py` (remove sourceless-drop logic).

---

## ACCEPTANCE CRITERIA

- [ ] `email_parser.py` populates `sections` for HTML emails using per-section link extraction
- [ ] `embedder.py` uses `parsed_email.sections` when available; falls back to plain-text splitting
- [ ] `embedder.py` no longer contains `_BOILERPLATE_SEGMENT_SIGNALS`, `_is_boilerplate_segment`, or `_links_for_chunk`
- [ ] `deduplicator.py` drops story groups with no valid sources before returning
- [ ] All Level 1–5 validation commands pass
- [ ] Manual pipeline run produces digest entries with topically consistent source links
- [ ] No empty `sources` arrays in digest output

---

## NOTES

- `_extract_sections()` receives the **original** `html_text` (before `_strip_noise()`), because we need the links before noise stripping. `_strip_noise()` + `_html_to_text()` still runs separately to produce `body` for the plain-text fallback path.
- The global `links` field on `ParsedEmail` is retained (populated as before) for potential future use, but `_segment_email()` no longer consumes it.
- `_is_heading_only()` handles the html2text behavior of emitting `## Headline\n\nBody paragraph` as two separate blank-line-split sections — merging keeps headline + body + links together.
- Sponsor sections are dropped at two levels: `_is_boilerplate_segment()` in `_extract_sections()` (before sections reach embedder), and the existing `_BOILERPLATE_SEGMENT_SIGNALS` check is removed from embedder since it's now redundant.

---

## VALIDATION OUTPUT REFERENCE — EXACT OUTPUTS TO CHECK

- Item to check:
  `python -c "import ingestion.email_parser; print('email_parser OK')"`
  Expected output or result:
  ```
  email_parser OK
  ```

- Item to check:
  `python -c "import processing.embedder; print('embedder OK')"`
  Expected output or result:
  ```
  embedder OK
  ```

- Item to check:
  `python -c "import processing.deduplicator; print('deduplicator OK')"`
  Expected output or result:
  ```
  deduplicator OK
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
  ```
  python -c "
  from ingestion.email_parser import _extract_sections
  sample_html = '<html><body><h2>AI Model Released</h2><p>Company X released a new model today with major new capabilities. <a href=\"https://example.com/story\">Read the announcement</a>.</p><hr/><p>Sponsored by Acme Corp. <a href=\"https://acme.com\">Visit us</a></p><hr/><h2>Another Story</h2><p>More news here about the latest developments in the industry. <a href=\"https://example.com/story2\">Details</a></p></body></html>'
  sections = _extract_sections(sample_html)
  assert len(sections) == 2, f'Expected 2 sections, got {len(sections)}: {sections}'
  assert sections[0]['links'][0]['url'] == 'https://example.com/story', f'Wrong link: {sections[0][\"links\"]}'
  assert sections[1]['links'][0]['url'] == 'https://example.com/story2', f'Wrong link: {sections[1][\"links\"]}'
  print('Section extraction test PASSED')
  "
  ```
  Expected output or result:
  ```
  Section extraction test PASSED
  ```

- Item to check:
  ```
  python -c "
  from ingestion.email_parser import ParsedEmail
  p = ParsedEmail('subject', 'sender', None, 'body')
  assert hasattr(p, 'sections')
  assert p.sections == []
  print('ParsedEmail.sections field PASSED')
  "
  ```
  Expected output or result:
  ```
  ParsedEmail.sections field PASSED
  ```

- Item to check:
  ```
  python -c "
  import processing.embedder as e
  assert not hasattr(e, '_BOILERPLATE_SEGMENT_SIGNALS'), 'Should be removed'
  assert not hasattr(e, '_is_boilerplate_segment'), 'Should be removed'
  assert not hasattr(e, '_links_for_chunk'), 'Should be removed'
  print('Removed symbols check PASSED')
  "
  ```
  Expected output or result:
  ```
  Removed symbols check PASSED
  ```

- Item to check:
  File `ingestion/email_parser.py` was modified to add `import re`, `_SECTION_SPLIT_PATTERN`, `_MIN_SECTION_CHARS`, `_MD_LINK_RE`, `_BOILERPLATE_SEGMENT_SIGNALS`, `_is_boilerplate_segment()`, `_is_heading_only()`, `_extract_sections()`, `sections` field on `ParsedEmail`, and `sections=sections` in `parse_emails()`.
  Expected output or result:
  File exists and all imports pass (confirmed by Level 1 and Level 2 checks above).

- Item to check:
  File `processing/embedder.py` was modified to remove `_BOILERPLATE_SEGMENT_SIGNALS`, `_is_boilerplate_segment()`, `_links_for_chunk()`, and replace `_segment_email()` with sections-first implementation.
  Expected output or result:
  File exists and removed symbols check passes (confirmed by Level 1 and Level 5 checks above).

- Item to check:
  File `processing/deduplicator.py` was modified to drop sourceless story groups before returning from `deduplicate()`.
  Expected output or result:
  File exists and import passes (confirmed by Level 1 check above).

- Item to check:
  Each digest entry's sources contain links that match that entry's topic (manual run: `python -m processing.digest_builder --folder "AI Newsletters" --start 2026-03-17 --end 2026-03-17`)
  Expected output or result:
  Every entry in the printed digest JSON has a non-empty `sources` array where each URL is topically related to the entry's headline and summary.

- Item to check:
  No unsubscribe / opt-out / manage preferences links in any sources (manual run: `python -m processing.digest_builder --folder "AI Newsletters" --start 2026-03-17 --end 2026-03-17`)
  Expected output or result:
  No source URL or anchor_text contains "unsubscribe", "opt-out", "opt out", or "manage preferences".

- Item to check:
  No "read more" / "click here" / "learn more" links in any sources (manual run: `python -m processing.digest_builder --folder "AI Newsletters" --start 2026-03-17 --end 2026-03-17`)
  Expected output or result:
  No source anchor_text is "read more", "click here", "learn more", or any other generic CTA from `_BOILERPLATE_ANCHORS`.

- Item to check:
  No digest entries with empty `sources` array (manual run: `python -m processing.digest_builder --folder "AI Newsletters" --start 2026-03-17 --end 2026-03-17`)
  Expected output or result:
  Every entry in the printed digest JSON has `"sources": [...]` with at least one item.

- Item to check:
  No sponsor/advertorial content appears as a digest entry (manual run: `python -m processing.digest_builder --folder "AI Newsletters" --start 2026-03-17 --end 2026-03-17`)
  Expected output or result:
  No entry headline or summary contains phrases like "sponsored by", "brought to you by", "presented by", or similar advertorial language.

- Item to check:
  Story text and source URLs are thematically consistent (manual run: `python -m processing.digest_builder --folder "AI Newsletters" --start 2026-03-17 --end 2026-03-17`)
  Expected output or result:
  For each entry, the source URLs visibly relate to the topic described in the entry's headline and summary — no links from unrelated stories appear in an entry's sources.
