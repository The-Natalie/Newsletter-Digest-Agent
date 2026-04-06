# Execution Report: email-parser-body-cleanup (Phase 5)
Timestamp: 2026-04-04T12-00-00

## Plan
`.agents/plans/email-parser-body-cleanup.md`

## Status: COMPLETE

---

## Task 1 — `_is_boilerplate_segment()` unicode normalization

**File**: `ingestion/email_parser.py`, lines 236–239

**Change**: Added smart-quote normalization before `.lower()` — replaces U+2018/U+2019/U+201C/U+201D with ASCII equivalents so signals like `"in today's newsletter"` match TDV text like `"IN TODAY'S NEWSLETTER"`.

```
BEFORE:
def _is_boilerplate_segment(text: str) -> bool:
    text_lower = text.lower()
    return any(signal in text_lower for signal in _BOILERPLATE_SEGMENT_SIGNALS)

AFTER:
def _is_boilerplate_segment(text: str) -> bool:
    text_lower = (
        text
        .replace('\u2018', "'")
        .replace('\u2019', "'")
        .replace('\u201c', '"')
        .replace('\u201d', '"')
        .lower()
    )
    return any(signal in text_lower for signal in _BOILERPLATE_SEGMENT_SIGNALS)
```

---

## Task 2 — Strip `****` empty-bold artifacts in `parse_emails()`

**File**: `ingestion/email_parser.py`, section loop in `parse_emails()`

**Change**: Added `re.sub(r'\*{4,}', '', body)` after `_strip_leading_pipe(body)` to strip html2text's `****` rendering of empty `<strong></strong>` tags.

---

## Task 3 — Min-length boundary in story assembly inner loop

**File**: `ingestion/email_parser.py`, inner while loop in `_extract_sections()`

**Change**: Computed `clean_next` once (reused for table-artifact and new min-length check). Added `if len(clean_next) < _MIN_SECTION_CHARS: break` after `_is_table_artifact` check. Prevents `| HARDWARE` (10 chars), `| ENTERPRISE` (12 chars) theme labels from being absorbed into story bodies.

**Also added**: Special case for image-link-only sections — `if not clean_next and _MD_LINK_RE.search(next_sec): story_parts.append(next_sec); i += 1; continue`. This handles `[](article-url)` sections (html2text render of `<a href="url"><img ...>`) that have clean text = "" but carry a URL. Without this, they would have broken the loop via `_is_table_artifact("")` = True (empty string), losing the article URL. The special case includes them in `story_parts` so their URL is captured in the second-pass link extraction.

---

## Task 4 — Empty-anchor image links in `_extract_sections()` and `_split_list_section()`

**File**: `ingestion/email_parser.py`, two link extraction loops

**Change 1** (`_extract_sections` second loop): Replaced `if not anchor: continue` with a branch that captures empty-anchor URLs (`anchor_text=""`) when no named link already holds the same normalized URL.

**Change 2** (`_split_list_section` per-item loop): Applied the same empty-anchor capture logic. Also refactored to use `item_links` (local variable) instead of `links` to avoid shadowing.

---

## Task 5 — Trailing table-artifact line stripping in `parse_emails()`

**File**: `ingestion/email_parser.py`, section loop in `parse_emails()`

**Change**: After existing trailing-pipe regex, added line-by-line strip:
```python
body_lines = body.split('\n')
while body_lines:
    last = body_lines[-1].strip()
    if last and (
        _is_table_artifact(last)
        or re.match(r'^\|[\s\|]+\S', last) is not None
    ):
        body_lines.pop()
    else:
        break
body = '\n'.join(body_lines).strip()
```
- `_is_table_artifact` catches `| |  SUBSCRIBE` (pipe ratio ≈ 18% > 15%)
- Secondary regex `r'^\|[\s\|]+\S'` catches `| |  GET IN TOUCH WITH US HERE` (pipe ratio ≈ 9%, below threshold but clearly structural)

---

## Task 6 — Link-free list item preservation in `_split_list_section()`

**File**: `ingestion/email_parser.py`, `_split_list_section()`

