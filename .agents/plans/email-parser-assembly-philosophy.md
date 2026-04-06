# Feature: email-parser-assembly-philosophy (Phase 6)

The following plan should be complete, but validate codebase patterns and line numbers before implementing — the file has been modified across multiple phases.

Pay special attention to the exact current state of `_BOILERPLATE_SEGMENT_SIGNALS`, the inner collection loop in `_extract_sections`, and the body post-processing block in `parse_emails`. Read those sections before touching them.

## Feature Description

A philosophy-level correction to the email parser's story assembly stage. The parser currently uses sponsor/content-judgment signals to break story assembly and drop sections. This causes article continuations to be silently severed when a sponsor section appears between an article's main body and its analytical continuation (e.g., TDV's "Our Deeper View" sections). The parser should only make structural decisions — assembling coherent story units and discarding obvious layout junk. All content-level keep/drop judgments belong to the downstream LLM filter.

Additionally fixes two body-text quality defects: trailing whitespace on body lines (html2text table-cell artifact) and markdown links with nested bracket anchor text not being extracted or stripped.

## User Story

As a newsletter digest user
I want each article assembled into a single complete record — including analytical sections that follow a sponsor insertion
So that the LLM filter sees the full article context and can make informed keep/drop decisions

## Problem Statement

Three confirmed defects, one philosophy misalignment:

1. **Philosophy**: `_is_boilerplate_segment` in the inner collection loop causes premature `break` when a sponsor-labeled section appears between an article's main body and its continuation. The LLM downstream never sees the continuation. This is a story-assembly / boundary-detection problem — not a content-filtering problem — and must be solved at the parser level.

2. **Sponsor signals in `_BOILERPLATE_SEGMENT_SIGNALS`**: "together with" and "brought to you by" are content-judgment signals. When they appear as standalone sections (not inside a story's heading-led collection), they cause those sections to be dropped without LLM review. These signals belong to the LLM filter, not the parser.

3. **Trailing `   \n` whitespace on body lines**: html2text appends two or more trailing spaces before `\n` when converting table-cell content. These survive all current post-processing and clutter every body field.

4. **Nested-bracket markdown links not extracted**: `_MD_LINK_RE = r'\[([^\]]*)\]\(https?://...\)'` uses `[^\]]*` (no nested `[` or `]` allowed). Anchor text like `"not ruling them [ads] out"` contains `[ads]` — the regex stops at the first `]`, failing to match. The URL ends up embedded as raw markdown syntax in body text, and `links` is empty.

## Scope

- In scope:
  - Remove `_is_boilerplate_segment` from the inner collection loop (Tasks 1)
  - Remove sponsor/interactive signals from `_BOILERPLATE_SEGMENT_SIGNALS` (Task 2)
  - Strip trailing whitespace per line from body (Task 3)
  - Update `_MD_LINK_RE` to handle one level of nested brackets (Task 4)
  - Update docstrings to reflect the new assembly philosophy (Task 1 and Task 2)
  - Tests for all four changes (Task 5)
- Out of scope:
  - Changes to `processing/deduplicator.py`, `ai/claude_client.py`, or any other file
  - Records [22]–[27] (quiz/poll/results) — LLM filter
  - Podcast promo / advertiser outreach records — LLM filter
  - Two-or-more levels of nested bracket nesting in links (extremely rare in practice)

## Solution Statement

**Task 1**: Delete the `if _is_boilerplate_segment(next_sec): break` line from the inner collection loop. The loop will now stop only at headings, table artifacts, and short structural labels — never at content-based signals. Sponsor sections without their own `#` heading are collected into the story that precedes them, and any unheaded continuation sections after the sponsor are also collected. The LLM filter then sees the full assembled content.

**Task 2**: Remove "together with", "brought to you by", "thanks for reading", "before you go", "a quick poll" from `_BOILERPLATE_SEGMENT_SIGNALS`. These are content-adjacent; they must not cause parser-level drops. Update the comment block above the tuple to reflect the narrower scope.

**Task 3**: After all other body processing in `parse_emails`, add `body = '\n'.join(line.rstrip() for line in body.split('\n'))` to strip html2text's trailing-space artifacts from each line.

**Task 4**: Replace `_MD_LINK_RE` with a regex that permits one level of nested brackets in the anchor text: `r'\[([^\[\]]*(?:\[[^\[\]]*\][^\[\]]*)*)\]\((https?://[^\)]+)\)'`. This is a drop-in replacement — all existing call sites (`.findall`, `.sub`, `.search`) work identically.

## Feature Metadata

**Feature Type**: Bug Fix + Refactor
**Estimated Complexity**: Low
**Primary Systems Affected**: `ingestion/email_parser.py`, `tests/test_email_parser.py`
**Dependencies**: None new
**Assumptions**:
- The IREN sponsor section between the Nvidia article and its "Our Deeper View" continuation does NOT start with a `#` markdown heading (if it did, `_is_story_heading` would still break collection — a separate problem). Verify by spot-checking the Level 4 output after implementation.
- `_SPARSE_LINK_STRIP_RE` (line ~257) uses the old `[^\]]*` pattern and is intentionally NOT updated here — it is used only for ToC sparse-link detection and the looser threshold (`len(bare) < 30`) makes nested-bracket edge cases harmless.

---

## CONTEXT REFERENCES

### Relevant Codebase Files — MUST READ BEFORE IMPLEMENTING

- `ingestion/email_parser.py` (lines 80–85) — `_MIN_SECTION_CHARS`, `_MD_LINK_RE` (the regex to replace)
- `ingestion/email_parser.py` (lines 113–152) — `_BOILERPLATE_SEGMENT_SIGNALS` current tuple, comment block above it explaining scope
- `ingestion/email_parser.py` (lines 236–249) — `_is_boilerplate_segment()`: reads `_BOILERPLATE_SEGMENT_SIGNALS`
- `ingestion/email_parser.py` (lines 468–520) — full inner collection loop: exact location of the `_is_boilerplate_segment` break to remove
- `ingestion/email_parser.py` (lines 694–733) — `parse_emails()` section loop: location for trailing whitespace strip (after the trailing-artifact strip block, before `links = _collect_links(...)`)
- `ingestion/email_parser.py` (lines 257–275) — `_SPARSE_LINK_STRIP_RE` and `_is_sparse_link_section()` — NOT to be changed, for reference only
- `tests/test_email_parser.py` (lines 264–275) — `_make_raw_email()` helper, test pattern for all new tests

### New Files to Create

None. Only modify existing files.

### Files to Modify

- `ingestion/email_parser.py` — four targeted changes
- `tests/test_email_parser.py` — new test functions appended at end

### Patterns to Follow

**Test pattern** (from `tests/test_email_parser.py` line 264):
```python
def test_name():
    html = (
        "<html><body>"
        "...HTML here..."
        "</body></html>"
    )
    raw = _make_raw_email(html)
    results = parse_emails([raw])
    assert ...
```

**Signal removal pattern**: Remove specific entries from the `_BOILERPLATE_SEGMENT_SIGNALS` tuple; update the comment block above it to reflect the narrower scope definition.

**Regex constant update**: `_MD_LINK_RE` is defined at line ~84 as a module-level compiled regex. Replace the pattern string in-place — no import changes needed.

---

## IMPLEMENTATION PLAN

### Phase 1: Philosophy and signal changes

Remove `_is_boilerplate_segment` from inner loop. Remove content-judgment signals from `_BOILERPLATE_SEGMENT_SIGNALS`.

### Phase 2: Body quality fixes

Strip trailing whitespace per line. Update `_MD_LINK_RE` for nested brackets.

### Phase 3: Tests

Regression tests for all four changes, plus existing suite.

---

## STEP-BY-STEP TASKS

### Task 1 — REMOVE `_is_boilerplate_segment` break from inner collection loop in `_extract_sections()`

**Location**: `ingestion/email_parser.py`, inner `while` loop beginning around line 482, inside the `if _is_story_heading(sec):` branch

**Current code to find** (exact match required for Edit tool):
```python
                # Stop collecting at boilerplate boundaries (sponsor sections etc.)
                if _is_boilerplate_segment(next_sec):
                    break
                # Stop collecting at structural noise (table artifacts — avoids
                # absorbing | TOGETHER WITH AIRIA etc. into the story)
                clean_next = _MD_LINK_RE.sub(r'\1', next_sec).strip()
```

**IMPLEMENT**: Remove the three boilerplate-break lines and update the comment on the following noise-check block to reflect the new sole purpose:
```python
                # Stop collecting at structural noise only (table artifacts, short labels).
                # Content-judgment signals (sponsor labels, sign-offs) are intentionally NOT
                # break conditions — the LLM filter handles content keep/drop decisions.
                clean_next = _MD_LINK_RE.sub(r'\1', next_sec).strip()
```

**GOTCHA**: The comment `# absorbing | TOGETHER WITH AIRIA etc. into the story` refers to the table-artifact check below, not the boilerplate check. Keep that check; only remove the `_is_boilerplate_segment` block and refresh the comment.

**VALIDATE**: `python -c "import ingestion.email_parser; print('OK')"`

---

### Task 2 — REMOVE sponsor/interactive signals from `_BOILERPLATE_SEGMENT_SIGNALS`

**Location**: `ingestion/email_parser.py`, lines 121–152

**Signals to REMOVE**:
- `"together with"` — sponsor partner label; content-adjacent
- `"brought to you by"` — sponsor partner label; content-adjacent
- `"thanks for reading"` — outro sign-off; LLM decides
- `"before you go"` — interactive section lead-in; LLM decides
- `"a quick poll"` — interactive section; LLM decides

**Signals to KEEP** (all others):
- All subscription management signals (`"manage your subscriptions"`, `"manage your email"`, etc.)
- `"all rights reserved"`, `"referral link"`, `"forward this email"`, `"share this newsletter"`, `"recommend this newsletter"` — structural/infrastructure, never story content
- `"in today's issue"`, `"in this issue"`, `"what's inside"`, `"today's top stories"`, `"in today's newsletter"` — table-of-contents signals; intro sections are navigation, not stories
- `"support this newsletter"` — subscription/fundraising infrastructure; keep

**IMPLEMENT**: Remove the five signals listed above. Update the comment block immediately above the tuple to reflect the narrowed scope. The updated comment should make clear that sponsor labels, sign-offs, and interactive sections are deliberately excluded — those belong to the LLM filter.

Replace the `# Sponsor / partner labels` and `# Poll / interactive sections` comment blocks and their entries, and the sign-off entry under `# Newsletter outro / sign-off`. The `"in today's newsletter"` entry stays; only `"thanks for reading"` is removed from that group.

**GOTCHA**: `"together with"` and `"brought to you by"` remain in `_BOILERPLATE_ANCHORS` (lines ~54-55) — those are anchor-text filters for link extraction and are a separate concern. Do NOT touch `_BOILERPLATE_ANCHORS`.

**VALIDATE**: `python -m pytest tests/test_email_parser.py -k "together_with" -v` (existing test `test_together_with_section_dropped` will now FAIL — see Task 5 for the replacement test)

**NOTE ON EXISTING TEST**: `test_together_with_section_dropped` (currently passing) tests that a "together with" section is dropped. After this change, it should NOT be dropped — the test must be replaced with a test verifying it is KEPT. Do this in Task 5.

---

### Task 3 — UPDATE `parse_emails()`: strip trailing whitespace per body line

**Location**: `ingestion/email_parser.py`, `parse_emails()` section loop, immediately before `links = _collect_links(section.get("links", []))`

Current surrounding context (find this exact block):
```python
            body = '\n'.join(body_lines).strip()
            if not body:                                         # skip if body is now empty
                continue
            links = _collect_links(section.get("links", []))
```

**IMPLEMENT**: Insert the trailing-whitespace strip between `body = '\n'.join(body_lines).strip()` and `if not body:`:
```python
            body = '\n'.join(body_lines).strip()
            # Strip trailing whitespace from each line: html2text appends '  ' (two spaces)
            # before '\n' in table-cell content, producing '   \n' artifacts in body text.
            body = '\n'.join(line.rstrip() for line in body.split('\n'))
            if not body:                                         # skip if body is now empty
                continue
            links = _collect_links(section.get("links", []))
```

**GOTCHA**: The `body.split('\n')` here is different from the earlier `body_lines` loop (which popped trailing artifact lines). Do NOT merge them — keep them as separate passes with their own semantics.

**VALIDATE**: `python -m pytest tests/test_email_parser.py -k "trailing_whitespace" -v`

---

### Task 4 — UPDATE `_MD_LINK_RE` to handle nested brackets in anchor text

**Location**: `ingestion/email_parser.py`, line 84

Current:
```python
_MD_LINK_RE = re.compile(r'\[([^\]]*)\]\((https?://[^\)]+)\)')
```

**IMPLEMENT**: Replace with a pattern that allows exactly one level of nested `[...]` in the anchor text:
```python
_MD_LINK_RE = re.compile(r'\[([^\[\]]*(?:\[[^\[\]]*\][^\[\]]*)*)\]\((https?://[^\)]+)\)')
```

**Pattern explanation**:
- `\[` — opening `[`
- `(` — capture group (anchor text)
  - `[^\[\]]*` — zero or more chars that are neither `[` nor `]`
  - `(?:` — non-capturing group for one nested bracket pair
    - `\[[^\[\]]*\]` — a nested `[inner]` (no further nesting)
    - `[^\[\]]*` — chars after the nested bracket
  - `)*` — zero or more nested bracket pairs
- `)` — end capture group
- `\]` — closing `]`
- `\(` — opening `(`
- `(https?://[^\)]+)` — URL capture group (unchanged)
- `\)` — closing `)`

**Verification**: For `["not ruling them [ads] out"](https://example.com)`:
- `[^\[\]]*` matches `"not ruling them ` (stops before `[`)
- `\[[^\[\]]*\]` matches `[ads]`
- `[^\[\]]*` matches ` out"`
- Full anchor capture: `"not ruling them [ads] out"` ✓

For `[simple anchor](https://example.com)`:
- `[^\[\]]*` matches `simple anchor`, nested group matches zero times ✓

**GOTCHA**: This is a drop-in replacement. ALL existing call sites — `.findall(sec)`, `.sub(r'\1', sec)`, `.search(next_sec)` — work identically. The `.sub(r'\1', text)` replacement correctly produces the anchor text including any inner `[nested]` portions (since `\1` is the full outer capture group). For `["text [ads] more"](url)`, the substitution produces `"text [ads] more"` which is the correct clean prose.

**GOTCHA**: `_SPARSE_LINK_STRIP_RE` at line ~257 uses a different pattern (`[^\]]*`) and is intentionally NOT updated — its looser matching is harmless for its specific use case (sparse ToC detection).

**VALIDATE**: `python -m pytest tests/test_email_parser.py -k "nested_bracket" -v`

---

### Task 5 — UPDATE and ADD tests in `test_email_parser.py`

**Location**: `tests/test_email_parser.py`

#### 5a — REPLACE `test_together_with_section_dropped`

Find and replace the existing test that asserts "together with" sections are dropped. The new assertion is the inverse: a "together with" standalone section must appear in the output (it is no longer filtered).

Find this test (by name — exact line may vary):
```python
def test_together_with_section_dropped():
```

Replace its body with:
```python
def test_together_with_section_not_dropped():
    """After the philosophy change, 'together with' sections are no longer dropped.
    Sponsor labels are content-adjacent; keep/drop is the LLM filter's job.
    """
    html = (
        "<html><body>"
        "<p>Together with Sponsor Corp. This section used to be dropped but now passes through.</p>"
        "<p>Valid story content appears in a separate section here.</p>"
        "</body></html>"
    )
    raw = _make_raw_email(html)
    results = parse_emails([raw])
    # The sponsor-labeled section must NOT be silently discarded
    bodies = " ".join(r.body for r in results)
    assert "Together with Sponsor Corp" in bodies, (
        "Sponsor-labeled section was dropped by parser — should be passed to LLM filter"
    )
```

**IMPORTANT**: Also rename the function — `test_together_with_section_dropped` → `test_together_with_section_not_dropped`. This is the same function body location, just a name change + inverted assertion.

#### 5b — ADD `test_sponsor_separated_continuation_assembled`

Verifies the core fix: an article with a sponsor section between its main body and a continuation assembles into a single record.

```python
def test_sponsor_separated_continuation_assembled():
    """A story continuation separated from its heading by a sponsor section is assembled into one record.

    TDV structure: # Article heading → main body → sponsor content → 'Our Deeper View' continuation.
    The inner collection loop must not break at the sponsor section.
    """
    html = (
        "<html><body>"
        "<h1>Main article heading</h1>"
        "<p>First part of the article body with enough content to be valid and pass filters.</p>"
        "<p>Together with Sponsor Corp. This is the sponsor content that was previously causing a break.</p>"
        "<p>This is the analytical continuation that was previously severed into a separate record.</p>"
        "</body></html>"
    )
    raw = _make_raw_email(html)
    results = parse_emails([raw])
    # All three sections should be in ONE record (same heading-led story)
    assert len(results) == 1, f"Expected 1 assembled record, got {len(results)}"
    assert "First part" in results[0].body
    assert "analytical continuation" in results[0].body
```

#### 5c — ADD `test_trailing_whitespace_stripped_from_body`

```python
def test_trailing_whitespace_stripped_from_body():
    """Body lines must not have trailing whitespace (html2text table-cell artifact)."""
    html = (
        "<html><body>"
        "<p>First sentence of the story body content here.  </p>"
        "<p>Second sentence with trailing spaces.   </p>"
        "</body></html>"
    )
    raw = _make_raw_email(html)
    results = parse_emails([raw])
    assert results
    for line in results[0].body.split('\n'):
        assert line == line.rstrip(), f"Line has trailing whitespace: {line!r}"
```

#### 5d — ADD `test_nested_bracket_anchor_link_extracted`

```python
def test_nested_bracket_anchor_link_extracted():
    """A markdown link whose anchor text contains nested brackets is correctly extracted.

    Example: ["not ruling them [ads] out"](https://example.com/article)
    The URL must appear in links and must NOT appear as raw markdown in body.
    """
    html = (
        "<html><body>"
        '<p>Google is <a href="https://example.com/gemini">\'not ruling them [ads] out\'</a>'
        " of Gemini, according to Wired.</p>"
        "</body></html>"
    )
    raw = _make_raw_email(html)
    results = parse_emails([raw])
    assert results
    assert any("example.com/gemini" in url for url in results[0].links), (
        "Nested-bracket anchor link URL not extracted into links list"
    )
    assert "](https://" not in results[0].body, (
        "Raw markdown link syntax still present in body"
    )
```

**VALIDATE**: `python -m pytest tests/test_email_parser.py tests/test_deduplicator.py -v 2>&1 | tail -20`

---

## TESTING STRATEGY

### Unit Tests

All tests use `_make_raw_email(html)` → `parse_emails([raw])` from `tests/test_email_parser.py`.

### Edge Cases to cover

- Sponsor section between article parts → one record (Task 5b)
- Sponsor section as standalone (no preceding story heading) → not dropped (Task 5a)
- Body line with trailing spaces → no trailing spaces after processing (Task 5c)
- Nested-bracket anchor → URL in `links`, not in `body` (Task 5d)
- Existing test `test_together_with_section_dropped` → renamed and inverted (Task 5a)
- All existing tests must continue passing (no regression)

### Regression concern: `test_together_with_section_dropped`

This is the only existing test whose assertion must change. The test currently asserts that a "together with" section IS dropped. After Task 2, it is NOT dropped. Task 5a renames and inverts it. This is an intentional, expected change — not a regression.

---

## VALIDATION COMMANDS

### Level 1: Syntax check
```bash
python -c "import ingestion.email_parser; print('OK')"
```

### Level 2: Full test suite
```bash
python -m pytest tests/test_email_parser.py tests/test_deduplicator.py -v 2>&1 | tail -25
```

Expected: all tests pass including 4 new tests. The renamed `test_together_with_section_not_dropped` must pass (was `test_together_with_section_dropped`).

### Level 3: Targeted new tests
```bash
python -m pytest tests/test_email_parser.py -k "together_with or sponsor_separated or trailing_whitespace or nested_bracket" -v
```

Expected: 4 tests collected, 4 passed.

### Level 4: Manual re-inspection against the_deep_view.eml
```bash
python -c "
import sys; sys.path.insert(0, '.')
from ingestion.email_parser import parse_emails

with open('debug_samples/the_deep_view.eml', 'rb') as f:
    raw = f.read()

records = parse_emails([raw])
print(f'Total story records: {len(records)}')
print()
for i, r in enumerate(records):
    print(f'[{i+1}]')
    print(f'title      = {r.title!r}')
    print(f'links      = {len(r.links)} links')
    print(f'body       = {r.body!r}')
    print('-' * 80)
" 2>&1 | tee tests/test-results/$(date -u +%Y-%m-%dT%H-%M-%S)-phase6-results.txt
```

### Level 5: Spot-checks
```bash
python -c "
import sys; sys.path.insert(0, '.')
from ingestion.email_parser import parse_emails

with open('debug_samples/the_deep_view.eml', 'rb') as f:
    raw = f.read()

records = parse_emails([raw])
print('Total records:', len(records))

# Check 1: body lines have no trailing whitespace
trailing_ws_records = [r for r in records if any(line != line.rstrip() for line in r.body.split('\n'))]
print('Records with trailing whitespace in body lines (should be 0):', len(trailing_ws_records))

# Check 2: Gemini/Google bullet link extracted (no raw markdown link syntax)
gemini_records = [r for r in records if 'Gemini' in (r.body or '') and 'ruling' in (r.body or '').lower()]
print('Google Gemini bullet records (should be >= 1):', len(gemini_records))
if gemini_records:
    r = gemini_records[0]
    print(f'  body = {r.body!r}')
    print(f'  links = {r.links!r}')
    print(f'  raw markdown in body: {\"](https://\" in r.body}')

# Check 3: Nvidia robots article continuations assembled
nvidia_records = [r for r in records if r.title and 'robotics' in r.title.lower()]
print('Nvidia robotics article records (should be 1 assembled record):', len(nvidia_records))
if nvidia_records:
    body = nvidia_records[0].body
    print(f'  body length: {len(body)} chars')
    print(f'  contains IREN section: {\"IREN\" in body}')
    print(f'  contains continuation: {\"hard to build\" in body.lower()}')
"
```

---

## MANUAL VERIFICATION CHECKLIST

- [ ] `python -c "import ingestion.email_parser; print('OK')"` prints `OK`
- [ ] All existing tests pass (no regressions beyond renamed `test_together_with_section_not_dropped`)
- [ ] 4 new tests pass: `test_together_with_section_not_dropped`, `test_sponsor_separated_continuation_assembled`, `test_trailing_whitespace_stripped_from_body`, `test_nested_bracket_anchor_link_extracted`
- [ ] Level 5 spot-checks: trailing whitespace = 0, Gemini bullet extracted, Nvidia robotics record assembled

---

## ROLLBACK CONSIDERATIONS

All changes in `email_parser.py` and `test_email_parser.py`. To revert: `git checkout ingestion/email_parser.py tests/test_email_parser.py`. No database, no config, no migration.

---

## ACCEPTANCE CRITERIA

- [ ] `_is_boilerplate_segment` removed from inner collection loop
- [ ] "together with", "brought to you by", "thanks for reading", "before you go", "a quick poll" removed from `_BOILERPLATE_SEGMENT_SIGNALS`
- [ ] `_MD_LINK_RE` updated to handle one level of nested brackets
- [ ] Trailing whitespace stripped per body line in `parse_emails()`
- [ ] `test_together_with_section_dropped` renamed to `test_together_with_section_not_dropped` with inverted assertion
- [ ] 4 new tests pass
- [ ] Zero regressions in existing suite
- [ ] Level 4: Nvidia robots article and continuation appear in one record (body contains both main article text and continuation text, with or without IREN sponsor content between them)
- [ ] Level 5: trailing whitespace = 0, Gemini bullet has URL in `links` and no `](https://` in body

---

## VALIDATION OUTPUT REFERENCE

- Item to check:
  `python -c "import ingestion.email_parser; print('OK')"`
  Expected output or result:
  `OK`

- Item to check:
  `python -m pytest tests/test_email_parser.py tests/test_deduplicator.py -v 2>&1 | tail -5`
  Expected output or result:
  Final line: `N passed` (where N = prior count + 4 new tests). Zero failures. `test_together_with_section_not_dropped` in passing list (replacing `test_together_with_section_dropped`).

- Item to check:
  `python -m pytest tests/test_email_parser.py -k "together_with or sponsor_separated or trailing_whitespace or nested_bracket" -v`
  Expected output or result:
  ```
  tests/test_email_parser.py::test_together_with_section_not_dropped PASSED
  tests/test_email_parser.py::test_sponsor_separated_continuation_assembled PASSED
  tests/test_email_parser.py::test_trailing_whitespace_stripped_from_body PASSED
  tests/test_email_parser.py::test_nested_bracket_anchor_link_extracted PASSED
  4 passed
  ```

- Item to check:
  Level 5 spot-check: trailing whitespace in body lines
  Expected output or result:
  `Records with trailing whitespace in body lines (should be 0): 0`

- Item to check:
  Level 5 spot-check: Gemini bullet link
  Expected output or result:
  `Google Gemini bullet records (should be >= 1): 1`
  `  raw markdown in body: False`
  `  links = [...]` (non-empty list containing a URL)

- Item to check:
  Level 5 spot-check: Nvidia robotics article assembly
  Expected output or result:
  `Nvidia robotics article records (should be 1 assembled record): 1`
  `  body length: [substantially longer than the Phase 5 version, >1000 chars]`
  `  contains continuation: True`

- Item to check:
  File `ingestion/email_parser.py` modified (4 changes: inner loop boilerplate break removed, 5 signals removed from tuple, trailing whitespace strip added, `_MD_LINK_RE` updated)
  Expected output or result:
  File exists at `ingestion/email_parser.py` with all 4 changes applied.

- Item to check:
  File `tests/test_email_parser.py` modified (`test_together_with_section_dropped` replaced + 3 new test functions appended)
  Expected output or result:
  File exists at `tests/test_email_parser.py` with the renamed/inverted test and 3 new test functions at end.

---

## NOTES

**Why NOT remove all boilerplate signals from the inner loop as a break condition**: The remaining signals (email management, ToC) do not typically appear as mid-story sections in the email bodies we are processing. They appear as standalone top/bottom sections and are already handled by the standalone filter in the second loop. Removing the entire boilerplate check from the inner loop is a no-op for these signals in practice, but the explicit removal of the line makes the intent clear and prevents future signals from accidentally being added with assembly-break behavior.

**Why NOT remove ToC signals from `_BOILERPLATE_SEGMENT_SIGNALS`**: ToC/intro sections ("in today's newsletter", "in today's issue") are not story content — they are navigation. The parser correctly drops them. The user confirmed in Phase 5 feedback that dropping the TDV intro/ToC was correct behavior. These are structural signals, not content-judgment signals.

**`_is_boilerplate_segment` in `_split_list_section`**: After Task 2, the `_is_boilerplate_segment` check inside `_split_list_section` (which filters individual split list items) will no longer drop items containing "together with" etc. This is the desired behavior — the LLM decides.

**Confidence score: 9/10** — all root causes are confirmed, fixes are surgical and independent. The main uncertainty is whether the IREN sponsor section in the TDV email has its own `#` heading. If it does, the inner loop would still stop at it (via `_is_story_heading`), and the Nvidia continuation would still be separate. The Level 5 spot-check `contains continuation: True` will confirm this either way.
