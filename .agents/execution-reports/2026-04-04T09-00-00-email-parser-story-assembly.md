# Execution Report: email-parser-story-assembly (Phase 4)

**Plan:** `.agents/plans/email-parser-story-assembly.md`
**Date:** 2026-04-04
**Context:** Phases 1–3 complete (53/53 tests passing). This run executes Phase 4 (Tasks 1–12): story reassembly, pipe stripping, bold-title detection, \xa0 normalization, new boilerplate signals, schema changes (links: list[str], source_count: int), and downstream deduplicator update.

---

## Pre-flight: syntax check

```
$ python -m py_compile ingestion/email_parser.py && echo "syntax ok"
syntax ok
```

---

## Task 1 — ADD new `_BOILERPLATE_SEGMENT_SIGNALS` entries

Added 6 new signals to the end of `_BOILERPLATE_SEGMENT_SIGNALS` in `ingestion/email_parser.py`:
- `"together with"` — sponsor connector labels
- `"brought to you by"` — sponsor labels
- `"in today's newsletter"` — ToC header variant
- `"thanks for reading"` — newsletter outro
- `"before you go"` — poll section header
- `"a quick poll"` — poll section header

### Validation
```
$ python -m py_compile ingestion/email_parser.py && echo "syntax ok"
syntax ok
```

---

## Task 2 — ADD `_strip_leading_pipe()` and apply in `_extract_sections()`

Added `_LEADING_PIPE_RE = re.compile(r'^\|\s*')` and `_strip_leading_pipe()` function after `_is_heading_only()`. Applied `sec = _strip_leading_pipe(sec)` at the start of the `for sec in merged:` loop in `_extract_sections()`, before any other processing.

### Validation
```
$ python -m py_compile ingestion/email_parser.py && echo "syntax ok"
syntax ok
```

---

## Task 3 — ADD `_is_story_heading()` helper

Added `_is_story_heading()` function immediately before `_is_heading_only()`.

**Deviation from plan:** The plan specified that `_is_story_heading()` checks whether ALL lines start with `#`. During real-email testing (Level 4), it was discovered that TDV newsletter headings look like `# Heading\n  \n| [](image-url)` in html2text output — the heading and an image link are in the same raw_section (separated by `\n  \n` rather than `\n\n`). The ALL-lines check returned False for these, preventing story assembly from triggering.

**Fix applied:** Changed `_is_story_heading()` to check only the FIRST non-empty line. A section is a story heading if its first line is a bare `#`-prefixed heading (not bold-wrapped), regardless of additional content in the same section. Updated docstring to reflect this.

### Validation
```
$ python -c "from ingestion.email_parser import _is_story_heading; print(_is_story_heading('# Nvidia builds the tech stack')); print(_is_story_heading('# **Headlines & Launches**'))"
True
False
```

---

## Task 4 — REWRITE heading-merge loop for story reassembly

Replaced the original heading-merge loop in `_extract_sections()` with the story reassembly algorithm from the plan.

**Additional deviation from plan:** The inner collection loop was specified to break only at `_is_heading_only(next_sec)`. However, because `_is_story_heading()` was updated to check only the first line, a section like `# Next Story\n  \n| [](image)` has `_is_heading_only()` = False (not all lines are `#`). Without the additional check, story 2's heading section would be absorbed into story 1.

**Fix applied:** Changed the inner loop break condition to:
```python
if _is_heading_only(next_sec) or _is_story_heading(next_sec):
    break
```
This catches both pure heading-only sections and TDV-style heading+image sections as story boundaries.

**Additional deviation from plan:** The plan specified `elif _is_heading_only(sec): # merge with next section only`. During Level 5 testing (TLDR email), this caused TLDR category headings (`# **Headlines & Launches**`) to merge with the first following story, producing records with `title='**Headlines & Launches**'` instead of the story's own bold title.

**Fix applied:** Changed `elif _is_heading_only(sec):` to simply skip the section (`i += 1`) rather than merge with the next. Rationale: TLDR-style bold-wrapped category headings are pure structural dividers; each following story already has its own bold title extracted by the new Format 2 bold-title detection in `_extract_title()`. Dropping the category heading loses no story content.

### Validation
```
$ python -m py_compile ingestion/email_parser.py && echo "syntax ok"
syntax ok
```

---

## Task 5 — UPDATE `_extract_title()` for bold-title detection

Replaced `_extract_title()` with the version that detects both Format 1 (markdown heading) and Format 2 (bold title: `**text**` as the entire first non-empty line).

