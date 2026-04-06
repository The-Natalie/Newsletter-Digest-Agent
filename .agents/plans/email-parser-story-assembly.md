# Feature: email-parser-story-assembly

The following plan should be complete, but validate codebase patterns and task sanity before implementing.

Read all files in CONTEXT REFERENCES before making any changes. The implementation touches four files and must be done in strict task order — the schema change propagates downstream.

## Feature Description

Phase 4 improvements to `ingestion/email_parser.py` addressing eight categories of issues discovered in real-email testing against `the_deep_view.eml` (40 records) and `tldr_sample.eml` (23 records).

**Previously implemented phases (all complete, do not re-implement):**
- Phase 1: `StoryRecord` dataclass, `parse_emails()` refactor, `_MIN_SECTION_CHARS = 20`
- Phase 2: `_MD_LINK_RE` fix, `_is_table_artifact()`, `_is_sparse_link_section()`, boilerplate signal extensions
- Phase 3: Post-title body artifact filter in `parse_emails()` (body=`|` after title extraction)

**Phase 4 (this plan):** Story reassembly, leading/trailing pipe stripping, bold-title detection, `\xa0` normalization, new boilerplate signals, schema changes (`links: list[str]`, `source_count: int`), and downstream deduplicator update.

## User Story

As the pipeline orchestrator (`digest_builder.py`),
I want `parse_emails()` to return fully assembled story-level records with all relevant links
So that downstream stages (embedder, deduplicator, LLM filter) receive one record per logical story — not one record per paragraph — and can preserve all source links for the user interface.

## Problem Statement

### Issue 1 — Story fragmentation (The Deep View)

HTML structure: TDV uses `<h1>` per story; paragraphs are in separate `<tr>` rows. `html2text` renders `<tr>` boundaries as `---` in markdown, which `_SECTION_SPLIT_PATTERN` splits on. The current heading-merge only takes the first paragraph after a heading; subsequent paragraphs become separate records.

Example: story "Nvidia builds the tech stack for the robotics era" produces records [2], [3], [5] (plus IREN sponsor [4] between them). After sponsor filtering, [2] and [3] should be one record.

### Issue 2 — Missing story titles

- TDV: `_extract_title()` correctly detects `# heading` → title, but only on the heading+first-para merged section. Continuation records have `title=None`.
- TLDR: story titles are `[ **Title (N min read)** ](url)` — a linked bold title. After link stripping, this becomes `**Title (N min read)**`. `_extract_title()` only recognizes `#` headings, not bold-title patterns.
- Result: ~38 of 40 TDV records have `title=None`.

### Issue 3 — Trailing `|` artifact in body text

~15 records end with `\n|` (table-row-end artifact from email HTML layout). The Phase 3 fix drops `body='|'` but does NOT catch `body='Real content...\n|'` because the pipe ratio is <15%.

Examples: records [3], [5], [9], [10], [15], [34], [35], [37], [38].

### Issue 4 — `| LABEL` structural artifacts as records

Sections that are section/sponsor labels with a leading `|` prefix pass all current filters:
- `'| TOGETHER WITH AIRIA'` (record [6])
- `'| TOGETHER WITH SLACK'` (record [11])
- `'| A QUICK POLL BEFORE YOU GO'` (record [31])
- `'| HARDWARE'`, `'| BIG TECH'` (section category labels)

### Issue 5 — Missing boilerplate signals

Phrases present in real emails but not in `_BOILERPLATE_SEGMENT_SIGNALS`:
- `"in today's newsletter"` (ToC header; current signals have `"in today's issue"` but not `"newsletter"`)
- `"thanks for reading"` (record [34] outro)
- `"before you go"` (poll header)
- `"together with"` (sponsor connector label)
- `"brought to you by"` (sponsor label — in `_BOILERPLATE_ANCHORS` but NOT in segment signals)
- `"a quick poll"` (poll section header)

### Issue 6 — `\xa0` in body text

Non-breaking spaces appear in records [4], [7], [12], [30], [32]. Should be normalized to regular space before storing.

### Issue 7 — Single link is too lossy

Current: `link: str | None` preserves only the first link from each section. A story with 3 relevant links loses 2. Request: preserve ALL non-boilerplate links as `links: list[str]`.

### Issue 8 — No source multiplicity signal

After deduplication, there is no way to tell if a story appeared in 1 newsletter or 5. Request: add `source_count: int` field (set to 1 by `parse_emails()`; updated to cluster size by `deduplicate()`). The UI will display a "N sources" indicator for stories with `source_count > 1`.

## Scope

**In scope (this plan):**
- `ingestion/email_parser.py` — story reassembly, pipe stripping, bold-title detection, `\xa0` normalization, new signals, schema changes
- `processing/deduplicator.py` — update for new `links`/`source_count` schema
- `tests/test_email_parser.py` — update for schema + new feature tests
- `tests/test_deduplicator.py` — update for schema change

**Out of scope / deferred:**
- `processing/digest_builder.py` — separate plan (full pipeline rewrite)
- `ai/claude_client.py` — separate plan (binary LLM filter rewrite)
- API routes, frontend — downstream of digest_builder
- Poll content filtering beyond new signals (LLM filter handles edge cases)
- Reader quote fragment filtering (LLM filter handles)

## Feature Metadata

**Feature Type:** Enhancement / Refactor
**Estimated Complexity:** High (story reassembly algorithm + schema change)
**Primary Systems Affected:** `ingestion/email_parser.py`, `processing/deduplicator.py`
**Dependencies:** None new
**Assumptions:**
- TDV-style newsletters use bare `# heading` (no `**`) for story titles
- TLDR-style newsletters use `# **Category**` (with `**`) for section headers and `**Title**` for story titles
- The `---` separators in html2text output (from table borders) will continue to separate paragraphs; the new algorithm handles this correctly
- After sponsor filtering breaks a story, continuation paragraphs become standalone records — this is acceptable (LLM filter and semantic dedup handle further merging)

