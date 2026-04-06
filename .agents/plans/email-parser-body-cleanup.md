# Feature: email-parser-body-cleanup (Phase 5)

The following plan should be complete, but it's important that you validate the codebase patterns and task sanity before starting implementation.

Pay special attention to existing helpers like `_is_table_artifact`, `_is_boilerplate_segment`, `_split_list_section`, `_MIN_SECTION_CHARS`, and `_MD_LINK_RE`. Import nothing new unless listed below.

## Feature Description

Six targeted body-cleanup fixes for `ingestion/email_parser.py`, derived from manual inspection of the `the_deep_view.eml` test output (`tests/test-results/2026-04-04T01-35-27-test-results.txt`). Each fix addresses one confirmed root-cause defect. No structural redesign — only surgical additions.

## User Story

As a newsletter digest user
I want the extracted story records to have clean bodies and complete links
So that stories are complete, readable, and correctly associated with their source URLs

## Problem Statement

Six defects confirmed by manual inspection:

| # | Symptom | Record(s) | Root Cause |
|---|---------|-----------|------------|
| 1 | Intro/ToC not dropped as boilerplate | [1] | U+2019 `'` in "TODAY'S" doesn't match ASCII `'` in signal `"in today's newsletter"` |
| 2 | `****\n\n` artifacts in bullet list bodies | [2] | html2text renders empty `<strong></strong>` as `****`; not stripped |
| 3 | `\| HARDWARE` / `\| ENTERPRISE` theme labels absorbed into story body | [4], [6] | Story assembly inner loop has no min-length boundary; short structural sections are collected |
| 4 | Article primary image link missing from `links` list | [5] | `if not anchor: continue` skips `[](url)` empty-anchor links (TDV images are `<a href="article-url"><img...>`) |
| 5 | Trailing `\| \|  SUBSCRIBE` / `\| \|  GET IN TOUCH` junk in body | [28], [29] | Trailing line-level table artifacts are not stripped; current regex only removes trailing pure-pipe content |
| 6 | 4th bullet in 6-item roundup list dropped silently | [2] context | `_split_list_section()` discards items with no link; link-free items with sufficient text should be preserved |

## Scope

- In scope: all six fixes listed above, plus one regression test per fix
- Out of scope:
  - Sponsor section detection for records [4], [6] — LLM filter will handle
  - Quiz/poll/results records [22]–[27] — interactive content, LLM filter territory
  - Article assembly across sponsor section boundaries ([2]/[3] split) — newsletter-specific layout; deferred
  - Changes to `deduplicator.py` or any file outside `ingestion/email_parser.py` and `tests/test_email_parser.py`

## Solution Statement

Apply six minimal, independently testable changes to `email_parser.py`, each targeted at the confirmed root cause. Add one regression test per fix in `test_email_parser.py`.

## Feature Metadata

**Feature Type**: Bug Fix
**Estimated Complexity**: Low
**Primary Systems Affected**: `ingestion/email_parser.py`, `tests/test_email_parser.py`
**Dependencies**: None new — all fixes use existing helpers and stdlib
**Assumptions**: html2text, BeautifulSoup4 behavior as observed is stable

---

## CONTEXT REFERENCES

### Relevant Codebase Files — MUST READ BEFORE IMPLEMENTING

- `ingestion/email_parser.py` (lines 80–84) — `_MIN_SECTION_CHARS`, `_MD_LINK_RE`, `_LIST_ITEM_START`
- `ingestion/email_parser.py` (lines 121–152) — `_BOILERPLATE_SEGMENT_SIGNALS` tuple
- `ingestion/email_parser.py` (lines 236–239) — `_is_boilerplate_segment()`: does `text.lower()`, then `any(signal in text_lower ...)`
- `ingestion/email_parser.py` (lines 242–254) — `_is_table_artifact()`: pipe-ratio check on non-whitespace chars
- `ingestion/email_parser.py` (lines 379–425) — `_split_list_section()`: builds per-item dicts; only includes items where `if links and len(clean_text) >= _MIN_LIST_ITEM_CHARS`
- `ingestion/email_parser.py` (lines 428–546) — `_extract_sections()`: story assembly loop (lines 459–495), link extraction loop (lines 518–529)
- `ingestion/email_parser.py` (lines 653–675) — `parse_emails()` section processing loop: calls `_extract_title`, `_strip_leading_pipe`, trailing-pipe regex, `_collect_links`
- `tests/test_email_parser.py` (lines 264–280) — `_make_raw_email()` helper: builds a minimal MIME email from HTML; use this for all new tests

### New Files to Create

None. Only modify existing files.

### Files to Modify

- `ingestion/email_parser.py` — six targeted changes
- `tests/test_email_parser.py` — six new test functions appended at end of file

### Patterns to Follow

**Test helper usage** — every test creates a raw email via `_make_raw_email(html)` and calls `parse_emails([raw])`. Inspect `results` list.

**Signal addition pattern** — add to `_BOILERPLATE_SEGMENT_SIGNALS` tuple or adjust pre-processing inline; do not create new constants unless necessary.

**Regex placement** — new regex constants go after existing `_LEADING_PIPE_RE` (line 278); new helper functions go just before `_extract_sections` (line 428).

---

## IMPLEMENTATION PLAN

### Phase 1: Unicode normalization for boilerplate detection

**Fix**: In `_is_boilerplate_segment()`, normalize curly/smart apostrophes before the signal check. No external import needed — plain string `.replace()`.

### Phase 2: `****` artifact stripping in body

**Fix**: In `parse_emails()` section loop, after building `body` and before appending `StoryRecord`, strip runs of 4+ consecutive asterisks via `re.sub`.

### Phase 3: Min-length boundary in story assembly loop

**Fix**: Inside the story assembly `while` loop in `_extract_sections()`, after the existing three `break` checks, add a min-length boundary: compute `clean_next = _MD_LINK_RE.sub(r'\1', next_sec).strip()` and break if `len(clean_next) < _MIN_SECTION_CHARS`.

**Note**: `clean_next` is already computed for the `_is_table_artifact` check — reuse it by computing once and passing to both checks. See Task 3 below for exact refactor.

### Phase 4: Empty-anchor image link capture

**Fix**: In `_extract_sections()` link extraction loop, after the `if not anchor: continue` guard, add a separate branch for empty-anchor URLs: collect them into `best_by_norm` with `anchor_text=""` if not boilerplate. Apply the same fix to `_split_list_section()`.

### Phase 5: Trailing table-artifact line stripping

**Fix**: In `parse_emails()`, after the existing trailing-pipe regex, add a line-by-line strip: pop trailing lines whose stripped text is non-empty and passes `_is_table_artifact()`.

### Phase 6: Link-free list item preservation in `_split_list_section`

**Fix**: Refactor the per-item loop to track `linked_count` separately. Include link-free items (with `links=[]`) when `len(clean_text) >= _MIN_LIST_ITEM_CHARS`. Only return the split result when `linked_count >= 2` (at least two items have distinct links — enough to justify splitting).

---

## STEP-BY-STEP TASKS

### Task 1 — UPDATE `_is_boilerplate_segment()` in `email_parser.py`

**Location**: `ingestion/email_parser.py`, function `_is_boilerplate_segment` (line 236)

Current code:
```python
def _is_boilerplate_segment(text: str) -> bool:
    """Return True if this text segment is sponsor or shell content, not a news story."""
    text_lower = text.lower()
    return any(signal in text_lower for signal in _BOILERPLATE_SEGMENT_SIGNALS)