**Change**: Introduced `linked_count` to track items with links separately from total items. Link-free items with `len(clean_text) >= _MIN_LIST_ITEM_CHARS` are now included in `result` with `links=[]`. The function still only returns a split result when `linked_count >= 2`.

---

## Deviation: Image-link section handling in assembly loop (Task 3/4 interaction)

The plan specified a straightforward min-length break in Task 3. During implementation, a secondary issue was discovered: `[](article-url)` sections (image links as standalone sections, separated by blank lines from the heading) have `clean_next = ""` which also triggers `_is_table_artifact("")` = True (because the empty-string branch returns True). This would break the story assembly loop before the URL-only section joined `story_parts`, causing the article URL to be lost regardless of the Task 4 change.

**Resolution**: Added a guard before the `_is_table_artifact` and min-length checks:
```python
if not clean_next and _MD_LINK_RE.search(next_sec):
    story_parts.append(next_sec)
    i += 1
    continue
```
This allows URL-only sections to be collected into the story without their content polluting the body (the second-loop's `_MD_LINK_RE.sub(r'\1', sec)` strips empty anchors from the prose). Verified that the existing test `test_empty_anchor_link_stripped_from_body` still passes.

---

## Validation: Level 1 — Syntax check

```
$ python -c "import ingestion.email_parser; print('OK')"
OK
```

---

## Validation: Level 2 — Full test suite (first run, before image-link assembly fix)

```
FAILED tests/test_email_parser.py::test_empty_anchor_image_link_captured
  assert any("example.com/article" in url for url in results[0].links)
  AssertionError
1 failed, 74 passed
```

Root cause diagnosed: `[](url)` as a standalone section (split from heading by blank lines) had `clean_next = ""` triggering `_is_table_artifact("")` = True → break before URL section joined `story_parts`. Added image-link guard to assembly loop.

---

## Validation: Level 2 — Full test suite (after fix)

```
============================= test session starts ==============================
platform darwin -- Python 3.12.12, pytest-9.0.2, pluggy-1.6.0
collected 75 items

tests/test_email_parser.py::test_split_list_two_items_with_links PASSED
tests/test_email_parser.py::test_split_list_five_items_with_links PASSED
tests/test_email_parser.py::test_split_list_preserves_link_per_item PASSED
tests/test_email_parser.py::test_split_list_single_item_returns_none PASSED
tests/test_email_parser.py::test_split_list_no_links_returns_none PASSED
tests/test_email_parser.py::test_split_list_fewer_than_two_linked_items_returns_none PASSED
tests/test_email_parser.py::test_split_list_not_triggered_for_paragraph PASSED
tests/test_email_parser.py::test_extract_sections_splits_multi_item_list PASSED
tests/test_email_parser.py::test_extract_sections_story_link_not_contaminated_by_neighbour PASSED
tests/test_email_parser.py::test_extract_sections_single_story_sponsor_unaffected PASSED
tests/test_email_parser.py::test_extract_sections_regular_paragraph_unaffected PASSED
tests/test_email_parser.py::test_extract_title_heading_line PASSED
tests/test_email_parser.py::test_extract_title_h2_heading PASSED
tests/test_email_parser.py::test_extract_title_no_heading PASSED
tests/test_email_parser.py::test_extract_title_empty_heading PASSED
tests/test_email_parser.py::test_extract_title_leading_blank_lines_skipped PASSED
tests/test_email_parser.py::test_collect_links_returns_all_urls PASSED
tests/test_email_parser.py::test_collect_links_empty_returns_empty_list PASSED
tests/test_email_parser.py::test_parse_emails_returns_story_records PASSED
tests/test_email_parser.py::test_parse_emails_newsletter_field PASSED
tests/test_email_parser.py::test_parse_emails_date_field_format PASSED
tests/test_email_parser.py::test_parse_emails_title_extracted_from_heading PASSED
tests/test_email_parser.py::test_parse_emails_title_none_when_no_heading PASSED
tests/test_email_parser.py::test_parse_emails_link_extracted PASSED
tests/test_email_parser.py::test_parse_emails_link_none_when_no_link PASSED
tests/test_email_parser.py::test_parse_emails_short_item_preserved PASSED
tests/test_email_parser.py::test_parse_emails_empty_email_skipped PASSED
tests/test_email_parser.py::test_parse_emails_multiple_emails_flat_list PASSED
tests/test_email_parser.py::test_table_artifact_dropped PASSED
tests/test_email_parser.py::test_empty_anchor_link_stripped_from_body PASSED
tests/test_email_parser.py::test_toc_section_dropped PASSED
tests/test_email_parser.py::test_story_with_multiple_inline_links_not_dropped PASSED
tests/test_email_parser.py::test_intro_signal_section_dropped PASSED
tests/test_email_parser.py::test_short_valid_story_still_preserved_after_phase2 PASSED
tests/test_email_parser.py::test_heading_with_pipe_body_not_a_story PASSED
tests/test_email_parser.py::test_titled_section_with_pipe_body_dropped_by_parse_emails PASSED
tests/test_email_parser.py::test_trailing_pipe_stripped_from_body PASSED
tests/test_email_parser.py::test_xa0_normalized_in_body PASSED
tests/test_email_parser.py::test_together_with_section_dropped PASSED
tests/test_email_parser.py::test_thanks_for_reading_section_dropped PASSED
tests/test_email_parser.py::test_story_heading_collects_following_paragraphs PASSED
tests/test_email_parser.py::test_category_heading_does_not_merge_following_stories PASSED
tests/test_email_parser.py::test_bold_title_extracted_as_story_title PASSED
tests/test_email_parser.py::test_links_field_is_list PASSED
tests/test_email_parser.py::test_links_field_contains_story_urls PASSED
tests/test_email_parser.py::test_source_count_default_is_1 PASSED
tests/test_email_parser.py::test_boilerplate_unicode_apostrophe_dropped PASSED
tests/test_email_parser.py::test_bold_artifact_stripped_from_body PASSED
tests/test_email_parser.py::test_theme_label_not_absorbed_into_story_body PASSED
tests/test_email_parser.py::test_empty_anchor_image_link_captured PASSED
tests/test_email_parser.py::test_trailing_table_artifact_line_stripped PASSED
tests/test_email_parser.py::test_trailing_get_in_touch_line_stripped PASSED
tests/test_email_parser.py::test_split_list_preserves_link_free_items PASSED
tests/test_deduplicator.py::test_single_item_cluster_returns_that_item PASSED
tests/test_deduplicator.py::test_longest_body_wins PASSED
tests/test_deduplicator.py::test_title_breaks_body_tie PASSED
tests/test_deduplicator.py::test_link_breaks_remaining_tie PASSED
tests/test_deduplicator.py::test_earliest_date_overrides_representative_date PASSED
tests/test_deduplicator.py::test_original_record_not_mutated PASSED
tests/test_deduplicator.py::test_all_empty_dates_preserves_representative_date PASSED
tests/test_deduplicator.py::test_representative_date_from_partial_empty_dates PASSED
tests/test_deduplicator.py::test_three_item_cluster_selects_longest PASSED
tests/test_deduplicator.py::test_deduplicate_empty_clusters_returns_empty PASSED
tests/test_deduplicator.py::test_deduplicate_skips_empty_clusters PASSED
tests/test_deduplicator.py::test_deduplicate_single_cluster_single_item PASSED
tests/test_deduplicator.py::test_deduplicate_single_cluster_multiple_items PASSED
tests/test_deduplicator.py::test_deduplicate_multiple_clusters_one_per_cluster PASSED
tests/test_deduplicator.py::test_deduplicate_returns_story_records PASSED
tests/test_deduplicator.py::test_deduplicate_date_override_propagates PASSED
tests/test_deduplicator.py::test_deduplicate_large_cluster_no_exception PASSED
tests/test_deduplicator.py::test_select_representative_merges_links_from_cluster PASSED
tests/test_deduplicator.py::test_select_representative_deduplicates_links PASSED
tests/test_deduplicator.py::test_select_representative_sets_source_count PASSED
tests/test_deduplicator.py::test_select_representative_single_item_source_count_is_1 PASSED
tests/test_deduplicator.py::test_deduplicate_source_count_set_on_representatives PASSED

============================== 75 passed in 0.19s ==============================
```

---

## Validation: Level 3 — Targeted new tests

```
$ python -m pytest tests/test_email_parser.py -k "unicode_apostrophe or bold_artifact or theme_label or empty_anchor or trailing_table or trailing_get or link_free" -v

tests/test_email_parser.py::test_empty_anchor_link_stripped_from_body PASSED
tests/test_email_parser.py::test_boilerplate_unicode_apostrophe_dropped PASSED
tests/test_email_parser.py::test_bold_artifact_stripped_from_body PASSED
tests/test_email_parser.py::test_theme_label_not_absorbed_into_story_body PASSED
tests/test_email_parser.py::test_empty_anchor_image_link_captured PASSED
tests/test_email_parser.py::test_trailing_table_artifact_line_stripped PASSED
tests/test_email_parser.py::test_trailing_get_in_touch_line_stripped PASSED
tests/test_email_parser.py::test_split_list_preserves_link_free_items PASSED
8 passed, 47 deselected
```

(8 selected because `empty_anchor` keyword matches both `test_empty_anchor_link_stripped_from_body` and `test_empty_anchor_image_link_captured`)

---

## Validation: Level 5 — Spot-checks against debug_samples/the_deep_view.eml

```
Total story records: 29

Intro/ToC records (should be 0): 0
Records with **** artifact (should be 0): 0
Records with theme label in body tail (should be 0): 0
Records with trailing footer junk (should be 0): 0
Google Gemini bullet present (should be >= 1): 1
```

Note: Total is still 29 (same as pre-Phase-5) because intro/ToC drop (-1) is offset by Gemini bullet inclusion (+1).

---

## Validation: Level 4 — Record-by-record changes confirmed

Key changes vs. `2026-04-04T01-35-27-test-results.txt`:

| Record | Before | After |
|--------|--------|-------|
| [1] (was intro/ToC) | title=None, body="Welcome back. IN TODAY'S NEWSLETTER..." | DROPPED — intro/ToC correctly filtered by unicode-normalized boilerplate signal |
| new [1] (was [2]) | body had `****\n` in two bullet items | body clean, no `****` artifacts |
| new [1] links count | 3 links | 4 links (image link `[](url)` captured by empty-anchor fix) |
| new [3] (was [4] sponsor) | body ended with `\| HARDWARE` | body ends at "Try a demo right here." — theme label stripped by min-length boundary |
| new [5] (was [6] sponsor) | body ended with `\| ENTERPRISE` | body ends at "Watch now" — theme label stripped |
| new [28] | body ended with `\| \|  SUBSCRIBE` | SUBSCRIBE line stripped by trailing artifact strip |
| new [29] | body ended with `\| \|  GET IN TOUCH WITH US HERE` | GET IN TOUCH line stripped by secondary regex |
| Google Gemini bullet | missing | present as its own record |

---

## Files Modified

- `ingestion/email_parser.py` — 6 targeted changes (Tasks 1–6, plus image-link assembly guard)
- `tests/test_email_parser.py` — 7 new test functions appended

---

## Ready for Commit

- [x] All tasks completed
- [x] All validation commands passed
- [x] All tests passing (75/75)

## Follow-up Items

- **Image-link assembly guard** (deviation from plan): The plan's Task 4 assumed empty-anchor links would be captured straightforwardly by changing `if not anchor: continue`. In practice, a `[](url)` section appearing as a *standalone section* (separated by blank lines from the story heading) would break out of the assembly loop via `_is_table_artifact("")` before joining `story_parts`. Added `if not clean_next and _MD_LINK_RE.search(next_sec): story_parts.append(next_sec); i += 1; continue` guard to handle this. Plan should be updated to document this nuance.
- Records [22]–[27] (quiz/poll/results) still appear — deferred to LLM filter as planned.
- Records [3] and [5] (sponsor bodies for Airia and Slack) still appear — deferred to LLM filter as planned.