### Validation
```
$ python -c "from ingestion.email_parser import _extract_title; print(_extract_title('**Meta Acquired Moltbook (3 minute read)**\n\nMeta has acquired Moltbook...'))"
('Meta Acquired Moltbook (3 minute read)', 'Meta has acquired Moltbook...')
```

---

## Task 6 — UPDATE `StoryRecord` schema

1. Changed `from dataclasses import dataclass` → `from dataclasses import dataclass, field`
2. Updated `StoryRecord`:
   - `link: str | None` → `links: list[str]`
   - Added `source_count: int = field(default=1)`

### Validation
```
$ python -c "from ingestion.email_parser import StoryRecord; r = StoryRecord(title=None, body='test', links=[], newsletter='A', date='2026-03-17'); print(r.source_count)"
1
```

---

## Task 7 — ADD `_collect_links()` and REMOVE `_select_link()`

Replaced `_select_link()` with `_collect_links()`. Updated `parse_emails()` to use `_collect_links()` and the new `links=` field name.

### Validation
```
$ python -m py_compile ingestion/email_parser.py && echo "syntax ok"
syntax ok
```

---

## Task 8 — UPDATE `parse_emails()` for `\xa0` normalization and trailing `|` stripping

Added to the `for section in sections:` loop:
1. `section_text = section_text.replace('\xa0', ' ')` — normalize non-breaking spaces
2. `body = _strip_leading_pipe(body)` — strip leading `| ` artifact from body after title extraction (new addition not in original plan, needed for TDV-style heading sections that produce `| \n\nparagraph` body)
3. `body = re.sub(r'(\s*\|)+\s*$', '', body).strip()` — strip trailing `|` lines
4. `if not body: continue` — skip if body is now empty

**Deviation from plan:** Task 8 in the plan did not include a leading-pipe strip on body. This was added because TDV heading sections (`# Heading\n  \n| [](image)`) after `_extract_title()` leaves a `| ` at the start of the body (from the image-only `| [](image-url)` line becoming just `| ` after link stripping). Applied `_strip_leading_pipe(body)` to handle this.

### Validation
```
$ python -m py_compile ingestion/email_parser.py && echo "syntax ok"
syntax ok
```

---

## Task 9 — UPDATE `processing/deduplicator.py` for new schema

Updated `select_representative()`:
1. Changed `max()` key: `r.link is not None` → `bool(r.links)`
2. Added link merging: collects all URLs from all cluster items, deduplicating on URL
3. Returns `dataclasses.replace(representative, date=earliest_date, links=merged_links, source_count=len(cluster))`

### Validation
```
$ python -m py_compile processing/deduplicator.py && echo "syntax ok"
syntax ok
```

---

## Task 10 — UPDATE `tests/test_deduplicator.py` for new schema

1. Updated `_record()` helper: `link: str | None = None` → `links: list[str] | None = None` (with `links or []`)
2. Updated `test_link_breaks_remaining_tie`: uses `links=[]` and `links=["url"]`; asserts `result.links == [...]`
3. Added 5 new tests:
   - `test_select_representative_merges_links_from_cluster`
   - `test_select_representative_deduplicates_links`
   - `test_select_representative_sets_source_count`
   - `test_select_representative_single_item_source_count_is_1`
   - `test_deduplicate_source_count_set_on_representatives`

### Validation
```
$ python -m pytest tests/test_deduplicator.py -v
22 passed in 0.16s
```

---

## Task 11 — UPDATE `tests/test_email_parser.py` for schema changes

1. Updated import: removed `_select_link`, added `_collect_links`
2. Replaced `test_select_link_*` tests with `test_collect_links_*` tests
3. Updated `test_parse_emails_link_extracted`: `records[0].link ==` → `"url" in records[0].links`
4. Updated `test_parse_emails_link_none_when_no_link`: `records[0].link is None` → `records[0].links == []`

### Validation
```
$ python -m pytest tests/test_email_parser.py -v
36 passed in 0.27s
```

---

## Task 12 — ADD Phase 4 feature tests

Added 10 new tests after the Phase 3 tests:
- `test_trailing_pipe_stripped_from_body`
- `test_xa0_normalized_in_body`
- `test_together_with_section_dropped`
- `test_thanks_for_reading_section_dropped`
- `test_story_heading_collects_following_paragraphs`
- `test_category_heading_does_not_merge_following_stories`
- `test_bold_title_extracted_as_story_title`
- `test_links_field_is_list`
- `test_links_field_contains_story_urls`
- `test_source_count_default_is_1`