```

**IMPLEMENT**: Replace `text.lower()` with a two-step normalization that first replaces Unicode directional apostrophes/quotes with ASCII equivalents before lowercasing:
```python
def _is_boilerplate_segment(text: str) -> bool:
    """Return True if this text segment is sponsor or shell content, not a news story."""
    # Normalize Unicode smart apostrophes/quotes → ASCII before signal matching.
    # TDV and other newsletters use U+2019 RIGHT SINGLE QUOTATION MARK in phrases
    # like "IN TODAY'S NEWSLETTER" which would otherwise not match the ASCII signal.
    text_lower = (
        text
        .replace('\u2018', "'")   # LEFT SINGLE QUOTATION MARK
        .replace('\u2019', "'")   # RIGHT SINGLE QUOTATION MARK
        .replace('\u201c', '"')   # LEFT DOUBLE QUOTATION MARK
        .replace('\u201d', '"')   # RIGHT DOUBLE QUOTATION MARK
        .lower()
    )
    return any(signal in text_lower for signal in _BOILERPLATE_SEGMENT_SIGNALS)
```

**GOTCHA**: Must not change the global `text` variable — only the local `text_lower` used for signal matching. The original text is not modified.

**VALIDATE**: `python -m pytest tests/test_email_parser.py -k "test_boilerplate_unicode" -v`

---

### Task 2 — UPDATE `parse_emails()` in `email_parser.py`: strip `****` artifacts

**Location**: `ingestion/email_parser.py`, `parse_emails()` section loop (lines 653–675)

Locate the line `body = _strip_leading_pipe(body)` (after `_extract_title` and before `re.sub(r'(\s*\|)+\s*$', ...)`).

**IMPLEMENT**: After `body = _strip_leading_pipe(body)`, add:
```python
# Strip '****' markdown artifacts: html2text renders empty <strong></strong> as '****'.
# Four or more consecutive asterisks never appear in valid markdown (valid: **, *, ***).
body = re.sub(r'\*{4,}', '', body)
```

**GOTCHA**: `re` is already imported at top of file — no new import needed.

**VALIDATE**: `python -m pytest tests/test_email_parser.py -k "test_bold_artifact" -v`

---

### Task 3 — UPDATE story assembly inner loop in `_extract_sections()`: min-length boundary

**Location**: `ingestion/email_parser.py`, story assembly `while` loop (lines 463–482)

Current inner loop break checks:
```python
if _is_heading_only(next_sec) or _is_story_heading(next_sec):
    break