---

## CONTEXT REFERENCES

### Relevant Codebase Files — MUST READ BEFORE IMPLEMENTING

- `ingestion/email_parser.py` (full file) — current state after Phases 1–3. Key areas:
  - Lines 80–85: `_SECTION_SPLIT_PATTERN`, `_MIN_SECTION_CHARS`, `_MD_LINK_RE`
  - Lines 121–143: `_BOILERPLATE_SEGMENT_SIGNALS`
  - Lines 230–263: `_is_table_artifact()`, `_SPARSE_LINK_STRIP_RE`, `_is_sparse_link_section()`
  - Lines 266–277: `_is_heading_only()`
  - Lines 280–311: `_extract_title()`, `_select_link()`
  - Lines 363–445: `_extract_sections()` — the heading-merge loop is here (lines 384–395)
  - Lines 487–568: `parse_emails()` — the section processing loop (lines 552–566)
- `processing/deduplicator.py` (full file) — `select_representative()` uses `r.link is not None` as a tiebreaker key
- `tests/test_email_parser.py` — existing 36 tests; many check `r.link`
- `tests/test_deduplicator.py` — existing 17 tests; `_record()` helper uses `link=None` or `link="url"`
- `CLAUDE.md` — "Never filter by body length" rule must be respected throughout

### New Files to Create

None.

### Real-Email Evidence Files

- `debug_samples/the_deep_view.eml` — used for Level 4 real-email validation
- `debug_samples/tldr_sample.eml` — used for Level 5 real-email validation
- `tests/test-results/deep_view_records-Apr-3-2026-3-39pm.txt` — full 40-record output showing all issues

### Patterns to Follow

**Dataclass default for list field** (`ingestion/email_parser.py` — add `field` import back):
```python
from dataclasses import dataclass, field

@dataclass
class StoryRecord:
    links: list[str] = field(default_factory=list)
    source_count: int = 1
```

**Regex on body text** (follow existing pattern in file):
```python
body = re.sub(r'[\n\s]*\|[\n\s]*$', '', body).strip()
```

**`_BOILERPLATE_SEGMENT_SIGNALS` — add to existing tuple** (lines 121–143):
```python
# New signals go after existing entries
"together with",
"brought to you by",
"in today's newsletter",
"thanks for reading",
"before you go",
"a quick poll",
```

---

## STEP-BY-STEP TASKS

IMPORTANT: Execute every task in order. Each task is atomic and independently validatable.

---

### TASK 1 — ADD new `_BOILERPLATE_SEGMENT_SIGNALS` entries in `ingestion/email_parser.py`

- **UPDATE** `_BOILERPLATE_SEGMENT_SIGNALS` — add the following entries to the end of the existing tuple, before the closing `)`

```python
    # Sponsor / partner labels
    "together with",
    "brought to you by",
    # Newsletter outro / sign-off
    "in today's newsletter",
    "thanks for reading",
    # Poll / interactive sections
    "before you go",
    "a quick poll",
```

- **GOTCHA:** `"brought to you by"` is currently only in `_BOILERPLATE_ANCHORS` (for link anchor text). Adding it here causes the FULL SECTION to be dropped when this phrase appears in the text body — which is correct for `GTC COVERAGE BROUGHT TO YOU BY IREN` style sponsor labels.
- **GOTCHA:** `"together with"` is intentionally broad — it matches `| TOGETHER WITH AIRIA`, `Together With Metronome`, etc. This is correct; "together with" in newsletter context always means a sponsor label.
- **VALIDATE:** `python -m py_compile ingestion/email_parser.py && echo "syntax ok"`

---

### TASK 2 — ADD `_strip_leading_pipe()` helper and apply it in `_extract_sections()`

**Root cause:** Many sections begin with `|   ` (a table cell artifact) that precedes actual content. Example: `'|   **Meta Acquired Moltbook (3 minute read)** ...'`. Stripping this restores normal section structure and allows downstream filters and title detection to work correctly.

- **ADD** this function after `_is_heading_only()` in `ingestion/email_parser.py`:

```python
_LEADING_PIPE_RE = re.compile(r'^\|\s*')


def _strip_leading_pipe(text: str) -> str:
    """Strip a leading table-cell '|' artifact from section text.

    Newsletter email HTML uses table-based layout. When html2text converts
    a table cell, it may emit '|  ' at the start of the cell's content.
    This strips that prefix so downstream filters and title detection work
    on the actual content text.

    Only strips if the text starts with '|' followed by optional spaces.
    A line that is ONLY '|' (with no content) is left for _is_table_artifact()
    to handle.
    """
    stripped = _LEADING_PIPE_RE.sub('', text, count=1)
    return stripped if stripped.strip() else text
```

- **APPLY** in `_extract_sections()`, at the very start of the `for sec in merged:` loop, before any other processing:

```python
    for sec in merged:
        sec = sec.strip()
        if not sec:
            continue
        sec = _strip_leading_pipe(sec)        # NEW — strip table cell artifact prefix
        ...
```

- **GOTCHA:** Apply BEFORE `_split_list_section(sec)` so list detection sees clean text.
- **GOTCHA:** The fallback `return stripped if stripped.strip() else text` ensures that a section whose ONLY content after stripping is whitespace is not accidentally returned as empty (the original `text` is returned, which will then be caught by `if not sec: continue`).
- **VALIDATE:** `python -m py_compile ingestion/email_parser.py && echo "syntax ok"`

---

### TASK 3 — ADD `_is_story_heading()` and `_is_category_heading()` helpers

These enable the reassembly algorithm to distinguish TDV-style story headings from TLDR-style category/section headings.