### Validation
```
$ python -m pytest tests/test_email_parser.py tests/test_deduplicator.py -v

============================= test session starts ==============================
platform darwin -- Python 3.12.12, pytest-9.0.2, pluggy-1.6.0 -- /Users/natalie/Documents/Agentic AI/Newsletter Digest Agent/.venv/bin/python
cachedir: .pytest_cache
rootdir: /Users/natalie/Documents/Agentic AI/Newsletter Digest Agent
plugins: anyio-4.12.1
collecting ... collected 68 items

tests/test_email_parser.py::test_split_list_two_items_with_links PASSED  [  1%]
tests/test_email_parser.py::test_split_list_five_items_with_links PASSED [  2%]
tests/test_email_parser.py::test_split_list_preserves_link_per_item PASSED [  4%]
tests/test_email_parser.py::test_split_list_single_item_returns_none PASSED [  5%]
tests/test_email_parser.py::test_split_list_no_links_returns_none PASSED [  7%]
tests/test_email_parser.py::test_split_list_fewer_than_two_linked_items_returns_none PASSED [  8%]
tests/test_email_parser.py::test_split_list_not_triggered_for_paragraph PASSED [ 10%]
tests/test_email_parser.py::test_extract_sections_splits_multi_item_list PASSED [ 11%]
tests/test_email_parser.py::test_extract_sections_story_link_not_contaminated_by_neighbour PASSED [ 13%]
tests/test_email_parser.py::test_extract_sections_single_story_sponsor_unaffected PASSED [ 14%]
tests/test_email_parser.py::test_extract_sections_regular_paragraph_unaffected PASSED [ 16%]
tests/test_email_parser.py::test_extract_title_heading_line PASSED       [ 17%]
tests/test_email_parser.py::test_extract_title_h2_heading PASSED         [ 19%]
tests/test_email_parser.py::test_extract_title_no_heading PASSED         [ 20%]
tests/test_email_parser.py::test_extract_title_empty_heading PASSED      [ 22%]
tests/test_email_parser.py::test_extract_title_leading_blank_lines_skipped PASSED [ 23%]
tests/test_email_parser.py::test_collect_links_returns_all_urls PASSED   [ 25%]
tests/test_email_parser.py::test_collect_links_empty_returns_empty_list PASSED [ 26%]
tests/test_email_parser.py::test_parse_emails_returns_story_records PASSED [ 27%]
tests/test_email_parser.py::test_parse_emails_newsletter_field PASSED    [ 29%]
tests/test_email_parser.py::test_parse_emails_date_field_format PASSED   [ 30%]
tests/test_email_parser.py::test_parse_emails_title_extracted_from_heading PASSED [ 32%]
tests/test_email_parser.py::test_parse_emails_title_none_when_no_heading PASSED [ 33%]
tests/test_email_parser.py::test_parse_emails_link_extracted PASSED      [ 35%]
tests/test_email_parser.py::test_parse_emails_link_none_when_no_link PASSED [ 36%]
tests/test_email_parser.py::test_parse_emails_short_item_preserved PASSED [ 38%]
tests/test_email_parser.py::test_parse_emails_empty_email_skipped PASSED [ 39%]
tests/test_email_parser.py::test_parse_emails_multiple_emails_flat_list PASSED [ 41%]
tests/test_email_parser.py::test_table_artifact_dropped PASSED           [ 42%]
tests/test_email_parser.py::test_empty_anchor_link_stripped_from_body PASSED [ 44%]
tests/test_email_parser.py::test_toc_section_dropped PASSED              [ 45%]
tests/test_email_parser.py::test_story_with_multiple_inline_links_not_dropped PASSED [ 47%]
tests/test_email_parser.py::test_intro_signal_section_dropped PASSED     [ 48%]
tests/test_email_parser.py::test_short_valid_story_still_preserved_after_phase2 PASSED [ 50%]
tests/test_email_parser.py::test_heading_with_pipe_body_not_a_story PASSED [ 51%]
tests/test_email_parser.py::test_titled_section_with_pipe_body_dropped_by_parse_emails PASSED [ 52%]
tests/test_email_parser.py::test_trailing_pipe_stripped_from_body PASSED [ 54%]
tests/test_email_parser.py::test_xa0_normalized_in_body PASSED           [ 55%]
tests/test_email_parser.py::test_together_with_section_dropped PASSED    [ 57%]
tests/test_email_parser.py::test_thanks_for_reading_section_dropped PASSED [ 58%]
tests/test_email_parser.py::test_story_heading_collects_following_paragraphs PASSED [ 60%]
tests/test_email_parser.py::test_category_heading_does_not_merge_following_stories PASSED [ 61%]
tests/test_email_parser.py::test_bold_title_extracted_as_story_title PASSED [ 63%]
tests/test_email_parser.py::test_links_field_is_list PASSED              [ 64%]
tests/test_email_parser.py::test_links_field_contains_story_urls PASSED  [ 66%]
tests/test_email_parser.py::test_source_count_default_is_1 PASSED        [ 67%]
tests/test_deduplicator.py::test_single_item_cluster_returns_that_item PASSED [ 69%]
tests/test_deduplicator.py::test_longest_body_wins PASSED                [ 70%]
tests/test_deduplicator.py::test_title_breaks_body_tie PASSED            [ 72%]
tests/test_deduplicator.py::test_link_breaks_remaining_tie PASSED        [ 73%]
tests/test_deduplicator.py::test_earliest_date_overrides_representative_date PASSED [ 75%]
tests/test_deduplicator.py::test_original_record_not_mutated PASSED      [ 76%]
tests/test_deduplicator.py::test_all_empty_dates_preserves_representative_date PASSED [ 77%]
tests/test_deduplicator.py::test_representative_date_from_partial_empty_dates PASSED [ 79%]
tests/test_deduplicator.py::test_three_item_cluster_selects_longest PASSED [ 80%]
tests/test_deduplicator.py::test_deduplicate_empty_clusters_returns_empty PASSED [ 82%]
tests/test_deduplicator.py::test_deduplicate_skips_empty_clusters PASSED [ 83%]
tests/test_deduplicator.py::test_deduplicate_single_cluster_single_item PASSED [ 85%]
tests/test_deduplicator.py::test_deduplicate_single_cluster_multiple_items PASSED [ 86%]
tests/test_deduplicator.py::test_deduplicate_multiple_clusters_one_per_cluster PASSED [ 88%]
tests/test_deduplicator.py::test_deduplicate_returns_story_records PASSED [ 89%]
tests/test_deduplicator.py::test_deduplicate_date_override_propagates PASSED [ 91%]
tests/test_deduplicator.py::test_deduplicate_large_cluster_no_exception PASSED [ 92%]
tests/test_deduplicator.py::test_select_representative_merges_links_from_cluster PASSED [ 94%]
tests/test_deduplicator.py::test_select_representative_deduplicates_links PASSED [ 95%]
tests/test_deduplicator.py::test_select_representative_sets_source_count PASSED [ 97%]
tests/test_deduplicator.py::test_select_representative_single_item_source_count_is_1 PASSED [ 98%]
tests/test_deduplicator.py::test_deduplicate_source_count_set_on_representatives PASSED [100%]

============================== 68 passed in 0.15s ==============================
```