if _is_boilerplate_segment(next_sec):
    break
if _is_table_artifact(_MD_LINK_RE.sub(r'\1', next_sec).strip()):
    break
story_parts.append(next_sec)
```

**IMPLEMENT**: Compute `clean_next` once (for reuse across both the table-artifact check and the new min-length check), then add the min-length boundary check:
```python
if _is_heading_only(next_sec) or _is_story_heading(next_sec):
    break
if _is_boilerplate_segment(next_sec):
    break
clean_next = _MD_LINK_RE.sub(r'\1', next_sec).strip()
if _is_table_artifact(clean_next):
    break
if len(clean_next) < _MIN_SECTION_CHARS:
    break
story_parts.append(next_sec)
```

**PATTERN**: `_MIN_SECTION_CHARS = 20` (line 81). `| HARDWARE` has 10 clean chars — breaks loop. `| ENTERPRISE` has 12 clean chars — breaks loop.

**GOTCHA**: The break (not skip) is intentional — a short structural section signals a layout boundary; breaking ensures it falls through to the outer `else:` branch where it enters `merged` as a standalone item, then the second loop's `len(clean_text) < _MIN_SECTION_CHARS: continue` check drops it.

**VALIDATE**: `python -m pytest tests/test_email_parser.py -k "test_theme_label" -v`

---

### Task 4 — UPDATE link extraction loops in `_extract_sections()` and `_split_list_section()`: capture empty-anchor image links

**Location 1**: `_extract_sections()` link extraction loop (lines 518–529)

Current code:
```python
for anchor, url in _MD_LINK_RE.findall(sec):
    if not anchor:              # skip empty-anchor image links
        continue
    if _is_boilerplate_url(url):
        continue
    norm = _normalize_url(url)
    if norm not in best_by_norm:
        best_by_norm[norm] = {"url": norm, "anchor_text": anchor}
    elif len(anchor) > len(best_by_norm[norm]["anchor_text"]):
        best_by_norm[norm]["anchor_text"] = anchor
