# Execution Report: deduplicator-representative-selection (Level 5 validations)

**Plan:** `.agents/plans/deduplicator-representative-selection.md`
**Date:** 2026-04-02
**Context:** Tasks 1–3 completed in prior execution (2026-04-02T21-57-51). This run executes the Level 5 cluster inspection validations added to the plan after initial implementation. Also fixes a marker logic bug discovered during execution.

---

## Pre-flight: syntax + unit tests

```
$ python -m py_compile processing/embedder.py && echo "embedder syntax ok"
embedder syntax ok

$ python -m py_compile processing/deduplicator.py && echo "deduplicator syntax ok"
deduplicator syntax ok

$ python -m pytest tests/test_email_parser.py tests/test_deduplicator.py -v

============================= test session starts ==============================
platform darwin -- Python 3.12.12, pytest-9.0.2, pluggy-1.6.0 -- /Users/natalie/Documents/Agentic AI/Newsletter Digest Agent/.venv/bin/python
cachedir: .pytest_cache
rootdir: /Users/natalie/Documents/Agentic AI/Newsletter Digest Agent
plugins: anyio-4.12.1
collecting ... collected 51 items

tests/test_email_parser.py::test_split_list_two_items_with_links PASSED  [  1%]
tests/test_email_parser.py::test_split_list_five_items_with_links PASSED [  3%]
tests/test_email_parser.py::test_split_list_preserves_link_per_item PASSED [  5%]
tests/test_email_parser.py::test_split_list_single_item_returns_none PASSED [  7%]
tests/test_email_parser.py::test_split_list_no_links_returns_none PASSED [  9%]
tests/test_email_parser.py::test_split_list_fewer_than_two_linked_items_returns_none PASSED [ 11%]
tests/test_email_parser.py::test_split_list_not_triggered_for_paragraph PASSED [ 13%]
tests/test_email_parser.py::test_extract_sections_splits_multi_item_list PASSED [ 15%]
tests/test_email_parser.py::test_extract_sections_story_link_not_contaminated_by_neighbour PASSED [ 17%]
tests/test_email_parser.py::test_extract_sections_single_story_sponsor_unaffected PASSED [ 19%]
tests/test_email_parser.py::test_extract_sections_regular_paragraph_unaffected PASSED [ 21%]
tests/test_email_parser.py::test_extract_title_heading_line PASSED       [ 23%]
tests/test_email_parser.py::test_extract_title_h2_heading PASSED         [ 25%]
tests/test_email_parser.py::test_extract_title_no_heading PASSED         [ 27%]
tests/test_email_parser.py::test_extract_title_empty_heading PASSED      [ 29%]
tests/test_email_parser.py::test_extract_title_leading_blank_lines_skipped PASSED [ 31%]
tests/test_email_parser.py::test_select_link_returns_first_url PASSED    [ 33%]
tests/test_email_parser.py::test_select_link_empty_returns_none PASSED   [ 35%]
tests/test_email_parser.py::test_parse_emails_returns_story_records PASSED [ 37%]
tests/test_email_parser.py::test_parse_emails_newsletter_field PASSED    [ 39%]
tests/test_email_parser.py::test_parse_emails_date_field_format PASSED   [ 41%]
tests/test_email_parser.py::test_parse_emails_title_extracted_from_heading PASSED [ 43%]
tests/test_email_parser.py::test_parse_emails_title_none_when_no_heading PASSED [ 45%]
tests/test_email_parser.py::test_parse_emails_link_extracted PASSED      [ 47%]
tests/test_email_parser.py::test_parse_emails_link_none_when_no_link PASSED [ 49%]
tests/test_email_parser.py::test_parse_emails_short_item_preserved PASSED [ 50%]
tests/test_email_parser.py::test_parse_emails_empty_email_skipped PASSED [ 52%]
tests/test_email_parser.py::test_parse_emails_multiple_emails_flat_list PASSED [ 54%]
tests/test_email_parser.py::test_table_artifact_dropped PASSED           [ 56%]
tests/test_email_parser.py::test_empty_anchor_link_stripped_from_body PASSED [ 58%]
tests/test_email_parser.py::test_toc_section_dropped PASSED              [ 60%]
tests/test_email_parser.py::test_story_with_multiple_inline_links_not_dropped PASSED [ 62%]
tests/test_email_parser.py::test_intro_signal_section_dropped PASSED     [ 64%]
tests/test_email_parser.py::test_short_valid_story_still_preserved_after_phase2 PASSED [ 66%]
tests/test_deduplicator.py::test_single_item_cluster_returns_that_item PASSED [ 68%]
tests/test_deduplicator.py::test_longest_body_wins PASSED                [ 70%]
tests/test_deduplicator.py::test_title_breaks_body_tie PASSED            [ 72%]
tests/test_deduplicator.py::test_link_breaks_remaining_tie PASSED        [ 74%]
tests/test_deduplicator.py::test_earliest_date_overrides_representative_date PASSED [ 76%]
tests/test_deduplicator.py::test_original_record_not_mutated PASSED      [ 78%]
tests/test_deduplicator.py::test_all_empty_dates_preserves_representative_date PASSED [ 80%]
tests/test_deduplicator.py::test_representative_date_from_partial_empty_dates PASSED [ 82%]
tests/test_deduplicator.py::test_three_item_cluster_selects_longest PASSED [ 84%]
tests/test_deduplicator.py::test_deduplicate_empty_clusters_returns_empty PASSED [ 86%]
tests/test_deduplicator.py::test_deduplicate_skips_empty_clusters PASSED [ 88%]
tests/test_deduplicator.py::test_deduplicate_single_cluster_single_item PASSED [ 90%]
tests/test_deduplicator.py::test_deduplicate_single_cluster_multiple_items PASSED [ 92%]
tests/test_deduplicator.py::test_deduplicate_multiple_clusters_one_per_cluster PASSED [ 94%]
tests/test_deduplicator.py::test_deduplicate_returns_story_records PASSED [ 96%]
tests/test_deduplicator.py::test_deduplicate_date_override_propagates PASSED [ 98%]
tests/test_deduplicator.py::test_deduplicate_large_cluster_no_exception PASSED [100%]

51 passed in 0.25s
```