- **ADD** these functions immediately after `_strip_leading_pipe()`:

```python
def _is_story_heading(text: str) -> bool:
    """Return True if text is a story-level heading (suitable for story assembly).

    A story heading is a section whose content is entirely one or more '#'-prefixed
    lines, where the heading text is NOT wrapped in **bold** markers.

    - '# Nvidia builds the tech stack for the robotics era' → True (story heading)
    - '# **Headlines & Launches**' → False (category/section label)
    - '# **TLDR AI 2026-03-11**' → False (newsletter title/label)

    Category headings with bold wrapping are section labels in TLDR-style newsletters.
    These should NOT trigger paragraph collection (each following item is its own story).
    """
    lines = [l for l in text.strip().splitlines() if l.strip()]
    if not lines:
        return False
    if not all(l.startswith('#') for l in lines):
        return False
    # Extract heading text from the first heading line
    heading_text = lines[0].lstrip('#').strip()
    # If the entire heading text is bold-wrapped, it's a category label
    if heading_text.startswith('**') and heading_text.endswith('**') and len(heading_text) > 4:
        return False
    return True
```

- **GOTCHA:** `_is_heading_only()` is still used in other places — do NOT remove it. `_is_story_heading()` is the new, more selective version used for reassembly.
- **VALIDATE:** `python -c "from ingestion.email_parser import _is_story_heading; print(_is_story_heading('# Nvidia builds the tech stack')); print(_is_story_heading('# **Headlines & Launches**'))"`
  Expected: `True` then `False`

---

### TASK 4 — REWRITE the heading-merge loop in `_extract_sections()` for story reassembly

This is the core story reassembly change. Replace the current heading-merge loop with one that collects ALL following paragraphs under a story heading until a story boundary is reached.

**Current code** (lines ~384–395 in `_extract_sections()`):
```python
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
```

**Replace with:**
```python
    # Story reassembly: merge story headings with all following paragraph sections
    # until the next story heading, category heading, or boilerplate boundary.
    merged: list[str] = []
    i = 0
    while i < len(raw_sections):
        sec = raw_sections[i].strip()
        if not sec:
            i += 1
            continue

        if _is_story_heading(sec):
            # Collect this heading and all following non-heading, non-boilerplate sections
            story_parts = [sec]
            i += 1
            while i < len(raw_sections):
                next_sec = raw_sections[i].strip()
                if not next_sec:
                    i += 1
                    continue
                # Stop collecting at any heading (new story or category label)
                if _is_heading_only(next_sec):
                    break
                # Stop collecting at boilerplate boundaries (sponsor sections etc.)
                if _is_boilerplate_segment(next_sec):
                    break
                # Stop collecting at structural noise (table artifacts — avoids
                # absorbing | TOGETHER WITH AIRIA etc. into the story)
                if _is_table_artifact(_MD_LINK_RE.sub(r'\1', next_sec).strip()):
                    break
                story_parts.append(next_sec)
                i += 1
            merged.append("\n\n".join(story_parts))

        elif _is_heading_only(sec):
            # Category heading (bold-wrapped) — merge with next section only (original behavior)
            if i + 1 < len(raw_sections):
                merged.append(sec + "\n\n" + raw_sections[i + 1].strip())
                i += 2
            else:
                merged.append(sec)
                i += 1

        else:
            merged.append(sec)
            i += 1
```

- **GOTCHA:** `_is_boilerplate_segment()` is called on `next_sec` (raw markdown, before link stripping). This is correct — the boilerplate signals work on body text. Do not call it on `clean_text` here.
- **GOTCHA:** `_is_table_artifact()` is called on `clean_text` (after link stripping via `_MD_LINK_RE.sub(r'\1', next_sec).strip()`). This matches its original usage pattern.
- **GOTCHA:** The `_is_boilerplate_segment()` check here is for the COLLECTION LOOP boundary — it stops collecting into the current story. The main `_extract_sections()` filter later will still drop boilerplate sections from the output.
- **GOTCHA:** `_strip_leading_pipe()` must be called on `next_sec` before the heading/boilerplate checks? NO — apply `_strip_leading_pipe()` on the merged sections during the main processing loop (Task 2), not during collection. The collection loop uses the raw sections.
- **EFFECT:** TDV story "Nvidia builds..." → heading + paragraphs 1 and 2 collected → one merged section. Paragraph 3 (after IREN sponsor break) becomes a standalone section.
- **EFFECT:** TLDR category "# **Headlines & Launches**" → merged with immediately next section (original behavior for `_is_heading_only()`).
- **VALIDATE:** `python -m py_compile ingestion/email_parser.py && echo "syntax ok"`

---

### TASK 5 — UPDATE `_extract_title()` to detect bold-title pattern

TLDR story sections look like `**Meta Acquired Moltbook (3 minute read)**\n\nMeta has acquired Moltbook...` after link-stripping. The bold title is the story title.

- **UPDATE** `_extract_title()` in `ingestion/email_parser.py` — add bold-title detection after the existing `#` heading check:

```python
def _extract_title(text: str) -> tuple[str | None, str]:
    """Extract a heading title from section text.

    Detects two title formats:
    1. Markdown heading: first non-empty line starts with '#'
    2. Bold title: first non-empty line is entirely '**title text**'

    Returns (title_text, body_without_title).
    Returns (None, original_text) if no title is found.
    """
    lines = text.split("\n")
    for i, line in enumerate(lines):
        stripped = line.strip()
        if not stripped:
            continue
        # Format 1: markdown heading
        if stripped.startswith("#"):
            title = stripped.lstrip("#").strip()
            body = "\n".join(lines[i + 1:]).lstrip("\n").strip()
            return title or None, body
        # Format 2: bold title (entire first non-empty line is **text**)
        if stripped.startswith("**") and stripped.endswith("**") and len(stripped) > 4:
            title = stripped[2:-2].strip()
            body = "\n".join(lines[i + 1:]).lstrip("\n").strip()
            return title or None, body
        # First non-empty line is not a heading
        break
    return None, text
```