links = list(best_by_norm.values())
```

**IMPLEMENT**: Replace `if not anchor: continue` with a branch that collects empty-anchor URLs as well:
```python
for anchor, url in _MD_LINK_RE.findall(sec):
    if _is_boilerplate_url(url):
        continue
    norm = _normalize_url(url)
    if not anchor:
        # Empty-anchor link: TDV article images are <a href="article-url"><img ...>
        # which html2text renders as [](article-url). Collect the URL; it may be
        # the only link to the article. Only add if no other entry already holds
        # this normalized URL (a named link to the same destination takes priority).
        if norm not in best_by_norm:
            best_by_norm[norm] = {"url": norm, "anchor_text": ""}
        continue
    if norm not in best_by_norm:
        best_by_norm[norm] = {"url": norm, "anchor_text": anchor}
    elif len(anchor) > len(best_by_norm[norm]["anchor_text"]):
        best_by_norm[norm]["anchor_text"] = anchor
links = list(best_by_norm.values())
```

**Location 2**: `_split_list_section()` per-item link loop (lines 410–419)

Current:
```python
for anchor, url in _MD_LINK_RE.findall(raw):
    if not anchor:              # skip empty-anchor image links
        continue
    if _is_boilerplate_url(url):
        continue
    ...
```

**IMPLEMENT**: Apply the same empty-anchor capture pattern here. Replace the `if not anchor: continue` guard with the same two-branch approach as above (check boilerplate first, then handle empty anchor by inserting with `anchor_text=""`).

**GOTCHA**: The named-link priority logic (`elif len(anchor) > len(best_by_norm[norm]["anchor_text"])`) handles the case where both a named and unnamed link point to the same URL — the named link wins because it has a longer anchor text.

**VALIDATE**: `python -m pytest tests/test_email_parser.py -k "test_empty_anchor" -v`

---

### Task 5 — UPDATE `parse_emails()`: strip trailing table-artifact lines from body

**Location**: `ingestion/email_parser.py`, `parse_emails()` section loop, after `body = re.sub(r'(\s*\|)+\s*$', '', body).strip()`

Current trailing strip (line 665):
```python
body = re.sub(r'(\s*\|)+\s*$', '', body).strip()
```

**IMPLEMENT**: After this existing regex, add a line-by-line trailing strip for lines whose stripped text is non-empty and is a table artifact:
```python
# Strip trailing lines that are table artifacts (e.g. '| |  SUBSCRIBE', '| |  GET IN TOUCH').
# _is_table_artifact checks pipe char ratio > 15% on non-whitespace chars.
# Only strip non-empty lines — blank trailing lines are already handled by .strip() above.
body_lines = body.split('\n')
while body_lines:
    last = body_lines[-1].strip()
    if last and _is_table_artifact(last):
        body_lines.pop()
    else:
        break
body = '\n'.join(body_lines).strip()
```

**GOTCHA**: `| |  SUBSCRIBE` → non-whitespace = `||SUBSCRIBE` (11 chars), pipes = 2, ratio ≈ 18% → `_is_table_artifact` returns True. `| |  GET IN TOUCH WITH US HERE` → non-ws = `||GETINTOUCHWITHUSHERE` (22 chars), pipes = 2, ratio ≈ 9% → returns False! This one slips through. To catch it, we need a secondary check: strip trailing lines that match a broader "pure structural label" pattern. See GOTCHA note below.

**REVISED IMPLEMENT** (covers both cases): After the existing regex line, add:
```python
body_lines = body.split('\n')
while body_lines:
    last = body_lines[-1].strip()
    if last and (
        _is_table_artifact(last)
        or re.match(r'^\|[\s\|]+\S', last) is not None  # '| |  TEXT' structural cell pattern
    ):
        body_lines.pop()
    else:
        break
