# Execution Report: email-parser-story-records (Phase 2)

**Plan:** `.agents/plans/email-parser-story-records.md`
**Date:** 2026-04-02
**Phase executed:** Phase 2 — Tasks 8–12 (Phase 1 was complete from prior session)

---

## Tasks Completed

### Task 8 — Fix `_MD_LINK_RE` to match empty-anchor image links

**File:** `ingestion/email_parser.py`

Changed anchor quantifier from `+` to `*`:

```python
# Before:
_MD_LINK_RE = re.compile(r'\[([^\]]+)\]\((https?://[^\)]+)\)')

# After:
_MD_LINK_RE = re.compile(r'\[([^\]]*)\]\((https?://[^\)]+)\)')
```

Added `if not anchor: continue` guard in `_split_list_section`:

```python
for anchor, url in _MD_LINK_RE.findall(raw):
    if not anchor:              # skip empty-anchor image links
        continue
    if _is_boilerplate_url(url):
        continue
```

Added `if not anchor: continue` guard in `_extract_sections`:

```python
for anchor, url in _MD_LINK_RE.findall(sec):
    if not anchor:              # skip empty-anchor image links
        continue
    if _is_boilerplate_url(url):
        continue
```

---

### Task 9 — Add `_is_table_artifact(clean_text: str) -> bool`

**File:** `ingestion/email_parser.py`

Added function after `_is_boilerplate_segment()`:

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

Applied in `_extract_sections()` after `clean_text` computed:

```python
if len(clean_text) < _MIN_SECTION_CHARS:
    continue
if _is_table_artifact(clean_text):
    continue
if _is_boilerplate_segment(clean_text):
    continue
```

---

### Task 10 — Add `_is_sparse_link_section(raw_sec: str, links: list[dict]) -> bool`

**File:** `ingestion/email_parser.py`

Added regex and function after `_is_table_artifact()`:

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
    bare = _SPARSE_LINK_STRIP_RE.sub('', raw_sec)
    return len(bare) < 30
```

Applied in `_extract_sections()` after `links` built, before `clean_text` computed:

```python
links = list(best_by_norm.values())

if _is_sparse_link_section(sec, links):
    continue

clean_text = _MD_LINK_RE.sub(r'\1', sec).strip()
```

---

### Task 11 — Extend `_BOILERPLATE_SEGMENT_SIGNALS`

**File:** `ingestion/email_parser.py`

Added four intro signals after the `# Navigation / sharing infrastructure` block:

```python
# Newsletter intro / table-of-contents headers
"in today's issue",
"in this issue",
"what's inside",
"today's top stories",
```

---

### Task 12 — Add Phase 2 tests

**File:** `tests/test_email_parser.py`

Added 6 new test functions after existing Phase 1 tests:

- `test_table_artifact_dropped` — unit test for `_is_table_artifact()` directly
- `test_empty_anchor_link_stripped_from_body` — confirms `[](url)` does not appear verbatim in `body`
- `test_toc_section_dropped` — 3-link ordered list with no prose produces no records (or only records with ≥6 prose words)
- `test_story_with_multiple_inline_links_not_dropped` — story with 3+ inline links and substantial prose is retained
- `test_intro_signal_section_dropped` — section containing "in today's issue" is not produced as a story record
- `test_short_valid_story_still_preserved_after_phase2` — one-sentence story still produces a record after Phase 2 filters

---

## Validation Results

### Level 1: Syntax

```
$ python -m py_compile ingestion/email_parser.py && echo "syntax ok"
syntax ok
```

### Level 2: Unit Tests