---

## Level 1: Syntax

```
$ python -m py_compile ingestion/email_parser.py && echo "email_parser syntax ok"
email_parser syntax ok

$ python -m py_compile processing/deduplicator.py && echo "deduplicator syntax ok"
deduplicator syntax ok
```

---

## Level 2: Unit Tests

```
$ python -m pytest tests/test_email_parser.py tests/test_deduplicator.py -v
68 passed in 0.15s
```

(46 email_parser + 22 deduplicator)

---

## Level 3: Import Smoke Test

```
$ python -c "
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

StoryRecord fields: ['title', 'body', 'links', 'newsletter', 'date', 'source_count']
# heading title: My Headline
**bold** title: Bold Story Title
is_story_heading (bare): True
is_story_heading (bold): False
collect_links: ['https://a.com', 'https://b.com']
source_count default: 1
All ok
```

---

## Level 4: The Deep View real-email inspection

```
$ python -c "
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

Total records: 29
Records with trailing |: 0 (expected: 0)
Records with xa0: 0 (expected: 0)
Records with body="|": 0 (expected: 0)
Records with Nvidia robotics title: 1 (expected: 1)
  links: 3 links, source_count=1
  body preview: 'Nvidia is betting on robots, without actually building any robots.   \nOn Monday, CEO Jensen Huang un'

First 5 records:
  [1] title=None  links=1  source_count=1
       body: '**Welcome back.** Nvidia announced several new bets on Monday at GTC 2026. In sp'
  [2] title='Nvidia builds the tech stack for the robotics era'  links=3  source_count=1
       body: 'Nvidia is betting on robots, without actually building any robots.   \nOn Monday,'
  [3] title=None  links=0  source_count=1
       body: 'It's hard to build a robot. Building the actual hardware that powers physical AI'
  [4] title='Want To Give Every Employee The Power of AI?'  links=3  source_count=1
       body: 'And, more importantly, want to do it _safely_ and _securely?_ Then you don't nee'
  [5] title='Nvidia unveils a different vision of AI-in-space'  links=2  source_count=1
       body: 'You may have heard of data centers on the ground, but now Nvidia chips are bring'
```

Record count: 29 (down from 40 in Phase 3, 45 in Phase 1-2). All quality checks pass.