body = '\n'.join(body_lines).strip()
```

**EXPLANATION of secondary pattern**: `r'^\|[\s\|]+\S'` matches lines that start with `|`, followed by whitespace and more `|` characters, then a non-whitespace char. This is the exact pattern of TDV table cell rows like `| |  SUBSCRIBE` and `| |  GET IN TOUCH WITH US HERE`. It does NOT match normal prose that happens to start with a pipe (which would be `| ` followed immediately by content, not another `|` pattern).

**VALIDATE**: `python -m pytest tests/test_email_parser.py -k "test_trailing_artifact" -v`

---

### Task 6 — UPDATE `_split_list_section()`: preserve link-free list items

**Location**: `ingestion/email_parser.py`, `_split_list_section()`, per-item loop (lines 406–424)

Current code:
```python
result: list[dict] = []
for raw in items_raw:
    best_by_norm: dict[str, dict] = {}
    for anchor, url in _MD_LINK_RE.findall(raw):
        if not anchor:              # skip empty-anchor image links
            continue
        if _is_boilerplate_url(url):
            continue
        norm = _normalize_url(url)
        if norm not in best_by_norm:
            best_by_norm[norm] = {"url": norm, "anchor_text": anchor}
        elif len(anchor) > len(best_by_norm[norm]["anchor_text"]):
            best_by_norm[norm]["anchor_text"] = anchor
    links = list(best_by_norm.values())
    clean_text = _MD_LINK_RE.sub(r'\1', raw).strip()
    if links and len(clean_text) >= _MIN_LIST_ITEM_CHARS:
        result.append({"text": clean_text, "links": links})

return result if len(result) >= 2 else None
```

**IMPLEMENT**: Track `linked_count` separately so link-free items can be included when a split is warranted. Only return the split result when `linked_count >= 2`:
```python
result: list[dict] = []
linked_count = 0
for raw in items_raw:
    best_by_norm: dict[str, dict] = {}
    for anchor, url in _MD_LINK_RE.findall(raw):
        if not anchor:              # skip empty-anchor image links
            continue
        if _is_boilerplate_url(url):
            continue
        norm = _normalize_url(url)
        if norm not in best_by_norm:
            best_by_norm[norm] = {"url": norm, "anchor_text": anchor}
        elif len(anchor) > len(best_by_norm[norm]["anchor_text"]):
            best_by_norm[norm]["anchor_text"] = anchor
    item_links = list(best_by_norm.values())
    clean_text = _MD_LINK_RE.sub(r'\1', raw).strip()
    if len(clean_text) >= _MIN_LIST_ITEM_CHARS:
        result.append({"text": clean_text, "links": item_links})
        if item_links:
            linked_count += 1

return result if linked_count >= 2 else None
```

**EXPLANATION**: A link-free item is now included in `result` (with `links=[]`) whenever it has enough text. However, the function still only returns the split list when `linked_count >= 2` — if fewer than 2 items have links, the caller processes the section as a unit (existing behavior). This preserves the invariant that splitting only happens for genuine aggregator sections.

**GOTCHA**: The `if not anchor: continue` guard is NOT changed here (Task 4 applies the empty-anchor capture to the *section-level* loop in `_extract_sections()` and separately to `_split_list_section()`, but these are different call sites). Ensure Task 4's empty-anchor capture is also applied to the `_split_list_section` link loop — that change is specified in Task 4. After both Task 4 and Task 6 are applied, the `_split_list_section` per-item loop should have Task 4's empty-anchor logic AND Task 6's `linked_count` tracking.

**VALIDATE**: `python -m pytest tests/test_email_parser.py -k "test_link_free_list" -v`

---

## TESTING STRATEGY

All tests use `_make_raw_email(html)` → `parse_emails([raw])` pattern from `tests/test_email_parser.py` (lines 264–280). Tests are unit-level and append to the existing file.

### Test 1: Unicode apostrophe boilerplate signal

```python
def test_boilerplate_unicode_apostrophe_dropped():
    """Section with U+2019 'TODAY\u2019S' in intro marker is dropped as boilerplate."""
    html = """<html><body>
    <p><strong>Welcome back.</strong> IN TODAY\u2019S NEWSLETTER</p>
    <p>Real story content here that is long enough to pass filters.</p>
    </body></html>"""
    raw = _make_raw_email(html)
    results = parse_emails([raw])
    # Intro/ToC section should be dropped; only the real story remains
    assert all("today\u2019s newsletter" not in (r.body or "").lower() for r in results)
