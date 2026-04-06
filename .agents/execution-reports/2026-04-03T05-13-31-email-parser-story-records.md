# Execution Report: email-parser-story-records (Phase 3)

**Plan:** `.agents/plans/email-parser-story-records.md`
**Date:** 2026-04-03
**Context:** Tasks 1–12 completed in prior executions. This run executes Phase 3 (Tasks 13–14): post-title body artifact filter to eliminate `body='|'` records observed in deduplicator Level 5 inspection.

---

## Pre-flight: syntax check

```
$ python -m py_compile ingestion/email_parser.py && echo "syntax ok"
syntax ok
```

---

## Task 13 — Apply `_is_table_artifact()` to body in `parse_emails()`

### Change made

Added one guard in `ingestion/email_parser.py` inside the `for section in sections:` loop in `parse_emails()`, immediately after the empty-body fallback:

```python
            title, body = _extract_title(section_text)
            if not body.strip():
                body = section_text  # fallback: use full text if title stripped everything
            if _is_table_artifact(body):           # skip if title extraction left only structural noise
                continue
            link = _select_link(section.get("links", []))
```

### Validation

```
$ python -m py_compile ingestion/email_parser.py && echo "syntax ok"
syntax ok
```

---

## Task 14 — Add Phase 3 tests to `tests/test_email_parser.py`

### Changes made

Added two tests after the existing Phase 2 tests:

- `test_heading_with_pipe_body_not_a_story` — unit test directly exercising `_extract_title` + `_is_table_artifact` on the exact section text pattern observed in real email
- `test_titled_section_with_pipe_body_dropped_by_parse_emails` — integration test through `parse_emails()` using `<h3>heading</h3><p>|</p>` HTML

---

## Validation Results

### Level 1: Syntax

```
$ python -m py_compile ingestion/email_parser.py && echo "syntax ok"
syntax ok
```

### Level 2: Unit Tests

