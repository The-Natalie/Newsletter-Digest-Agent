# Execution Report: improve-noise-filter-and-dedup-precision

**Plan:** `.agents/plans/improve-noise-filter-and-dedup-precision.md`
**Started:** 2026-04-08T23:09:22Z
**Status:** COMPLETE

---

## Files Modified

- `ai/claude_client.py`

---

## Task 1: Update `_NOISE_SYSTEM_PROMPT` and `_NOISE_MAX_BODY_CHARS`

### Changes made

- `_NOISE_MAX_BODY_CHARS`: 200 → 300
- `_NOISE_SYSTEM_PROMPT`: replaced with updated version

**New noise prompt adds:**
- Session blurbs and agenda items (conference schedule entries, panel descriptions, event time/location notices with no substantive news content)
- Tool-tip and feature-callout marketing (product pitches framed as tips with no real news)
- Purely promotional sponsor copy (taglines, brand-awareness, buzzword-heavy ad text) with explicit carve-out: sponsor content that provides specific usable facts is KEEP
- "Specific usable facts" test for KEEP rule: named product with concrete capability, specific offer or discount, date-bound event, factual explanation a reader could act on
- Tighter pure-CTA definition: "where the entire item is the CTA with nothing else"

### Task 1 validation

```
cd "/Users/natalie/Documents/Agentic AI/Newsletter Digest Agent" && python -c "from ai.claude_client import _NOISE_MAX_BODY_CHARS, _REFINE_MAX_BODY_CHARS; assert _NOISE_MAX_BODY_CHARS == 300, f'expected 300, got {_NOISE_MAX_BODY_CHARS}'; assert _REFINE_MAX_BODY_CHARS == 350, f'expected 350, got {_REFINE_MAX_BODY_CHARS}'; print('constants OK')"
```
Output:
```
constants OK
```

---

## Task 2: Update `_REFINE_SYSTEM_PROMPT` and `_REFINE_MAX_BODY_CHARS`

### Changes made

- `_REFINE_MAX_BODY_CHARS`: 250 → 350
- `_REFINE_SYSTEM_PROMPT`: replaced with updated version

**New refine prompt adds:**
- `same_story` definition now requires "SAME single announcement, product release, or event" (not just "same specific event, announcement, or development")
- `related_but_distinct` section now includes three concrete conference-multi-story anti-examples:
  1. Broad conference recap vs. focused story on one announcement from same conference
  2. Robotics platform launch vs. inference chip performance (same company, same conference)
  3. Keynote highlights across several topics vs. one specific product announcement
- Critical rule added explicitly: "Same company + same conference + same day does NOT make stories the same"
- "Same specific announcement" test as the primary question
- "If each story contains developments or details not in the other, they are related_but_distinct"

---

## Manual Prompt Review

```
cd "/Users/natalie/Documents/Agentic AI/Newsletter Digest Agent" && python -c "
from ai.claude_client import _NOISE_SYSTEM_PROMPT, _REFINE_SYSTEM_PROMPT, _NOISE_MAX_BODY_CHARS, _REFINE_MAX_BODY_CHARS
print('=== NOISE FILTER ===')
print(f'Max body chars: {_NOISE_MAX_BODY_CHARS}')
print(_NOISE_SYSTEM_PROMPT)
print()
print('=== REFINE CLUSTERS ===')
print(f'Max body chars: {_REFINE_MAX_BODY_CHARS}')
print(_REFINE_SYSTEM_PROMPT)
"
```