- **GOTCHA:** The bold-title check requires the ENTIRE first non-empty line to be `**...**` — it must start AND end with `**`. This prevents false positives from inline bold text like `**important:** some description`.
- **GOTCHA:** The fallback `title or None` handles `**  **` (empty bold markers) — same as for headings.
- **VALIDATE:** `python -c "from ingestion.email_parser import _extract_title; print(_extract_title('**Meta Acquired Moltbook (3 minute read)**\n\nMeta has acquired Moltbook...'))"`
  Expected: `('Meta Acquired Moltbook (3 minute read)', 'Meta has acquired Moltbook...')`

---

### TASK 6 — UPDATE `StoryRecord` schema: `links: list[str]` and `source_count: int`

- **UPDATE** `ingestion/email_parser.py`:
  1. Change `from dataclasses import dataclass` → `from dataclasses import dataclass, field`
  2. Replace the `StoryRecord` dataclass definition:

```python
@dataclass
class StoryRecord:
    title: str | None    # first #-heading or **bold** title; None if absent
    body: str            # section text without the title line; primary dedup signal
    links: list[str]     # all non-boilerplate URLs from the section; empty list if none
    newsletter: str      # sender display name or email address
    date: str            # YYYY-MM-DD; empty string if email Date header missing/unparseable
    source_count: int = field(default=1)
    # source_count: set to 1 by parse_emails(); updated to len(cluster) by deduplicate().
    # A value > 1 means this record was selected as representative from N duplicate story items.
```

- **GOTCHA:** `source_count` must have a default value so existing `StoryRecord(title=..., body=..., links=..., newsletter=..., date=...)` calls continue to work without passing `source_count`.
- **GOTCHA:** `links` is now a required positional field (no default). All `StoryRecord(...)` calls must pass `links=[...]`. Search for all `StoryRecord(` calls in the codebase: `grep -n "StoryRecord(" ingestion/email_parser.py processing/deduplicator.py tests/`.
- **VALIDATE:** `python -c "from ingestion.email_parser import StoryRecord; r = StoryRecord(title=None, body='test', links=[], newsletter='A', date='2026-03-17'); print(r.source_count)"`
  Expected: `1`

---

### TASK 7 — ADD `_collect_links()` and REMOVE `_select_link()`

- **REPLACE** `_select_link()` with `_collect_links()`:

```python
def _collect_links(links: list[dict]) -> list[str]:
    """Return all normalized URLs from a section's filtered links list.

    The links list is already boilerplate-filtered by _extract_sections() — every
    entry is a non-boilerplate, non-social URL. All URLs are returned as a list.
    Returns an empty list if no links are present.
    """
    return [entry["url"] for entry in links]
```

- **REMOVE** the old `_select_link()` function entirely.
- **UPDATE** `parse_emails()` to use `_collect_links()`:
  - Change: `link = _select_link(section.get("links", []))`
  - To: `links = _collect_links(section.get("links", []))`
  - Change: `StoryRecord(title=title, body=body, link=link, newsletter=newsletter, date=date_formatted)`
  - To: `StoryRecord(title=title, body=body, links=links, newsletter=newsletter, date=date_formatted)`
- **VALIDATE:** `python -m py_compile ingestion/email_parser.py && echo "syntax ok"`

---

### TASK 8 — UPDATE `parse_emails()` for `\xa0` normalization and trailing `|` stripping

In the `for section in sections:` loop in `parse_emails()`, after the body fallback and before the `_is_table_artifact(body)` check:

**ADD** `\xa0` normalization immediately after `section_text` is obtained:
```python
        section_text = section.get("text", "").strip()
        if not section_text:
            continue
        section_text = section_text.replace('\xa0', ' ')   # NEW — normalize non-breaking spaces
```

**ADD** trailing-pipe strip AFTER `_is_table_artifact(body)` check and BEFORE `_collect_links()`:

```python
        title, body = _extract_title(section_text)
        if not body.strip():
            body = section_text  # fallback
        if _is_table_artifact(body):           # Phase 3: drop body='|'
            continue
        # Strip trailing table-artifact '|' from end of body text
        body = re.sub(r'(\s*\|)+\s*$', '', body).strip()   # NEW — strip trailing | lines
        if not body:                                         # NEW — skip if body is now empty
            continue
```

- **GOTCHA:** `re.sub(r'(\s*\|)+\s*$', '', body)` strips one or more `|` characters (with surrounding whitespace) from the very end of the body. This handles `body='content\n|'`, `body='content\n|\n|'`, and `body='content | | '`.
- **GOTCHA:** After stripping, `if not body: continue` guards against the rare case where the entire body was `|`-only content that wasn't caught by `_is_table_artifact()`.
- **GOTCHA:** `re` is already imported at the top of `email_parser.py`.
- **VALIDATE:** `python -m py_compile ingestion/email_parser.py && echo "syntax ok"`

---

### TASK 9 — UPDATE `processing/deduplicator.py` for new schema

- **UPDATE** `select_representative()` in `processing/deduplicator.py`:
  1. Change the `max()` key: `r.link is not None` → `bool(r.links)`
  2. After selecting representative, merge `links` from all cluster items
  3. Set `source_count = len(cluster)` on the returned record