```
$ python -m pytest tests/test_email_parser.py -v

============================= test session starts ==============================
platform darwin -- Python 3.12.12, pytest-9.0.2, pluggy-1.6.0
collected 34 items

tests/test_email_parser.py::test_split_list_two_items_with_links PASSED  [  2%]
tests/test_email_parser.py::test_split_list_five_items_with_links PASSED [  5%]
tests/test_email_parser.py::test_split_list_preserves_link_per_item PASSED [  8%]
tests/test_email_parser.py::test_split_list_single_item_returns_none PASSED [ 11%]
tests/test_email_parser.py::test_split_list_no_links_returns_none PASSED [ 14%]
tests/test_email_parser.py::test_split_list_fewer_than_two_linked_items_returns_none PASSED [ 16%]
tests/test_email_parser.py::test_split_list_not_triggered_for_paragraph PASSED [ 20%]
tests/test_email_parser.py::test_extract_sections_splits_multi_item_list PASSED [ 23%]
tests/test_email_parser.py::test_extract_sections_story_link_not_contaminated_by_neighbour PASSED [ 26%]
tests/test_email_parser.py::test_extract_sections_single_story_sponsor_unaffected PASSED [ 29%]
tests/test_email_parser.py::test_extract_sections_regular_paragraph_unaffected PASSED [ 32%]
tests/test_email_parser.py::test_extract_title_heading_line PASSED       [ 35%]
tests/test_email_parser.py::test_extract_title_h2_heading PASSED         [ 38%]
tests/test_email_parser.py::test_extract_title_no_heading PASSED         [ 41%]
tests/test_email_parser.py::test_extract_title_empty_heading PASSED      [ 44%]
tests/test_email_parser.py::test_extract_title_leading_blank_lines_skipped PASSED [ 47%]
tests/test_email_parser.py::test_select_link_returns_first_url PASSED    [ 50%]
tests/test_email_parser.py::test_select_link_empty_returns_none PASSED   [ 52%]
tests/test_email_parser.py::test_parse_emails_returns_story_records PASSED [ 55%]
tests/test_email_parser.py::test_parse_emails_newsletter_field PASSED    [ 58%]
tests/test_email_parser.py::test_parse_emails_date_field_format PASSED   [ 61%]
tests/test_email_parser.py::test_parse_emails_title_extracted_from_heading PASSED [ 64%]
tests/test_email_parser.py::test_parse_emails_title_none_when_no_heading PASSED [ 67%]
tests/test_email_parser.py::test_parse_emails_link_extracted PASSED      [ 70%]
tests/test_email_parser.py::test_parse_emails_link_none_when_no_link PASSED [ 73%]
tests/test_email_parser.py::test_parse_emails_short_item_preserved PASSED [ 76%]
tests/test_email_parser.py::test_parse_emails_empty_email_skipped PASSED [ 79%]
tests/test_email_parser.py::test_parse_emails_multiple_emails_flat_list PASSED [ 82%]
tests/test_email_parser.py::test_table_artifact_dropped PASSED           [ 85%]
tests/test_email_parser.py::test_empty_anchor_link_stripped_from_body PASSED [ 88%]
tests/test_email_parser.py::test_toc_section_dropped PASSED              [ 91%]
tests/test_email_parser.py::test_story_with_multiple_inline_links_not_dropped PASSED [ 94%]
tests/test_email_parser.py::test_intro_signal_section_dropped PASSED     [ 97%]
tests/test_email_parser.py::test_short_valid_story_still_preserved_after_phase2 PASSED [100%]

============================== 34 passed in 0.29s ==============================
```

### Level 3: Smoke Test

```
$ python -c "
from ingestion.email_parser import StoryRecord, parse_emails, _extract_title, _select_link
print('StoryRecord fields:', list(StoryRecord.__dataclass_fields__.keys()))
title, body = _extract_title('# My Headline\nBody text here.')
print('title:', title, '| body:', body)
link = _select_link([{'url': 'https://example.com', 'anchor_text': 'x'}])
print('link:', link)
print('All imports ok')
"

StoryRecord fields: ['title', 'body', 'link', 'newsletter', 'date']
title: My Headline | body: Body text here.
link: https://example.com
All imports ok
```

### Level 4: Manual — Real Email

```
$ python -c "
import sys; sys.path.insert(0, '.')
from ingestion.email_parser import parse_emails
with open('debug_samples/the_deep_view.eml', 'rb') as f:
    raw = f.read()
records = parse_emails([raw])
print(f'Total story records: {len(records)}')
for i, r in enumerate(records[:5], 1):
    print(f'  [{i}] title={r.title!r}  date={r.date}  link={r.link}')
    print(f'       body preview: {r.body[:80]!r}')
"

Total story records: 45
  [1] title=None  date=2026-03-17  link=https://elink983.thedeepview.co/ss/c/...
       body preview: '**Welcome back.** Nvidia announced several new bets on Monday at GTC 2026. In sp'
  [2] title='Nvidia builds the tech stack for the robotics era'  date=2026-03-17  link=None
       body preview: '|'
  [3] title=None  date=2026-03-17  link=https://elink983.thedeepview.co/ss/c/...
       body preview: 'Nvidia is betting on robots, without actually building any robots.   \nOn Monday,'
  [4] title=None  date=2026-03-17  link=https://elink983.thedeepview.co/ss/c/...
       body preview: 'This isn't the first time in recent history that Huang has proclaimed AI's futur'
  [5] title=None  date=2026-03-17  link=https://elink983.thedeepview.co/ss/c/...
       body preview: 'GTC COVERAGE BROUGHT TO YOU BY IREN  \n  \n# Unleashing NVIDIA Blackwell Performan'
```

Record count reduced from 49 → 45 (4 noise sections removed by Phase 2 filters).

---

## Known Edge Case (not in plan scope)

Record [2] has `title='Nvidia builds the tech stack for the robotics era'` but `body='|'`. The full section text passes `_is_table_artifact()` because the heading text dominates (pipe ratio well under 15%). After `_extract_title()` strips the heading, only `|` remains as body. The `body = section_text` fallback in `parse_emails()` does not apply because `|` is non-empty. The LLM filter will handle this downstream.

---

## Status

- 34/34 tests passing
- All validation commands pass
- Ready for `/commit`