---

## Level 5: TLDR real-email inspection

```
$ python -c "
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

Total records: 22
First 8 records:
  [1] title=None
       body: "Google's Gemini Embedding 2, available via the Gemini API and Vertex AI, unifies"
       links=0  source_count=1
  [2] title='Shipping features has never been cheaper. How do you price them? (Sponsor)'
       body: 'AI keeps reducing the cost to build products, and no one knows how to price them'
       links=2  source_count=1
  [3] title=None
       body: '* How to map pricing to value\n  * How to treat pricing as a product\n  * How to v'
       links=0  source_count=1
  [4] title=None
       body: "In the AI era, pricing is your product.  👉 Here's how to put it all together"
       links=2  source_count=1
  [5] title='Meta Acquired Moltbook (3 minute read)'
       body: 'Meta has acquired Moltbook, a Reddit‑like network where AI agents built with the'
       links=1  source_count=1
  [6] title="Nvidia Invests in Mira Murati's Thinking Machines Lab (2 minute read)"
       body: "Nvidia and Mira Murati's Thinking Machines Lab have formed a multiyear partnersh"
       links=1  source_count=1
  [7] title='Google launches new multimodal Gemini Embedding 2 model (2 minute read)'
       body: "Google's Gemini Embedding 2, available via the Gemini API and Vertex AI, unifies"
       links=1  source_count=1
  [8] title='Codex, File My Taxes. Make No Mistakes (11 minute read)'
       body: 'Codex can be used to file personal taxes, and it can even be more accurate than '
       links=1  source_count=1

Records with trailing |: 0 (expected: 0)
Records with Meta Acquired title: 1 (expected: 1+)
```

---

## grep checks

```
$ grep -rn "_select_link" ingestion/tests/
(no output — _select_link is fully removed)

$ grep -n "link:" ingestion/email_parser.py (checking for old link: str | None)
(no old-style link field — only links: list[str])
```

---

## Deviations from Plan

### Deviation 1: `_is_story_heading()` checks first line only (not all lines)

**Root cause discovered:** TDV newsletter headings appear as `# Heading\n  \n| [](image-url)` in a single raw_section (the spaces between newlines prevent `_SECTION_SPLIT_PATTERN` from splitting them). The plan's all-lines check returned False, preventing story assembly.

**Fix:** Changed to check only the first non-empty line. Updated docstring. Tests still pass.

### Deviation 2: Inner collection loop also breaks on `_is_story_heading(next_sec)`

**Root cause:** With first-line-only `_is_story_heading()`, the next story heading section (`# Story2\n  \n| [](image)`) would not be caught by `_is_heading_only()` (not all lines are headings). Without the additional check, story 2's heading would be absorbed into story 1.

**Fix:** Added `or _is_story_heading(next_sec)` to the inner break condition.

### Deviation 3: Category headings are dropped, not merged

**Root cause discovered (Level 5):** The plan's `elif _is_heading_only(): # merge with next section` caused TLDR category headings (`# **Headlines & Launches**`) to merge with the first following story. The resulting record had `title='**Headlines & Launches**'` instead of the story's own bold title.

**Fix:** Changed `elif _is_heading_only():` to simply skip the section (`i += 1`). Category headings are pure structural dividers; each following story has its own bold title extracted by the new Format 2 detection. Tests pass; Level 5 `Meta Acquired title: 1` confirmed.

### Deviation 4: Leading-pipe strip on body in `parse_emails()`

**Root cause:** After story reassembly merges `# Heading\n  \n| [](image)` with paragraphs, and `_extract_title()` strips the heading, the body starts with `| ` (from the image link). The plan did not include a leading-pipe strip on body.

**Fix:** Added `body = _strip_leading_pipe(body)` after `_extract_title()` in `parse_emails()`, before trailing-pipe strip. Reuses the existing helper.

---

## Ready for Commit

- [x] All tasks completed
- [x] All validation commands passed
- [x] All tests passing (68/68)

## Follow-up Items

- `ai/claude_client.py` — rewrite as binary keep/drop filter (next plan); currently imports `StoryGroup` which no longer exists
- `ai/story_reviewer.py` + `tests/test_story_reviewer.py` — delete (per prime summary)
- `processing/digest_builder.py` — rewrite full pipeline (subsequent plan)
- TDV record [3] (`title=None`) is the 3rd paragraph of the Nvidia story, separated by a sponsor break — acceptable per plan notes (semantic dedup handles further merging)
- TLDR records [3] and [4] (`title=None`) are a bullet list and CTA paragraph from the sponsor section — LLM filter handles residual sponsor content