```python
def select_representative(cluster: list[StoryRecord]) -> StoryRecord:
    """Select the representative story item from a cluster of duplicates.

    Selection priority (higher is better, applied left-to-right as a tuple key):
    1. Longest body — maximises content richness; body text is the dedup signal
    2. Has title — structured items preferred over untitled ones as tiebreaker
    3. Has links — items with content URLs are preferable as tiebreaker

    After selection, the representative's date is replaced with the earliest date
    across all items in the cluster. Links from all cluster items are merged
    (deduplicating on URL). source_count is set to the cluster size.

    Args:
        cluster: Non-empty list of StoryRecord objects from one semantic cluster.

    Returns:
        A new StoryRecord (via dataclasses.replace) with the representative's
        fields, the earliest date, merged links, and source_count = len(cluster).
    """
    representative = max(
        cluster,
        key=lambda r: (len(r.body), r.title is not None, bool(r.links)),
    )
    earliest_date = min(
        (r.date for r in cluster if r.date),
        default=representative.date,
    )
    # Merge links from all cluster items, preserving order and deduplicating on URL
    seen_urls: set[str] = set()
    merged_links: list[str] = []
    for item in cluster:
        for url in item.links:
            if url not in seen_urls:
                seen_urls.add(url)
                merged_links.append(url)
    return dataclasses.replace(
        representative,
        date=earliest_date,
        links=merged_links,
        source_count=len(cluster),
    )
```

- **VALIDATE:** `python -m py_compile processing/deduplicator.py && echo "syntax ok"`

---

### TASK 10 — UPDATE `tests/test_deduplicator.py` for new schema