```

### Test 2: `****` artifact stripping

```python
def test_bold_artifact_stripped_from_body():
    """'****' empty-bold artifacts from html2text are removed from body text."""
    html = """<html><body>
    <h1>Story headline</h1>
    <p>First paragraph with <strong></strong> trailing artifact.</p>
    </body></html>"""
    raw = _make_raw_email(html)
    results = parse_emails([raw])
    assert results
    assert '****' not in results[0].body
```

### Test 3: Theme label not absorbed into story body

```python
def test_theme_label_not_absorbed_into_story_body():
    """Short structural labels like '| HARDWARE' are not absorbed into the preceding story body."""
    html = """<html><body>
    <h1>Main story headline</h1>
    <p>Main story body text with enough content to pass the length filter and be kept.</p>
    <p>| HARDWARE</p>
    <h1>Next story headline</h1>
    <p>Next story body text.</p>
    </body></html>"""
    raw = _make_raw_email(html)
    results = parse_emails([raw])
    assert results
    # First story body must not contain the theme label
    assert 'HARDWARE' not in results[0].body
```

### Test 4: Empty-anchor image link captured

```python
def test_empty_anchor_image_link_captured():
    """Article image links rendered as [](url) by html2text are included in links list."""
    html = """<html><body>
    <h1>Story with image link</h1>
    <p><a href="https://example.com/article"><img src="https://img.example.com/photo.jpg" /></a></p>
    <p>Story body text with enough content to pass all filters and be included.</p>
    </body></html>"""
    raw = _make_raw_email(html)
    results = parse_emails([raw])
    assert results
    # The article URL behind the image should be in the links list
    assert any("example.com/article" in url for url in results[0].links)
```

### Test 5: Trailing table-artifact line stripped

```python
def test_trailing_table_artifact_line_stripped():
    """Trailing '| |  SUBSCRIBE'-style lines are stripped from the body."""
    html = """<html><body>
    <p>Valid story content about a podcast that has enough text to pass the length filter.</p>
    <p>| |  SUBSCRIBE</p>
    </body></html>"""
    raw = _make_raw_email(html)
    results = parse_emails([raw])
    assert results
    assert 'SUBSCRIBE' not in results[0].body
    assert results[0].body.strip()  # body is not empty after stripping


def test_trailing_get_in_touch_line_stripped():
    """Trailing '| |  GET IN TOUCH WITH US HERE' structural cell is stripped from body."""
    html = """<html><body>
    <p>If you want to advertise to our audience, get in touch with us here. Long enough to pass.</p>
    <p>| |  GET IN TOUCH WITH US HERE</p>
    </body></html>"""
    raw = _make_raw_email(html)
    results = parse_emails([raw])
    assert results
    assert 'GET IN TOUCH WITH US HERE' not in results[0].body
```

### Test 6: Link-free list item preserved in split

```python
def test_split_list_preserves_link_free_items():
    """A link-free bullet item in a multi-link list is not silently dropped."""
    html = """<html><body>
    <ul>
    <li><a href="https://example.com/a">Story A about something interesting and newsworthy</a></li>
    <li>Story B has no link but enough text to be a valid item worth preserving here</li>
    <li><a href="https://example.com/c">Story C about something else entirely newsworthy</a></li>
    </ul>
    </body></html>"""
    raw = _make_raw_email(html)
    results = parse_emails([raw])
    # All three items should appear — Story B (link-free) must not be silently dropped
    bodies = [r.body for r in results]
    assert any("Story A" in b for b in bodies)
    assert any("Story B" in b for b in bodies), "Link-free list item must not be dropped"
    assert any("Story C" in b for b in bodies)
```

---

## VALIDATION COMMANDS

### Level 1: Syntax check
```bash
python -c "import ingestion.email_parser; print('OK')"
```

### Level 2: Full test suite
```bash
python -m pytest tests/test_email_parser.py tests/test_deduplicator.py -v 2>&1 | tail -20
```

Expected: all existing tests pass (no regressions) + 7 new tests pass.

### Level 3: Targeted new tests only
```bash
python -m pytest tests/test_email_parser.py -k "unicode_apostrophe or bold_artifact or theme_label or empty_anchor or trailing_artifact or link_free" -v
```

### Level 4: Manual re-inspection

Run the manual test script against `the_deep_view.eml` (substitute actual path as used in prior runs):
```bash
python -c "
import sys; sys.path.insert(0, '.')
from ingestion.email_parser import parse_emails