Output:
```
=== NOISE FILTER ===
Max body chars: 300
You are a pre-processing filter for a newsletter digest pipeline. Your only job is to remove obvious structural noise before content analysis.

Mark is_noise=True ONLY for items that clearly contain no article or news content:
- Sponsor or referral blocks that are purely promotional: taglines, brand-awareness copy, buzzword-heavy ad text with no specific facts ('AI-powered. Enterprise-grade. Transform your workflow.'). NOT the same as sponsor content that explains a specific product or offer — see KEEP rules.
- Newsletter infrastructure: subscribe/unsubscribe prompts, account management, referral incentive programs ('Refer 3 friends to unlock...')
- Session blurbs and agenda items: conference schedule entries, panel descriptions, event time/location notices with no substantive news content ('Join us Thursday at 2pm for a discussion on AI safety')
- Tool-tip and feature-callout marketing: product pitches framed as tips ('Did you know you can use X to do Y?') with no real news or factual content
- Pure CTAs with no substantive content: 'Click here', 'Sign up today', 'Get started free' — where the entire item is the CTA with nothing else
- Newsletter intro/outro shells: 'Welcome to today's issue', 'That's all for this week', editor's notes with no article content
- Polls and surveys: 'How did we do? Vote below', reader feedback requests

Mark is_noise=False (KEEP) for everything else, including:
- Any real article, news item, announcement, or report — even if short or low quality
- Sponsor content that provides specific, usable facts: a named product with a concrete capability, a specific offer or discount, a date-bound event, or a factual explanation a reader could act on. The test: does this item give the reader specific information they could use? If yes, keep it.
- Job listings, product launches, research summaries, tool releases, event notices
- Any item that is ambiguous — when in doubt, always keep

This filter is maximally conservative. It is better to keep 10 noisy items than to accidentally remove one real article.

=== REFINE CLUSTERS ===
Max body chars: 350
You are a deduplication assistant for a newsletter digest. You will be shown pairs of story excerpts from different newsletters that scored above the embedding similarity threshold.

For each pair, classify the relationship:

'same_story' — Both stories are specifically reporting on the SAME single announcement, product release, or event. The underlying news item is identical even if the writing style, length, or framing differs. Example: TLDR says 'OpenAI released GPT-5 today' and The Deep View says 'OpenAI unveils GPT-5 with enhanced reasoning' — same story.

'related_but_distinct' — The stories share context (same company, same conference, same day, same broad topic) but cover DIFFERENT specific developments or announcements. Each story contains information not present in the other. Examples:
- A broad conference recap covering multiple announcements vs. a story focused on one specific announcement from that same conference — related_but_distinct.
- Two stories from the same company at the same conference: one covers their robotics platform launch, another covers their inference chip performance — related_but_distinct.
- One story covers the keynote highlights across several topics; another covers one specific product announcement from that keynote — related_but_distinct.

'different' — The stories are about unrelated topics.

Critical rule: Same company + same conference + same day does NOT make stories the same. Ask: are both stories reporting on the exact same single announcement? If each story contains developments or details not in the other, they are related_but_distinct.

When in doubt, use 'related_but_distinct' or 'different'. Only use 'same_story' when you are confident both stories are covering the same specific event. It is better to show a near-duplicate than to hide a distinct story.
```

---

## Validation Commands

### Level 1: Import check

```
cd "/Users/natalie/Documents/Agentic AI/Newsletter Digest Agent" && python -c "from ai.claude_client import _NOISE_MAX_BODY_CHARS, _NOISE_SYSTEM_PROMPT, _REFINE_MAX_BODY_CHARS, _REFINE_SYSTEM_PROMPT; print('imports OK')"
```
Output:
```
imports OK
```

### Level 2: Constant value checks

```
cd "/Users/natalie/Documents/Agentic AI/Newsletter Digest Agent" && python -c "from ai.claude_client import _NOISE_MAX_BODY_CHARS, _REFINE_MAX_BODY_CHARS; assert _NOISE_MAX_BODY_CHARS == 300, f'expected 300, got {_NOISE_MAX_BODY_CHARS}'; assert _REFINE_MAX_BODY_CHARS == 350, f'expected 350, got {_REFINE_MAX_BODY_CHARS}'; print('constants OK')"
```
Output:
```
constants OK
```

### Level 3: Noise filter unit tests

```
cd "/Users/natalie/Documents/Agentic AI/Newsletter Digest Agent" && python -m pytest tests/test_claude_client.py -v -k "noise"
```
Output:
```
============================= test session starts ==============================
platform darwin -- Python 3.12.12, pytest-9.0.2, pluggy-1.6.0 -- /Users/natalie/Documents/Agentic AI/Newsletter Digest Agent/.venv/bin/python
cachedir: .pytest_cache
rootdir: /Users/natalie/Documents/Agentic AI/Newsletter Digest Agent
plugins: anyio-4.12.1
collecting ... collected 22 items / 15 deselected / 7 selected

tests/test_claude_client.py::test_noise_batch_size PASSED                [ 14%]
tests/test_claude_client.py::test_noise_tool_name PASSED                 [ 28%]
tests/test_claude_client.py::test_noise_schema_is_noise_field PASSED     [ 42%]
tests/test_claude_client.py::test_noise_batch_split_95_stories PASSED    [ 57%]
tests/test_claude_client.py::test_noise_message_includes_newsletter_name PASSED [ 71%]
tests/test_claude_client.py::test_noise_message_includes_body_excerpt PASSED [ 85%]
tests/test_claude_client.py::test_noise_message_truncates_long_body PASSED [100%]

======================= 7 passed, 15 deselected in 0.31s =======================
```