---

## Plan fix: marker logic bug discovered during Level 5 execution

The inspection scripts in the plan used value equality to identify the representative (`item.body == rep.body and item.newsletter == rep.newsletter`). Because `select_representative()` uses `dataclasses.replace()`, the returned `rep` is a new object — not one of the original cluster items. When multiple items share identical `body` and `newsletter` values (as the `body='|'` cluster does), all of them get marked `[REPRESENTATIVE]`.

**Fix applied to plan:** Both Level 5a and 5b scripts now identify the representative by index using the same `max()` key as `select_representative()`:

```python
rep_idx = max(range(len(cluster)), key=lambda j: (
    len(cluster[j].body), cluster[j].title is not None, cluster[j].link is not None
))
```

This matches exactly one item per cluster regardless of field value collisions.

---

## Level 5a — Synthetic cluster inspection (fixed script)

```
$ python -c "..."  (full script in plan Level 5a)

=== Cluster 1 (2 item(s)) ===
  [ duplicate    ]  newsletter='TLDR AI'             date=2026-03-10  body_len=  27  title=None
               body: 'Short version of the story.'
  [REPRESENTATIVE]  newsletter='The Deep View'       date=2026-03-17  body_len= 187  title='Nvidia bets on robotics'
               body: 'Nvidia announced several new robotics platforms at GTC 2026, including a full-st'
  -> selected date (earliest): 2026-03-10

=== Cluster 2 (2 item(s)) ===
  [ duplicate    ]  newsletter='NL A'                date=2026-03-15  body_len=  22  title=None
               body: 'Same body length here!'
  [REPRESENTATIVE]  newsletter='NL B'                date=2026-03-17  body_len=  22  title='Headline wins'
               body: 'Same body length here!'
  -> selected date (earliest): 2026-03-15

=== Cluster 3 (1 item(s)) ===
  [REPRESENTATIVE]  newsletter='AI Breakfast'        date=2026-03-14  body_len=  66  title=None
               body: 'OpenAI cut API prices for GPT-4o by 50 percent starting this week.'
  -> selected date (earliest): 2026-03-14
```