with open('tests/fixtures/the_deep_view.eml', 'rb') as f:
    raw = f.read()

records = parse_emails([raw])
print(f'Total story records: {len(records)}')
print('=' * 80)
for i, r in enumerate(records):
    print(f'[{i+1}]')
    print(f'title      = {r.title!r}')
    print(f'links      = {r.links!r}')
    print(f'body       = {r.body!r}')
    print('-' * 80)
" 2>&1 | tee tests/test-results/$(date -u +%Y-%m-%dT%H-%M-%S)-phase5-results.txt
```

Expected improvements vs. `2026-04-04T01-35-27-test-results.txt`:
- Record [1] (intro/ToC with "IN TODAY'S NEWSLETTER") is now DROPPED — total record count decreases by 1
- Record [2] body no longer contains `****`
- Records [4] and [6] bodies no longer end with `| HARDWARE` / `| ENTERPRISE`
- Records [5] (and others with article images) now have the article URL in `links`
- Records [28] and [29] bodies no longer end with `| |  SUBSCRIBE` / `| |  GET IN TOUCH WITH US HERE`
- The Google Gemini "not ruling out ads" bullet appears as its own record (no longer silently dropped)

### Level 5: Specific spot-checks
```bash
python -c "
import sys; sys.path.insert(0, '.')
from ingestion.email_parser import parse_emails

with open('tests/fixtures/the_deep_view.eml', 'rb') as f:
    raw = f.read()

records = parse_emails([raw])
print('Total records:', len(records))
print()

# Check 1: intro/ToC dropped
intro_records = [r for r in records if 'today' in (r.body or '').lower() and 'newsletter' in (r.body or '').lower() and r.title is None and len(r.body) > 200]
print('Intro/ToC records (should be 0):', len(intro_records))

# Check 2: no **** artifacts
star_records = [r for r in records if '****' in (r.body or '')]
print('Records with **** artifact (should be 0):', len(star_records))

# Check 3: no theme label leakage
theme_records = [r for r in records if r.body and r.body.rstrip().endswith(('| HARDWARE', '| ENTERPRISE', '| BIG TECH', '| SPACE'))]
print('Records with theme label in body tail (should be 0):', len(theme_records))

# Check 4: no trailing SUBSCRIBE/GET IN TOUCH
footer_records = [r for r in records if 'SUBSCRIBE' in (r.body or '').split('\n')[-1] or 'GET IN TOUCH' in (r.body or '').split('\n')[-1]]
print('Records with trailing footer junk (should be 0):', len(footer_records))