```
$ python -m pytest tests/test_email_parser.py tests/test_deduplicator.py -v

============================= test session starts ==============================
platform darwin -- Python 3.12.12, pytest-9.0.2, pluggy-1.6.0 -- /Users/natalie/Documents/Agentic AI/Newsletter Digest Agent/.venv/bin/python
cachedir: .pytest_cache
rootdir: /Users/natalie/Documents/Agentic AI/Newsletter Digest Agent
plugins: anyio-4.12.1
collecting ... collected 53 items

tests/test_email_parser.py::test_split_list_two_items_with_links PASSED  [  1%]
tests/test_email_parser.py::test_split_list_five_items_with_links PASSED [  3%]
tests/test_email_parser.py::test_split_list_preserves_link_per_item PASSED [  5%]
tests/test_email_parser.py::test_split_list_single_item_returns_none PASSED [  7%]
tests/test_email_parser.py::test_split_list_no_links_returns_none PASSED [  9%]
tests/test_email_parser.py::test_split_list_fewer_than_two_linked_items_returns_none PASSED [ 11%]
tests/test_email_parser.py::test_split_list_not_triggered_for_paragraph PASSED [ 13%]
tests/test_email_parser.py::test_extract_sections_splits_multi_item_list PASSED [ 15%]
tests/test_email_parser.py::test_extract_sections_story_link_not_contaminated_by_neighbour PASSED [ 16%]
tests/test_email_parser.py::test_extract_sections_single_story_sponsor_unaffected PASSED [ 18%]
tests/test_email_parser.py::test_extract_sections_regular_paragraph_unaffected PASSED [ 20%]
tests/test_email_parser.py::test_extract_title_heading_line PASSED       [ 22%]
tests/test_email_parser.py::test_extract_title_h2_heading PASSED         [ 24%]
tests/test_email_parser.py::test_extract_title_no_heading PASSED         [ 26%]
tests/test_email_parser.py::test_extract_title_empty_heading PASSED      [ 28%]
tests/test_email_parser.py::test_extract_title_leading_blank_lines_skipped PASSED [ 30%]
tests/test_email_parser.py::test_select_link_returns_first_url PASSED    [ 32%]
tests/test_email_parser.py::test_select_link_empty_returns_none PASSED   [ 33%]
tests/test_email_parser.py::test_parse_emails_returns_story_records PASSED [ 35%]
tests/test_email_parser.py::test_parse_emails_newsletter_field PASSED    [ 37%]
tests/test_email_parser.py::test_parse_emails_date_field_format PASSED   [ 39%]
tests/test_email_parser.py::test_parse_emails_title_extracted_from_heading PASSED [ 41%]
tests/test_email_parser.py::test_parse_emails_title_none_when_no_heading PASSED [ 43%]
tests/test_email_parser.py::test_parse_emails_link_extracted PASSED      [ 45%]
tests/test_email_parser.py::test_parse_emails_link_none_when_no_link PASSED [ 47%]
tests/test_email_parser.py::test_parse_emails_short_item_preserved PASSED [ 49%]
tests/test_email_parser.py::test_parse_emails_empty_email_skipped PASSED [ 50%]
tests/test_email_parser.py::test_parse_emails_multiple_emails_flat_list PASSED [ 52%]
tests/test_email_parser.py::test_table_artifact_dropped PASSED           [ 54%]
tests/test_email_parser.py::test_empty_anchor_link_stripped_from_body PASSED [ 56%]
tests/test_email_parser.py::test_toc_section_dropped PASSED              [ 58%]
tests/test_email_parser.py::test_story_with_multiple_inline_links_not_dropped PASSED [ 60%]
tests/test_email_parser.py::test_intro_signal_section_dropped PASSED     [ 62%]
tests/test_email_parser.py::test_short_valid_story_still_preserved_after_phase2 PASSED [ 64%]
tests/test_email_parser.py::test_heading_with_pipe_body_not_a_story PASSED [ 66%]
tests/test_email_parser.py::test_titled_section_with_pipe_body_dropped_by_parse_emails PASSED [ 67%]
tests/test_deduplicator.py::test_single_item_cluster_returns_that_item PASSED [ 69%]
tests/test_deduplicator.py::test_longest_body_wins PASSED                [ 71%]
tests/test_deduplicator.py::test_title_breaks_body_tie PASSED            [ 73%]
tests/test_deduplicator.py::test_link_breaks_remaining_tie PASSED        [ 75%]
tests/test_deduplicator.py::test_earliest_date_overrides_representative_date PASSED [ 77%]
tests/test_deduplicator.py::test_original_record_not_mutated PASSED      [ 79%]
tests/test_deduplicator.py::test_all_empty_dates_preserves_representative_date PASSED [ 81%]
tests/test_deduplicator.py::test_representative_date_from_partial_empty_dates PASSED [ 83%]
tests/test_deduplicator.py::test_three_item_cluster_selects_longest PASSED [ 84%]
tests/test_deduplicator.py::test_deduplicate_empty_clusters_returns_empty PASSED [ 86%]
tests/test_deduplicator.py::test_deduplicate_skips_empty_clusters PASSED [ 88%]
tests/test_deduplicator.py::test_deduplicate_single_cluster_single_item PASSED [ 90%]
tests/test_deduplicator.py::test_deduplicate_single_cluster_multiple_items PASSED [ 92%]
tests/test_deduplicator.py::test_deduplicate_multiple_clusters_one_per_cluster PASSED [ 94%]
tests/test_deduplicator.py::test_deduplicate_returns_story_records PASSED [ 96%]
tests/test_deduplicator.py::test_deduplicate_date_override_propagates PASSED [ 98%]
tests/test_deduplicator.py::test_deduplicate_large_cluster_no_exception PASSED [100%]

============================== 53 passed in 0.18s ==============================
```

### Level 5 — Real-email re-inspection

```
$ python -c "
import sys; sys.path.insert(0, '.')
from ingestion.email_parser import parse_emails
with open('debug_samples/the_deep_view.eml', 'rb') as f:
    raw = f.read()
records = parse_emails([raw])
pipe_records = [r for r in records if r.body.strip() == '|']
print(f'Total records: {len(records)}')
print(f'Records with body=\"|\": {len(pipe_records)}')
if pipe_records:
    for r in pipe_records:
        print(f'  title={r.title!r}')
else:
    print('No pipe-body records — Phase 3 fix is working.')
"

Total records: 40
Records with body="|": 0
No pipe-body records — Phase 3 fix is working.
```

**Verified:**
- Real-email record count dropped from 45 → 40 (5 `body='|'` records correctly eliminated). ✓
- Zero `body='|'` records remain. ✓
- All 53 tests passing (36 email_parser + 17 deduplicator). ✓

---

## Ready for Commit

- [x] All tasks completed
- [x] All validation commands passed
- [x] All tests passing (53/53)

## Follow-up Items

- `ai/claude_client.py` — rewrite as binary keep/drop filter (next plan); currently imports `StoryGroup` which no longer exists
- `ai/story_reviewer.py` + `tests/test_story_reviewer.py` — delete (per prime summary)
- `processing/digest_builder.py` — rewrite full pipeline (subsequent plan)