### Level 4: Refine unit tests

```
cd "/Users/natalie/Documents/Agentic AI/Newsletter Digest Agent" && python -m pytest tests/test_claude_client.py -v -k "refine"
```
Output:
```
============================= test session starts ==============================
platform darwin -- Python 3.12.12, pytest-9.0.2, pluggy-1.6.0 -- /Users/natalie/Documents/Agentic AI/Newsletter Digest Agent/.venv/bin/python
cachedir: .pytest_cache
rootdir: /Users/natalie/Documents/Agentic AI/Newsletter Digest Agent
plugins: anyio-4.12.1
collecting ... collected 22 items / 16 deselected / 6 selected

tests/test_claude_client.py::test_refine_batch_size PASSED               [ 16%]
tests/test_claude_client.py::test_refine_tool_name PASSED                [ 33%]
tests/test_claude_client.py::test_refine_schema_relationship_enum PASSED [ 50%]
tests/test_claude_client.py::test_refine_relationship_enum_values PASSED [ 66%]
tests/test_claude_client.py::test_refine_message_labels_newsletter PASSED [ 83%]
tests/test_claude_client.py::test_refine_batch_split_45_pairs PASSED     [100%]

======================= 6 passed, 16 deselected in 0.34s =======================
```

### Level 5: Full test suite