# Check 5: Google Gemini bullet present
gemini_records = [r for r in records if 'Gemini' in (r.body or '') and 'ruling' in (r.body or '').lower()]
print('Google Gemini bullet present (should be >= 1):', len(gemini_records))
"
```

---

## MANUAL VERIFICATION CHECKLIST

- [ ] `python -c "import ingestion.email_parser; print('OK')"` prints `OK`
- [ ] All existing 68+ tests continue passing
- [ ] 7 new tests all pass (6 test functions: `test_boilerplate_unicode_apostrophe_dropped`, `test_bold_artifact_stripped_from_body`, `test_theme_label_not_absorbed_into_story_body`, `test_empty_anchor_image_link_captured`, `test_trailing_table_artifact_line_stripped`, `test_trailing_get_in_touch_line_stripped`, `test_split_list_preserves_link_free_items`)
- [ ] Level 5 spot-checks: intro/ToC = 0, `****` artifacts = 0, theme label tail = 0, trailing footer = 0, Gemini bullet >= 1

---

## VALIDATION OUTPUT REFERENCE

- Item to check:
  `python -c "import ingestion.email_parser; print('OK')"`
  Expected output or result:
  `OK`

- Item to check:
  `python -m pytest tests/test_email_parser.py tests/test_deduplicator.py -v 2>&1 | tail -5`
  Expected output or result:
  All tests pass, including 7 new tests. Final line: `N passed` (where N ≥ 75).

- Item to check:
  `python -m pytest tests/test_email_parser.py -k "unicode_apostrophe or bold_artifact or theme_label or empty_anchor or trailing_artifact or link_free" -v`
  Expected output or result:
  7 tests collected, 7 passed, 0 failed.

- Item to check:
  Level 4 manual run — total record count vs. `2026-04-04T01-35-27-test-results.txt` (29 records)
  Expected output or result:
  Total story records: 27 or fewer (intro/ToC dropped = -1; possibly more reductions from improved filtering)

- Item to check:
  Level 5 spot-checks output
  Expected output or result:
  ```
  Intro/ToC records (should be 0): 0
  Records with **** artifact (should be 0): 0
  Records with theme label in body tail (should be 0): 0
  Records with trailing footer junk (should be 0): 0
  Google Gemini bullet present (should be >= 1): 1
  ```

- Item to check:
  File `ingestion/email_parser.py` modified (6 changes: `_is_boilerplate_segment`, `parse_emails` `****` strip, inner assembly loop min-length, `_extract_sections` empty-anchor, `parse_emails` trailing artifact strip, `_split_list_section` `linked_count`)
  Expected output or result:
  File exists at `ingestion/email_parser.py` with all 6 changes applied.

- Item to check:
  File `tests/test_email_parser.py` modified (7 new test functions appended)
  Expected output or result:
  File exists at `tests/test_email_parser.py` with 7 new test functions appended at end.

---

## ROLLBACK CONSIDERATIONS

All changes are in `email_parser.py` and `test_email_parser.py`. To revert: `git checkout ingestion/email_parser.py tests/test_email_parser.py`.

No database, no config, no migration changes.

---

## ACCEPTANCE CRITERIA

- [ ] `_is_boilerplate_segment()` normalizes U+2018/U+2019/U+201C/U+201D before lowercasing
- [ ] `****` clusters removed from body in `parse_emails()` section loop
- [ ] Story assembly inner loop breaks on `len(clean_next) < _MIN_SECTION_CHARS`
- [ ] Empty-anchor `[](url)` links captured in `_extract_sections()` and `_split_list_section()`
- [ ] Trailing `| |  SUBSCRIBE` and `| |  GET IN TOUCH WITH US HERE` lines stripped from body
- [ ] Link-free list items preserved when `_split_list_section` splits a multi-link list
- [ ] All 7 new regression tests pass
- [ ] Zero regressions in existing test suite (all previously passing tests still pass)
- [ ] Level 4 manual output shows no `****`, no theme label tails, no trailing footer lines, intro/ToC dropped

---

## NOTES

**Out of scope in this plan:**
- Records [22]–[27] (quiz/poll/results): interactive content. Body of [22] is `'Option A  |  Option B'`  (pipe ratio ≈ 7%, passes table artifact check). These require semantic understanding → LLM filter.
- Records [4] and [6] sponsor bodies: after Issue 3 fix, theme labels will no longer leak into them. The sponsor bodies themselves (Airia, Slack) will still appear as records; the LLM filter will drop them.
- Record [3] ("It's hard to build a robot...") appearing as separate record from record [2]: the TDV newsletter structure places a sponsor section between the main article and its "Our Deeper View" continuation. The assembly loop correctly stops at the sponsor heading. Merging across a sponsor boundary would require TDV-specific layout knowledge. Deferred.
- The `_is_sparse_link_section` check uses `_SPARSE_LINK_STRIP_RE` which explicitly strips empty anchors (`\[([^\]]*)\]\([^\)]+\)`). After Task 4, empty-anchor links are collected but `_is_sparse_link_section` will still strip them when computing bare text — this is correct behavior.

**Confidence score: 8/10** — all six root causes are confirmed and fixes are surgical. The main risk is the `| |  GET IN TOUCH WITH US HERE` pattern — the pipe-ratio check gives ~9%, below the 15% threshold, so the secondary regex pattern `r'^\|[\s\|]+\S'` is required. Verify this pattern doesn't over-fire on legitimate prose that starts with `|` (rare in practice).