- **UPDATE** the `_record()` helper — change `link: str | None = None` → `links: list[str] = None` (with `field(default_factory=list)` not needed since it's a helper, just use `links: list[str] | None = None` with `links or []`):

```python
def _record(
    body: str,
    title: str | None = None,
    links: list[str] | None = None,
    newsletter: str = "Test Newsletter",
    date: str = "2026-03-17",
) -> StoryRecord:
    """Build a minimal StoryRecord for testing."""
    return StoryRecord(title=title, body=body, links=links or [], newsletter=newsletter, date=date)
```

- **UPDATE** all tests that previously passed `link="url"` → `links=["url"]`
- **UPDATE** all tests that checked `result.link == "url"` → `result.links == ["url"]` or `"url" in result.links`
- **UPDATE** `test_link_breaks_remaining_tie`:
  - Old: `no_link = _record(..., link=None)` / `with_link = _record(..., link="url")`
  - New: `no_links = _record(..., links=[])` / `with_links = _record(..., links=["https://example.com/story"])`
  - Old assert: `assert result.link == "https://example.com/story"`
  - New assert: `assert result.links == ["https://example.com/story"]`

- **ADD** new tests at the end of the file:

```python
def test_select_representative_merges_links_from_cluster():
    """Links from all cluster items are merged into the representative."""
    r1 = _record("Short.", links=["https://example.com/a"])
    r2 = _record("Longer body that wins on selection.", links=["https://example.com/b"])
    result = select_representative([r1, r2])
    assert "https://example.com/a" in result.links
    assert "https://example.com/b" in result.links
    assert len(result.links) == 2


def test_select_representative_deduplicates_links():
    """Duplicate URLs across cluster items appear only once in merged links."""
    shared_url = "https://example.com/story"
    r1 = _record("Short.", links=[shared_url])
    r2 = _record("Longer body wins.", links=[shared_url, "https://example.com/other"])
    result = select_representative([r1, r2])
    assert result.links.count(shared_url) == 1
    assert len(result.links) == 2


def test_select_representative_sets_source_count():
    """source_count equals the number of items in the cluster."""
    cluster = [_record(f"Body {i}.") for i in range(3)]
    result = select_representative(cluster)
    assert result.source_count == 3


def test_select_representative_single_item_source_count_is_1():
    """Single-item cluster has source_count=1."""
    r = _record("Only item.")
    result = select_representative([r])
    assert result.source_count == 1


def test_deduplicate_source_count_set_on_representatives():
    """deduplicate() propagates source_count from clusters to output."""
    cluster = [_record(f"Story content item {i}.") for i in range(4)]
    result = deduplicate([cluster])
    assert len(result) == 1
    assert result[0].source_count == 4
```

- **VALIDATE:** `python -m pytest tests/test_deduplicator.py -v`

---

### TASK 11 — UPDATE `tests/test_email_parser.py` for schema changes

- **UPDATE** all tests that check `r.link` → check `r.links` (list):
  - `test_parse_emails_link_extracted`: change `assert records[0].link == "https://openai.com/pricing"` → `assert "https://openai.com/pricing" in records[0].links`
  - `test_parse_emails_link_none_when_no_link`: change `assert records[0].link is None` → `assert records[0].links == []`
  - `test_select_link_returns_first_url` and `test_select_link_empty_returns_none`: these test `_select_link()` which is being removed — **DELETE these two tests** and replace with new `test_collect_links_*` tests

- **ADD** replacement tests for `_collect_links()`:

```python
def test_collect_links_returns_all_urls():
    """_collect_links() returns all URLs from the links list."""
    from ingestion.email_parser import _collect_links
    links = [
        {"url": "https://example.com/a", "anchor_text": "First"},
        {"url": "https://example.com/b", "anchor_text": "Second"},
    ]
    assert _collect_links(links) == ["https://example.com/a", "https://example.com/b"]


def test_collect_links_empty_returns_empty_list():
    """_collect_links() returns empty list when no links."""
    from ingestion.email_parser import _collect_links
    assert _collect_links([]) == []
```

- **VALIDATE:** `python -m pytest tests/test_email_parser.py -v`

---

### TASK 12 — ADD Phase 4 feature tests to `tests/test_email_parser.py`

Add the following tests after the Phase 3 tests. Do not modify any existing tests beyond the schema updates in Task 11.

```python
# ---------------------------------------------------------------------------
# Phase 4: Story reassembly, pipe stripping, bold-title detection, xa0 tests
# ---------------------------------------------------------------------------

def test_trailing_pipe_stripped_from_body():
    """Body text with trailing '|' has the pipe stripped."""
    html = _html(
        "<p>Nvidia is betting on robots, without actually building any robots.</p>"
        "<p>|</p>"   # trailing table artifact — same paragraph structure as real email
    )
    raw = _make_raw_email(html)
    records = parse_emails([raw])
    for r in records:
        assert not r.body.rstrip().endswith("|"), (
            f"Trailing '|' found in body: {r.body[-50:]!r}"
        )


def test_xa0_normalized_in_body():
    """Non-breaking spaces are normalized to regular spaces in body text."""
    html = _html(
        "<p>In the AI era, pricing is your product.\xa0 The shift is here.</p>"
    )
    raw = _make_raw_email(html)
    records = parse_emails([raw])
    assert len(records) >= 1
    for r in records:
        assert '\xa0' not in r.body, f"\\xa0 found in body: {r.body[:100]!r}"


def test_together_with_section_dropped():
    """A section containing 'together with' (sponsor label) is dropped."""
    html = _html("<p>Together with Acme AI</p>")
    raw = _make_raw_email(html)
    records = parse_emails([raw])
    together_records = [r for r in records if "together with" in r.body.lower()]
    assert together_records == [], (
        f"Got {len(together_records)} 'together with' record(s)"
    )


def test_thanks_for_reading_section_dropped():
    """A section containing 'thanks for reading' (outro) is dropped."""
    html = _html(
        "<p>Thanks for reading today's edition of The Deep View! We'll see you in the next one.</p>"
    )
    raw = _make_raw_email(html)
    records = parse_emails([raw])
    outro_records = [r for r in records if "thanks for reading" in r.body.lower()]
    assert outro_records == [], (
        f"Outro section produced {len(outro_records)} record(s)"
    )


def test_story_heading_collects_following_paragraphs():
    """A story heading merges with all following paragraphs into one record."""
    html = _html(
        "<h1>Nvidia builds the tech stack for the robotics era</h1>"
        "<p>Nvidia is betting on robots, without actually building any robots.</p>"
        "<p>This is a continuation paragraph with more context about the story.</p>"
    )
    raw = _make_raw_email(html)
    records = parse_emails([raw])
    # All three parts should be in one record
    assert len(records) == 1, f"Expected 1 record, got {len(records)}"
    r = records[0]
    assert r.title == "Nvidia builds the tech stack for the robotics era"
    assert "Nvidia is betting on robots" in r.body
    assert "continuation paragraph" in r.body


def test_category_heading_does_not_merge_following_stories():
    """A bold-wrapped category heading (TLDR-style) does NOT collect following stories."""
    html = _html(
        "<h1><strong>Headlines &amp; Launches</strong></h1>"
        "<p><strong>Meta Acquired Moltbook (3 minute read)</strong> Meta has acquired Moltbook.</p>"
        "<p><strong>Nvidia Invests in Lab (2 minute read)</strong> Nvidia announced an investment.</p>"
    )
    raw = _make_raw_email(html)
    records = parse_emails([raw])
    # Two stories should be two records (category heading does not merge them)
    assert len(records) >= 2, (
        f"Expected 2+ records for two distinct stories, got {len(records)}"
    )


def test_bold_title_extracted_as_story_title():
    """A section starting with **Bold Title** has it extracted as the story title."""
    html = _html(
        "<p><strong>Meta Acquired Moltbook (3 minute read)</strong></p>"
        "<p>Meta has acquired Moltbook, a Reddit-like network where AI agents collaborate.</p>"
    )
    raw = _make_raw_email(html)
    records = parse_emails([raw])
    assert len(records) >= 1
    titled = [r for r in records if r.title is not None]
    assert titled, "Expected at least one record with a title from bold-title pattern"
    assert any("Meta Acquired Moltbook" in r.title for r in titled), (
        f"Expected title containing 'Meta Acquired Moltbook', got: {[r.title for r in titled]}"
    )


def test_links_field_is_list():
    """StoryRecord.links is always a list (empty list when no links)."""
    html = _html("<p>AI safety researchers published a new alignment paper this week.</p>")
    raw = _make_raw_email(html)
    records = parse_emails([raw])
    assert len(records) >= 1
    for r in records:
        assert isinstance(r.links, list), f"links should be a list, got {type(r.links)}"


def test_links_field_contains_story_urls():
    """StoryRecord.links contains all non-boilerplate story URLs."""
    html = _html(
        '<p>OpenAI cut API prices. '
        '<a href="https://openai.com/pricing">See pricing</a> and '
        '<a href="https://openai.com/blog/api-update">read the announcement</a>.</p>'
    )
    raw = _make_raw_email(html)
    records = parse_emails([raw])
    assert len(records) >= 1
    all_links = [url for r in records for url in r.links]
    assert any("openai.com/pricing" in url for url in all_links)
    assert any("openai.com/blog" in url for url in all_links)


def test_source_count_default_is_1():
    """StoryRecord.source_count defaults to 1 when produced by parse_emails()."""
    html = _html("<p>Anthropic released Claude 4 with improved reasoning capabilities.</p>")
    raw = _make_raw_email(html)
    records = parse_emails([raw])
    assert len(records) >= 1
    for r in records:
        assert r.source_count == 1, f"Expected source_count=1, got {r.source_count}"
```

- **VALIDATE:** `python -m pytest tests/test_email_parser.py tests/test_deduplicator.py -v`

---

## TESTING STRATEGY

### Unit Tests

All existing 36 email_parser tests and 17 deduplicator tests must continue to pass after schema updates in Tasks 10–11. New tests in Task 12 add coverage for every Phase 4 feature.

### Edge Cases

- Story heading followed immediately by another heading (no body) → heading section with no paragraphs → dropped by `_MIN_SECTION_CHARS`
- Category heading with ONE story following → that story stays as its own record (not merged into category heading)
- Section where entire content is `| TOGETHER WITH X` → dropped by new boilerplate signal
- Body that is ONLY `\xa0` characters → normalizes to spaces → dropped by `_MIN_SECTION_CHARS` (empty after strip)
- `links: list[str]` with 0, 1, or multiple URLs — all valid
- `source_count` must NOT be passed to `StoryRecord()` from `parse_emails()` — it defaults to 1

---

## VALIDATION COMMANDS

### Level 1: Syntax

```bash
python -m py_compile ingestion/email_parser.py && echo "email_parser syntax ok"
python -m py_compile processing/deduplicator.py && echo "deduplicator syntax ok"
```

### Level 2: Unit Tests

```bash
python -m pytest tests/test_email_parser.py tests/test_deduplicator.py -v
```

Expected: all tests passing (no failures). Final count should be 36 email_parser tests + new Phase 4 tests + 17 + new deduplicator tests.

### Level 3: Import Smoke Test

```bash
python -c "
from ingestion.email_parser import StoryRecord, parse_emails, _extract_title, _collect_links, _is_story_heading
print('StoryRecord fields:', list(StoryRecord.__dataclass_fields__.keys()))
title, body = _extract_title('# My Headline\nBody text here.')
print('# heading title:', title)
title2, body2 = _extract_title('**Bold Story Title**\n\nStory content here.')
print('**bold** title:', title2)
print('is_story_heading (bare):', _is_story_heading('# Nvidia builds the tech stack'))
print('is_story_heading (bold):', _is_story_heading('# **Headlines & Launches**'))
links = _collect_links([{'url': 'https://a.com', 'anchor_text': 'A'}, {'url': 'https://b.com', 'anchor_text': 'B'}])
print('collect_links:', links)
r = StoryRecord(title=None, body='test', links=['https://example.com'], newsletter='A', date='2026-03-17')
print('source_count default:', r.source_count)
print('All ok')
"
```

Expected output:
```
StoryRecord fields: ['title', 'body', 'links', 'newsletter', 'date', 'source_count']
# heading title: My Headline
**bold** title: Bold Story Title
is_story_heading (bare): True
is_story_heading (bold): False
collect_links: ['https://a.com', 'https://b.com']
source_count default: 1
All ok
```

### Level 4: The Deep View real-email inspection

```bash
python -c "
import sys; sys.path.insert(0, '.')
from ingestion.email_parser import parse_emails
with open('debug_samples/the_deep_view.eml', 'rb') as f:
    raw = f.read()
records = parse_emails([raw])
print(f'Total records: {len(records)}')
pipe_trail = [r for r in records if r.body.rstrip().endswith('|')]
xa0_records = [r for r in records if '\xa0' in r.body]
pipe_body = [r for r in records if r.body.strip() == '|']
print(f'Records with trailing |: {len(pipe_trail)} (expected: 0)')
print(f'Records with xa0: {len(xa0_records)} (expected: 0)')
print(f'Records with body=\"|\": {len(pipe_body)} (expected: 0)')
nvidia_records = [r for r in records if r.title and 'Nvidia builds' in r.title]
print(f'Records with Nvidia robotics title: {len(nvidia_records)} (expected: 1)')
if nvidia_records:
    r = nvidia_records[0]
    print(f'  links: {len(r.links)} links, source_count={r.source_count}')
    print(f'  body preview: {r.body[:100]!r}')
print()
print('First 5 records:')
for i, r in enumerate(records[:5], 1):
    print(f'  [{i}] title={r.title!r}  links={len(r.links)}  source_count={r.source_count}')
    print(f'       body: {r.body[:80]!r}')
"
```

Expected:
- `Records with trailing |: 0`
- `Records with xa0: 0`
- `Records with body="|": 0`
- `Records with Nvidia robotics title: 1` (story heading correctly found)
- Total records: ~20–30 (reduced from 40 by story assembly and new signals)

### Level 5: TLDR real-email inspection

```bash
python -c "
import sys; sys.path.insert(0, '.')
from ingestion.email_parser import parse_emails
with open('debug_samples/tldr_sample.eml', 'rb') as f:
    raw = f.read()
records = parse_emails([raw])
print(f'Total records: {len(records)}')
print('First 8 records:')
for i, r in enumerate(records[:8], 1):
    print(f'  [{i}] title={r.title!r}')
    print(f'       body: {r.body[:80]!r}')
    print(f'       links={len(r.links)}  source_count={r.source_count}')
print()
pipe_trail = [r for r in records if r.body.rstrip().endswith('|')]
print(f'Records with trailing |: {len(pipe_trail)} (expected: 0)')
meta_story = [r for r in records if r.title and 'Meta Acquired' in r.title]
print(f'Records with Meta Acquired title: {len(meta_story)} (expected: 1+)')
"
```

Expected:
- TLDR stories remain as individual records (no regression)
- Bold titles extracted: `r.title = 'Meta Acquired Moltbook (3 minute read)'` (or similar)
- No trailing `|`

---

## MANUAL VERIFICATION CHECKLIST

- [ ] `StoryRecord.links` is a `list[str]`, `StoryRecord.source_count` is `int` with default 1
- [ ] `_select_link()` is removed; `_collect_links()` is present
- [ ] `_is_story_heading()` correctly returns True for bare `#` headings, False for `# **bold**` headings
- [ ] TDV story "Nvidia builds the tech stack for the robotics era" produces ONE record with all paragraphs in body (not split into 3)
- [ ] TLDR "Headlines & Launches" category does NOT merge following stories into one record
- [ ] No `\xa0` in any record body from either test email
- [ ] No records with body ending in `|`
- [ ] `| TOGETHER WITH X` sections produce no records
- [ ] `"thanks for reading"` section produces no record
- [ ] `links` is a list in all records; `source_count` = 1 for all records from `parse_emails()`
- [ ] After `deduplicate()`, representative's `source_count` = cluster size, `links` = merged from all cluster items

---

## ROLLBACK CONSIDERATIONS

All changes are in `ingestion/email_parser.py`, `processing/deduplicator.py`, and their test files. Git revert to any prior commit restores full state. The `StoryRecord` schema change breaks any code that references `.link` — search for all `.link` usages before merging.

## ACCEPTANCE CRITERIA

- [ ] All Phase 4 features implemented per task specs
- [ ] All validation commands pass with zero errors
- [ ] Level 4 inspection: 0 trailing-pipe records, 0 `\xa0` records, Nvidia story has correct title and is ONE record
- [ ] Level 5 inspection: TLDR stories remain individual records, bold titles extracted
- [ ] `source_count` = 1 on all `parse_emails()` output; set to cluster size by `deduplicate()`
- [ ] `links` is `list[str]` — no `link: str | None` remaining anywhere in codebase
- [ ] All existing tests continue to pass (no regressions)

---

## COMPLETION CHECKLIST

- [ ] All tasks completed in order
- [ ] `python -m py_compile ingestion/email_parser.py` passes
- [ ] `python -m py_compile processing/deduplicator.py` passes
- [ ] `python -m pytest tests/test_email_parser.py tests/test_deduplicator.py -v` — all tests pass
- [ ] Level 3 smoke test output matches expected exactly
- [ ] Level 4 TDV inspection: 0 trailing-pipe, 0 xa0, Nvidia title found
- [ ] Level 5 TLDR inspection: no regression, bold titles extracted

---

## NOTES

**Why `source_count` not `duplicate_count`:** The field represents how many newsletter issues covered the same story, from the reader's perspective — "this story appeared in 3 sources." A count of 1 means "seen once."

**Story reassembly and partial coverage:** A story like "Nvidia robotics" whose paragraphs are interrupted by a sponsor section will be SPLIT at the sponsor break. The pre-sponsor paragraphs form one record; the post-sponsor paragraph becomes a standalone record. This is acceptable — the dedup/embedder stage can further cluster content-similar paragraphs. Perfect reassembly requires semantic understanding beyond what a structural parser can provide.

**Why bold-title check requires ENTIRE first line to be `**...**`:** Inline bold like `**important:** here is some text` must not be extracted as a title. The full-line check (`startswith('**') and endswith('**')`) prevents this.

**`_select_link()` removal:** This function is referenced in two test files. Task 11 deletes those tests and replaces with `_collect_links()` tests. After removing, verify with `grep -rn "_select_link" .` returns no results.

**Downstream compatibility:** `processing/digest_builder.py` currently references `StoryRecord` fields. Since it's being rewritten in a subsequent plan anyway, any temporary breakage there is acceptable. However, verify `python -m pytest tests/` does not introduce NEW collection errors beyond the already-known `test_claude_client.py` and `test_story_reviewer.py` failures.

---

## VALIDATION OUTPUT REFERENCE — EXACT OUTPUTS TO CHECK

- Item to check:
  `python -m py_compile ingestion/email_parser.py && echo "email_parser syntax ok"`
  Expected output or result:
  `email_parser syntax ok`

- Item to check:
  `python -m py_compile processing/deduplicator.py && echo "deduplicator syntax ok"`
  Expected output or result:
  `deduplicator syntax ok`

- Item to check:
  `python -m pytest tests/test_email_parser.py tests/test_deduplicator.py -v`
  Expected output or result:
  All tests PASSED. Zero failures, zero errors. Count includes all Phase 1–4 email_parser tests plus all updated deduplicator tests.

- Item to check:
  Level 3 smoke test (full command in Validation Commands section)
  Expected output or result:
  ```
  StoryRecord fields: ['title', 'body', 'links', 'newsletter', 'date', 'source_count']
  # heading title: My Headline
  **bold** title: Bold Story Title
  is_story_heading (bare): True
  is_story_heading (bold): False
  collect_links: ['https://a.com', 'https://b.com']
  source_count default: 1
  All ok
  ```

- Item to check:
  Level 4: `Records with trailing |:` line
  Expected output or result:
  `Records with trailing |: 0`

- Item to check:
  Level 4: `Records with xa0:` line
  Expected output or result:
  `Records with xa0: 0`

- Item to check:
  Level 4: `Records with body="|":` line
  Expected output or result:
  `Records with body="|": 0`

- Item to check:
  Level 4: `Records with Nvidia robotics title:` line
  Expected output or result:
  `Records with Nvidia robotics title: 1`

- Item to check:
  Level 5: `Records with trailing |:` line (TLDR)
  Expected output or result:
  `Records with trailing |: 0`

- Item to check:
  Level 5: `Records with Meta Acquired title:` line
  Expected output or result:
  `Records with Meta Acquired title: 1+` (at least 1)

- Item to check:
  `grep -n "link:" ingestion/email_parser.py` (checking old field name is gone)
  Expected output or result:
  No line matching `link: str | None` — only `links: list[str]` in the StoryRecord definition

- Item to check:
  `grep -rn "_select_link" ingestion/ tests/` (checking old function is removed)
  Expected output or result:
  No output — `_select_link` must not exist anywhere

**Confidence score: 7/10.** The story reassembly algorithm is the highest-risk task — the `_is_story_heading()` heuristic (bold-wrapped = category) works for TDV and TLDR but may need adjustment for other newsletter formats. The schema change (Tasks 6–11) is mechanical but touches many test assertions. Level 4/5 real-email inspections are the most reliable signal for whether the plan succeeded.