**Verified:**
- Cluster 1: The Deep View item is `[REPRESENTATIVE]` (body_len=187 beats 27). Date overridden to 2026-03-10 (from TLDR AI item). ✓
- Cluster 2: NL B item is `[REPRESENTATIVE]` (body lengths equal at 22; title tiebreaker wins). Date overridden to 2026-03-15 (from NL A item). ✓
- Cluster 3: Singleton returned unchanged. ✓

---

## Level 5b — Real email end-to-end inspection (fixed script)

```
$ python -c "..."  (full script in plan Level 5b)

Parsed: 45 story records
Clustered: 41 groups (5 items in multi-item clusters)
Deduplicated: 41 representatives

=== 1 multi-item cluster(s) ===
--- Group 1 (5 items) ---
  [REP]  body_len=   1  title='Nvidia builds the tech stack for the robotics era'
         body: '|'
  [dup]  body_len=   1  title='Want To Give Every Employee The Power of AI?'
         body: '|'
  [dup]  body_len=   1  title='Nvidia unveils a different vision of AI-in-space'
         body: '|'
  [dup]  body_len=   1  title='How to Get More Out of Microsoft 365 with Slack'
         body: '|'
  [dup]  body_len=   1  title='OpenAI expands its enterprise AI plans'
         body: '|'
  -> representative date: 2026-03-17

--- All representatives (first 5) ---
  date=2026-03-17  newsletter='The Deep View'  title='Nvidia builds the tech stack for the robotics era'
  body: '|'

  date=2026-03-17  newsletter='The Deep View'  title=None
  body: '**Welcome back.** Nvidia announced several new bets on Monday at GTC 2026. In sp'

  date=2026-03-17  newsletter='The Deep View'  title=None
  body: 'Nvidia is betting on robots, without actually building any robots.   \nOn Monday,'

  date=2026-03-17  newsletter='The Deep View'  title=None
  body: 'This isn't the first time in recent history that Huang has proclaimed AI's futur'

  date=2026-03-17  newsletter='The Deep View'  title=None
  body: 'GTC COVERAGE BROUGHT TO YOU BY IREN  \n  \n# Unleashing NVIDIA Blackwell Performan'
```

**Verified:**
- 45 records parsed → 41 groups → 41 representatives. Dedup count ≤ parsed count. ✓
- Exactly one `[REP]` in the multi-item cluster. ✓
- The `[REP]` has the first-maximum body_len (all equal at 1 — first item in `max()` wins). ✓
- Representative date is 2026-03-17 (only date available; all items in this cluster have the same date). ✓

**Observation — `body='|'` cluster:**
The one multi-item cluster groups 5 records that all have `body='|'` — these are the residual table-artifact records noted in the prior execution report (titles set, body collapsed to `|` after `_extract_title()` strips the heading, leaving only a pipe from a table fragment). The deduplication itself is correct: 5 near-identical items → 1 representative. The underlying data quality issue (these records should ideally not exist) is a known email_parser edge case deferred to the LLM filter stage.

---

## Ready for Commit

- [x] All tasks completed (Tasks 1–3 from prior run; Level 5 validations this run)
- [x] All validation commands passed
- [x] 51/51 tests passing
- [x] Level 5a: all three synthetic clusters correct
- [x] Level 5b: real email pipeline runs end-to-end; 1 multi-item cluster correctly deduplicated

## Follow-up Items

- `body='|'` records: 5 residual table-artifact records in the_deep_view.eml have title set but body='|'. The `_is_table_artifact()` filter in email_parser doesn't catch these because the full section text (heading + `|`) passes the 15% pipe threshold. The LLM filter will handle them downstream. If they become a pattern across more emails, revisit email_parser Phase 3.
- `ai/claude_client.py` — rewrite as binary keep/drop filter (next plan); currently imports `StoryGroup` which no longer exists
- `ai/story_reviewer.py` + `tests/test_story_reviewer.py` — delete (per prime summary)
- `processing/digest_builder.py` — rewrite full pipeline (subsequent plan)