```
cd "/Users/natalie/Documents/Agentic AI/Newsletter Digest Agent" && python -m pytest tests/ -v
```
Output:
```
============================= test session starts ==============================
platform darwin -- Python 3.12.12, pytest-9.0.2, pluggy-1.6.0 -- /Users/natalie/Documents/Agentic AI/Newsletter Digest Agent/.venv/bin/python
cachedir: .pytest_cache
rootdir: /Users/natalie/Documents/Agentic AI/Newsletter Digest Agent
plugins: anyio-4.12.1
collecting ... collected 114 items

tests/test_claude_client.py::test_filter_batch_size PASSED               [  0%]
tests/test_claude_client.py::test_filter_tool_name PASSED                [  1%]
tests/test_claude_client.py::test_filter_schema_decisions_array PASSED   [  2%]
tests/test_claude_client.py::test_filter_batch_split_75_stories PASSED   [  3%]
tests/test_claude_client.py::test_filter_batch_split_26_stories PASSED   [  4%]
tests/test_claude_client.py::test_filter_message_includes_newsletter_name PASSED [  5%]
tests/test_claude_client.py::test_filter_message_includes_title_when_present PASSED [  6%]
tests/test_claude_client.py::test_filter_message_includes_body_excerpt PASSED [  7%]
tests/test_claude_client.py::test_filter_message_truncates_long_body PASSED [  7%]
tests/test_claude_client.py::test_noise_batch_size PASSED                [  8%]
tests/test_claude_client.py::test_noise_tool_name PASSED                 [  9%]
tests/test_claude_client.py::test_noise_schema_is_noise_field PASSED     [ 10%]
tests/test_claude_client.py::test_noise_batch_split_95_stories PASSED    [ 11%]
tests/test_claude_client.py::test_noise_message_includes_newsletter_name PASSED [ 12%]
tests/test_claude_client.py::test_noise_message_includes_body_excerpt PASSED [ 13%]
tests/test_claude_client.py::test_noise_message_truncates_long_body PASSED [ 14%]
tests/test_claude_client.py::test_refine_batch_size PASSED               [ 14%]
tests/test_claude_client.py::test_refine_tool_name PASSED                [ 15%]
tests/test_claude_client.py::test_refine_schema_relationship_enum PASSED [ 16%]
tests/test_claude_client.py::test_refine_relationship_enum_values PASSED [ 17%]
tests/test_claude_client.py::test_refine_message_labels_newsletter PASSED [ 18%]
tests/test_claude_client.py::test_refine_batch_split_45_pairs PASSED     [ 19%]
tests/test_deduplicator.py::test_single_item_cluster_returns_that_item PASSED [ 20%]
tests/test_deduplicator.py::test_longest_body_wins PASSED                [ 21%]
tests/test_deduplicator.py::test_title_breaks_body_tie PASSED            [ 21%]
tests/test_deduplicator.py::test_link_breaks_remaining_tie PASSED        [ 22%]
tests/test_deduplicator.py::test_earliest_date_overrides_representative_date PASSED [ 23%]
tests/test_deduplicator.py::test_original_record_not_mutated PASSED      [ 24%]
tests/test_deduplicator.py::test_all_empty_dates_preserves_representative_date PASSED [ 25%]
tests/test_deduplicator.py::test_representative_date_from_partial_empty_dates PASSED [ 26%]
tests/test_deduplicator.py::test_three_item_cluster_selects_longest PASSED [ 27%]
tests/test_deduplicator.py::test_deduplicate_empty_clusters_returns_empty PASSED [ 28%]
tests/test_deduplicator.py::test_deduplicate_skips_empty_clusters PASSED [ 28%]
tests/test_deduplicator.py::test_deduplicate_single_cluster_single_item PASSED [ 29%]
tests/test_deduplicator.py::test_deduplicate_single_cluster_multiple_items PASSED [ 30%]
tests/test_deduplicator.py::test_deduplicate_multiple_clusters_one_per_cluster PASSED [ 31%]
tests/test_deduplicator.py::test_deduplicate_returns_story_records PASSED [ 32%]
tests/test_deduplicator.py::test_deduplicate_date_override_propagates PASSED [ 33%]
tests/test_deduplicator.py::test_deduplicate_large_cluster_no_exception PASSED [ 34%]
tests/test_deduplicator.py::test_select_representative_merges_links_from_cluster PASSED [ 35%]
tests/test_deduplicator.py::test_select_representative_deduplicates_links PASSED [ 35%]
tests/test_deduplicator.py::test_select_representative_sets_source_count PASSED [ 36%]
tests/test_deduplicator.py::test_select_representative_single_item_source_count_is_1 PASSED [ 37%]
tests/test_deduplicator.py::test_deduplicate_source_count_set_on_representatives PASSED [ 38%]
tests/test_deduplicator.py::test_merge_confirmed_no_pairs_returns_original PASSED [ 39%]
tests/test_deduplicator.py::test_merge_confirmed_single_pair PASSED      [ 40%]
tests/test_deduplicator.py::test_merge_confirmed_transitivity PASSED     [ 41%]
tests/test_deduplicator.py::test_merge_confirmed_unconfirmed_clusters_preserved PASSED [ 42%]
tests/test_deduplicator.py::test_merge_confirmed_multi_item_clusters PASSED [ 42%]
tests/test_email_parser.py::test_split_list_two_items_with_links PASSED  [ 43%]
tests/test_email_parser.py::test_split_list_five_items_with_links PASSED [ 44%]
tests/test_email_parser.py::test_split_list_preserves_link_per_item PASSED [ 45%]
tests/test_email_parser.py::test_split_list_single_item_returns_none PASSED [ 46%]
tests/test_email_parser.py::test_split_list_no_links_returns_none PASSED [ 47%]
tests/test_email_parser.py::test_split_list_fewer_than_two_linked_items_returns_none PASSED [ 48%]
tests/test_email_parser.py::test_split_list_not_triggered_for_paragraph PASSED [ 49%]
tests/test_email_parser.py::test_extract_sections_splits_multi_item_list PASSED [ 50%]
tests/test_email_parser.py::test_extract_sections_story_link_not_contaminated_by_neighbour PASSED [ 50%]
tests/test_email_parser.py::test_extract_sections_single_story_sponsor_unaffected PASSED [ 51%]
tests/test_email_parser.py::test_extract_sections_regular_paragraph_unaffected PASSED [ 52%]
tests/test_email_parser.py::test_extract_title_heading_line PASSED       [ 53%]
tests/test_email_parser.py::test_extract_title_h2_heading PASSED         [ 54%]
tests/test_email_parser.py::test_extract_title_no_heading PASSED         [ 55%]
tests/test_email_parser.py::test_extract_title_empty_heading PASSED      [ 56%]
tests/test_email_parser.py::test_extract_title_leading_blank_lines_skipped PASSED [ 57%]
tests/test_email_parser.py::test_collect_links_returns_all_urls PASSED   [ 57%]
tests/test_email_parser.py::test_collect_links_empty_returns_empty_list PASSED [ 58%]
tests/test_email_parser.py::test_parse_emails_returns_story_records PASSED [ 59%]
tests/test_email_parser.py::test_parse_emails_newsletter_field PASSED    [ 60%]
tests/test_email_parser.py::test_parse_emails_date_field_format PASSED   [ 61%]
tests/test_email_parser.py::test_parse_emails_title_extracted_from_heading PASSED [ 62%]
tests/test_email_parser.py::test_parse_emails_title_none_when_no_heading PASSED [ 63%]
tests/test_email_parser.py::test_parse_emails_link_extracted PASSED      [ 64%]
tests/test_email_parser.py::test_parse_emails_link_none_when_no_link PASSED [ 65%]
tests/test_email_parser.py::test_parse_emails_short_item_preserved PASSED [ 65%]
tests/test_email_parser.py::test_parse_emails_empty_email_skipped PASSED [ 66%]
tests/test_email_parser.py::test_parse_emails_multiple_emails_flat_list PASSED [ 67%]
tests/test_email_parser.py::test_table_artifact_dropped PASSED           [ 68%]
tests/test_email_parser.py::test_empty_anchor_link_stripped_from_body PASSED [ 69%]
tests/test_email_parser.py::test_toc_section_dropped PASSED              [ 70%]
tests/test_email_parser.py::test_story_with_multiple_inline_links_not_dropped PASSED [ 71%]
tests/test_email_parser.py::test_intro_signal_section_dropped PASSED     [ 71%]
tests/test_email_parser.py::test_short_valid_story_still_preserved_after_phase2 PASSED [ 72%]
tests/test_email_parser.py::test_heading_with_pipe_body_not_a_story PASSED [ 73%]
tests/test_email_parser.py::test_titled_section_with_pipe_body_dropped_by_parse_emails PASSED [ 74%]
tests/test_email_parser.py::test_trailing_pipe_stripped_from_body PASSED [ 75%]
tests/test_email_parser.py::test_xa0_normalized_in_body PASSED           [ 76%]
tests/test_email_parser.py::test_together_with_section_not_dropped PASSED [ 77%]
tests/test_email_parser.py::test_thanks_for_reading_section_not_dropped PASSED [ 78%]
tests/test_email_parser.py::test_story_heading_collects_following_paragraphs PASSED [ 79%]
tests/test_email_parser.py::test_category_heading_does_not_merge_following_stories PASSED [ 79%]
tests/test_email_parser.py::test_bold_title_extracted_as_story_title PASSED [ 80%]
tests/test_email_parser.py::test_links_field_is_list PASSED              [ 81%]
tests/test_email_parser.py::test_links_field_contains_story_urls PASSED  [ 82%]
tests/test_email_parser.py::test_source_count_default_is_1 PASSED        [ 83%]
tests/test_email_parser.py::test_boilerplate_unicode_apostrophe_dropped PASSED [ 84%]
tests/test_email_parser.py::test_bold_artifact_stripped_from_body PASSED [ 85%]
tests/test_email_parser.py::test_theme_label_not_absorbed_into_story_body PASSED [ 85%]
tests/test_email_parser.py::test_empty_anchor_image_link_captured PASSED [ 86%]
tests/test_email_parser.py::test_trailing_table_artifact_line_stripped PASSED [ 87%]
tests/test_email_parser.py::test_trailing_get_in_touch_line_stripped PASSED [ 88%]
tests/test_email_parser.py::test_split_list_preserves_link_free_items PASSED [ 89%]
tests/test_email_parser.py::test_sponsor_separated_continuation_assembled PASSED [ 90%]
tests/test_email_parser.py::test_trailing_whitespace_stripped_from_body PASSED [ 91%]
tests/test_email_parser.py::test_nested_bracket_anchor_link_extracted PASSED [ 92%]
tests/test_email_parser.py::test_is_story_heading_second_line PASSED     [ 92%]
tests/test_email_parser.py::test_extract_title_second_line_heading PASSED [ 93%]
tests/test_email_parser.py::test_category_label_then_heading_splits_into_separate_story PASSED [ 94%]
tests/test_embedder.py::test_embed_and_cluster_empty_input PASSED        [ 95%]
tests/test_embedder.py::test_embed_and_cluster_single_item PASSED        [ 96%]
tests/test_embedder.py::test_embed_and_cluster_identical_stories_same_cluster PASSED [ 97%]
tests/test_embedder.py::test_embed_and_cluster_unrelated_stories_separate_clusters PASSED [ 98%]
tests/test_embedder.py::test_embed_and_cluster_all_records_present PASSED [ 99%]
tests/test_embedder.py::test_embed_and_cluster_no_record_in_multiple_clusters PASSED [100%]

============================= 114 passed in 6.24s ==============================
```

---

## Deviations

None. Implementation followed the plan exactly.

---

## Ready for Commit

- [x] All tasks completed
- [x] All validation commands passed
- [x] All tests passing (114/114)

## Follow-up Items

- Run a live pipeline test against real newsletter data to verify the prompt changes produce better noise filter and dedup results
- If over-merging persists on a specific pair type, add it as a concrete named example in `_REFINE_SYSTEM_PROMPT` (the prompt is designed to be extended this way)
- If noise filter still passes certain item types through, they can be added explicitly to the NOISE list following the same bullet format
