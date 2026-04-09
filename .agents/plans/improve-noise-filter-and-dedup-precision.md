# Feature: improve-noise-filter-and-dedup-precision

The following plan should be complete, but validate codebase patterns before implementing.

Pay close attention to the exact constant names, string formatting style, and Unicode escape sequences used in the existing system prompts. Mirror them precisely.

## Feature Description

Two targeted prompt-engineering changes to `ai/claude_client.py`:

1. **Noise filter tightening:** The pre-cluster LLM noise filter (`filter_noise`) is letting through pure ads, promotional copy, session blurbs, tool-tip style content, and CTA-tainted items. The system prompt needs more precise categories and a clearer test for distinguishing substantive sponsor content from purely promotional copy.

2. **Dedup refinement sharpening:** The pairwise LLM dedup refinement (`refine_clusters`) is over-merging related-but-distinct stories — particularly when multiple stories from the same company appear at the same conference on the same day. The system prompt needs stronger guidance on the "same specific announcement" test and concrete examples of the conference multi-story failure case.

No schema changes. No infrastructure changes. No parser changes. No new files.

## User Story

As a newsletter digest user
I want the noise filter to catch pure promotional content and the dedup filter to keep distinct stories separate
So that the digest contains only real articles and no related stories are incorrectly merged into one

## Problem Statement

**Noise filter:** Items that are clearly non-article (pure ads, session blurbs, tool-tip marketing copy, promotional taglines) are surviving the pre-cluster filter and entering embedding + clustering, adding noise to the pipeline.

**Dedup refinement:** Stories covering different aspects of the same company's conference appearance (broad keynote recap, robotics platform announcement, chip performance news, inference cost strategy) are being classified as `same_story` and merged, hiding distinct stories from the reader.

## Scope

- In scope: `_NOISE_SYSTEM_PROMPT` and `_NOISE_MAX_BODY_CHARS` in `ai/claude_client.py`
- In scope: `_REFINE_SYSTEM_PROMPT` and `_REFINE_MAX_BODY_CHARS` in `ai/claude_client.py`
- Out of scope: schema changes, batch size changes, new functions, parser changes, `filter_stories`

## Solution Statement

**Noise filter:** Expand the NOISE categories to explicitly name session blurbs, promotional copy without specific facts, and tool-tip style marketing. Tighten the keep rule for sponsor content by adding a concrete test: keep if it provides specific usable facts; remove if it is purely brand-awareness copy. Increase `_NOISE_MAX_BODY_CHARS` from 200 to 300 so the LLM sees enough content to make the promotional/informational distinction.

**Dedup refinement:** Add explicit guidance that same company + same conference + same day does NOT make stories the same. Add the "same specific announcement" test as the primary bar for `same_story`. Add a concrete anti-example covering the conference multi-story failure case. Increase `_REFINE_MAX_BODY_CHARS` from 250 to 350 so the LLM sees more of each story's distinct content.

## Feature Metadata

**Feature Type**: Bug Fix / Prompt Engineering
**Estimated Complexity**: Low
**Primary Systems Affected**: `ai/claude_client.py` only
**Dependencies**: None beyond existing Anthropic SDK
**Assumptions**: No test changes are needed — existing tests check schema structure and message format, not prompt text. The `_NOISE_MAX_BODY_CHARS` and `_REFINE_MAX_BODY_CHARS` constant changes are covered by existing truncation tests (which use `constant + 100` as input length).

---

## CONTEXT REFERENCES

### Relevant Codebase Files IMPORTANT: YOU MUST READ THESE FILES BEFORE IMPLEMENTING!

- `ai/claude_client.py` (lines 66–84) — Current `_NOISE_SYSTEM_PROMPT`: understand exact formatting, Unicode escapes (`\u2014`, `\u2019`), and the existing NOISE/KEEP structure before rewriting
- `ai/claude_client.py` (lines 30–32) — `_NOISE_MAX_BODY_CHARS = 200`: change to 300
- `ai/claude_client.py` (lines 240–257) — Current `_REFINE_SYSTEM_PROMPT`: understand exact formatting and the existing same_story/related_but_distinct/different structure before rewriting
- `ai/claude_client.py` (lines 201–203) — `_REFINE_MAX_BODY_CHARS = 250`: change to 350
- `tests/test_claude_client.py` — Read in full to confirm no test changes needed (all tests check schema structure, batch sizes, and message content — none test system prompt text)

### New Files to Create

None.

### Relevant Documentation

None required — this is a pure prompt-engineering change.

### Patterns to Follow

**String formatting:** Multi-line strings use implicit concatenation with `\n\n` within parentheses — not triple-quoted strings. Unicode characters use escape sequences (`\u2014` for em dash, `\u2019` for right single quote). Mirror this pattern exactly.

**Example from existing code (ai/claude_client.py:66–84):**
```python
_NOISE_SYSTEM_PROMPT = (
    "You are a pre-processing filter for a newsletter digest pipeline. "
    "Your only job is to remove obvious structural noise before content analysis.\n\n"
    "Mark is_noise=True ONLY for items that are clearly non-article structural content:\n"
    "- Sponsor or referral blocks: 'Refer 3 friends to unlock...', 'Sponsored by X'\n"
    ...
)
```

**Constant naming:** `_NOISE_MAX_BODY_CHARS`, `_REFINE_MAX_BODY_CHARS` — underscore-prefixed module-level constants, all caps with underscores.

---

## IMPLEMENTATION PLAN

### Phase 1: Noise filter prompt update

Update `_NOISE_SYSTEM_PROMPT` and `_NOISE_MAX_BODY_CHARS`.

### Phase 2: Dedup refinement prompt update

Update `_REFINE_SYSTEM_PROMPT` and `_REFINE_MAX_BODY_CHARS`.

---

## STEP-BY-STEP TASKS

### Task 1: UPDATE `ai/claude_client.py` — tighten `_NOISE_SYSTEM_PROMPT` and increase `_NOISE_MAX_BODY_CHARS`

- **IMPLEMENT**: Change `_NOISE_MAX_BODY_CHARS = 200` to `_NOISE_MAX_BODY_CHARS = 300`
- **IMPLEMENT**: Replace `_NOISE_SYSTEM_PROMPT` with the updated version below. Keep the same implicit string concatenation style and Unicode escape sequences as the existing code.
- **GOTCHA**: Do not change the schema, function signature, batch size, or any logic in `filter_noise`. This task is prompt text + one constant only.
- **GOTCHA**: The updated prompt must preserve the fail-open philosophy: when uncertain, always keep.
- **VALIDATE**: `cd "/Users/natalie/Documents/Agentic AI/Newsletter Digest Agent" && python -c "from ai.claude_client import _NOISE_MAX_BODY_CHARS, _NOISE_SYSTEM_PROMPT; assert _NOISE_MAX_BODY_CHARS == 300; assert 'session blurb' in _NOISE_SYSTEM_PROMPT.lower() or 'session' in _NOISE_SYSTEM_PROMPT.lower(); assert 'specific' in _NOISE_SYSTEM_PROMPT; print('NOISE prompt OK')"`

**New `_NOISE_SYSTEM_PROMPT` content (implement exactly this):**

```
"You are a pre-processing filter for a newsletter digest pipeline. "
"Your only job is to remove obvious structural noise before content analysis.\n\n"
"Mark is_noise=True ONLY for items that clearly contain no article or news content:\n"
"- Sponsor or referral blocks that are purely promotional: "
"taglines, brand-awareness copy, buzzword-heavy ad text with no specific facts "
"(\u2018AI-powered. Enterprise-grade. Transform your workflow.\u2019). "
"NOT the same as sponsor content that explains a specific product or offer \u2014 see KEEP rules.\n"
"- Newsletter infrastructure: subscribe/unsubscribe prompts, account management, "
"referral incentive programs (\u2018Refer 3 friends to unlock...\u2019)\n"
"- Session blurbs and agenda items: conference schedule entries, panel descriptions, "
"event time/location notices with no substantive news content "
"(\u2018Join us Thursday at 2pm for a discussion on AI safety\u2019)\n"
"- Tool-tip and feature-callout marketing: product pitches framed as tips "
"(\u2018Did you know you can use X to do Y?\u2019) with no real news or factual content\n"
"- Pure CTAs with no substantive content: \u2018Click here\u2019, \u2018Sign up today\u2019, "
"\u2018Get started free\u2019 \u2014 where the entire item is the CTA with nothing else\n"
"- Newsletter intro/outro shells: \u2018Welcome to today\u2019s issue\u2019, "
"\u2018That\u2019s all for this week\u2019, editor\u2019s notes with no article content\n"
"- Polls and surveys: \u2018How did we do? Vote below\u2019, reader feedback requests\n\n"
"Mark is_noise=False (KEEP) for everything else, including:\n"
"- Any real article, news item, announcement, or report \u2014 even if short or low quality\n"
"- Sponsor content that provides specific, usable facts: a named product with a concrete "
"capability, a specific offer or discount, a date-bound event, or a factual explanation "
"a reader could act on. The test: does this item give the reader specific information "
"they could use? If yes, keep it.\n"
"- Job listings, product launches, research summaries, tool releases, event notices\n"
"- Any item that is ambiguous \u2014 when in doubt, always keep\n\n"
"This filter is maximally conservative. It is better to keep 10 noisy items "
"than to accidentally remove one real article."
```

- **VALIDATE**: `cd "/Users/natalie/Documents/Agentic AI/Newsletter Digest Agent" && python -m pytest tests/test_claude_client.py -v -k "noise"`

---

### Task 2: UPDATE `ai/claude_client.py` — strengthen `_REFINE_SYSTEM_PROMPT` and increase `_REFINE_MAX_BODY_CHARS`

- **IMPLEMENT**: Change `_REFINE_MAX_BODY_CHARS = 250` to `_REFINE_MAX_BODY_CHARS = 350`
- **IMPLEMENT**: Replace `_REFINE_SYSTEM_PROMPT` with the updated version below. Keep the same implicit string concatenation style and Unicode escape sequences as the existing code.
- **GOTCHA**: Do not change the schema (the enum values `same_story`, `related_but_distinct`, `different` are tested by existing tests and must remain unchanged). Do not change `_REFINE_BATCH_SIZE`, function signature, or any logic in `refine_clusters`.
- **GOTCHA**: The fail-open bias must be preserved: when uncertain, use `related_but_distinct` or `different`, not `same_story`.
- **VALIDATE**: `cd "/Users/natalie/Documents/Agentic AI/Newsletter Digest Agent" && python -c "from ai.claude_client import _REFINE_MAX_BODY_CHARS, _REFINE_SYSTEM_PROMPT; assert _REFINE_MAX_BODY_CHARS == 350; assert 'same specific' in _REFINE_SYSTEM_PROMPT.lower() or 'specific announcement' in _REFINE_SYSTEM_PROMPT.lower(); print('REFINE prompt OK')"`

**New `_REFINE_SYSTEM_PROMPT` content (implement exactly this):**

```
"You are a deduplication assistant for a newsletter digest. "
"You will be shown pairs of story excerpts from different newsletters that "
"scored above the embedding similarity threshold.\n\n"
"For each pair, classify the relationship:\n\n"
"'same_story' \u2014 Both stories are specifically reporting on the SAME single "
"announcement, product release, or event. The underlying news item is identical "
"even if the writing style, length, or framing differs. "
"Example: TLDR says 'OpenAI released GPT-5 today' and The Deep View says "
"'OpenAI unveils GPT-5 with enhanced reasoning' \u2014 same story.\n\n"
"'related_but_distinct' \u2014 The stories share context (same company, same conference, "
"same day, same broad topic) but cover DIFFERENT specific developments or announcements. "
"Each story contains information not present in the other. "
"Examples:\n"
"- A broad conference recap covering multiple announcements vs. a story focused on one "
"specific announcement from that same conference \u2014 related_but_distinct.\n"
"- Two stories from the same company at the same conference: one covers their robotics "
"platform launch, another covers their inference chip performance \u2014 related_but_distinct.\n"
"- One story covers the keynote highlights across several topics; another covers one "
"specific product announcement from that keynote \u2014 related_but_distinct.\n\n"
"'different' \u2014 The stories are about unrelated topics.\n\n"
"Critical rule: Same company + same conference + same day does NOT make stories the same. "
"Ask: are both stories reporting on the exact same single announcement? "
"If each story contains developments or details not in the other, they are related_but_distinct.\n\n"
"When in doubt, use 'related_but_distinct' or 'different'. "
"Only use 'same_story' when you are confident both stories are covering the same specific event. "
"It is better to show a near-duplicate than to hide a distinct story."
```

- **VALIDATE**: `cd "/Users/natalie/Documents/Agentic AI/Newsletter Digest Agent" && python -m pytest tests/test_claude_client.py -v -k "refine"`

---

### Task 3: Run full test suite

- **VALIDATE**: `cd "/Users/natalie/Documents/Agentic AI/Newsletter Digest Agent" && python -m pytest tests/ -v`

---

## TESTING STRATEGY

### Unit Tests

No new tests required. All existing tests check schema structure, batch sizes, and message builder output (newsletter name in message, body truncation, body inclusion). None test system prompt text. The constant changes (`_NOISE_MAX_BODY_CHARS` 200→300, `_REFINE_MAX_BODY_CHARS` 250→350) are automatically covered by existing truncation tests, which use `constant + 100` as the long-body input.

### Integration Tests

Manual validation (see Level 4) is the appropriate test for prompt quality. Unit tests cannot evaluate LLM judgment quality.

### Edge Cases

- Sponsor content with specific facts must remain classified as ARTICLE (not noise) — verified by existing `test_noise_message_includes_body_excerpt`
- Dedup schema enum values must remain `["same_story", "related_but_distinct", "different"]` — verified by existing `test_refine_relationship_enum_values`
- Body truncation at new constant values must still work — verified by existing truncation tests

---

## VALIDATION COMMANDS

### Level 1: Import check

```bash
cd "/Users/natalie/Documents/Agentic AI/Newsletter Digest Agent" && python -c "from ai.claude_client import _NOISE_MAX_BODY_CHARS, _NOISE_SYSTEM_PROMPT, _REFINE_MAX_BODY_CHARS, _REFINE_SYSTEM_PROMPT; print('imports OK')"
```

### Level 2: Constant value checks

```bash
cd "/Users/natalie/Documents/Agentic AI/Newsletter Digest Agent" && python -c "from ai.claude_client import _NOISE_MAX_BODY_CHARS, _REFINE_MAX_BODY_CHARS; assert _NOISE_MAX_BODY_CHARS == 300, f'expected 300, got {_NOISE_MAX_BODY_CHARS}'; assert _REFINE_MAX_BODY_CHARS == 350, f'expected 350, got {_REFINE_MAX_BODY_CHARS}'; print('constants OK')"
```

### Level 3: Noise filter unit tests

```bash
cd "/Users/natalie/Documents/Agentic AI/Newsletter Digest Agent" && python -m pytest tests/test_claude_client.py -v -k "noise"
```

### Level 4: Refine unit tests

```bash
cd "/Users/natalie/Documents/Agentic AI/Newsletter Digest Agent" && python -m pytest tests/test_claude_client.py -v -k "refine"
```

### Level 5: Full test suite

```bash
cd "/Users/natalie/Documents/Agentic AI/Newsletter Digest Agent" && python -m pytest tests/ -v
```

### Level 6: Manual validation

After implementation, review the updated prompts directly:

```bash
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

Verify visually:
- Noise prompt mentions session blurbs, promotional copy without specific facts, and the "specific usable facts" keep test
- Refine prompt mentions "same specific announcement" and includes the conference multi-story anti-examples

---

## MANUAL VERIFICATION CHECKLIST

- [ ] `_NOISE_MAX_BODY_CHARS` is 300
- [ ] `_REFINE_MAX_BODY_CHARS` is 350
- [ ] Noise prompt includes session blurbs as a NOISE category
- [ ] Noise prompt includes the "specific usable facts" test for sponsor content
- [ ] Noise prompt does NOT drop sponsor content that provides specific facts
- [ ] Refine prompt includes "same specific announcement" as the `same_story` test
- [ ] Refine prompt explicitly states that same company + same conference + same day ≠ same story
- [ ] Refine prompt includes conference multi-story examples under `related_but_distinct`
- [ ] Full test suite passes (no regressions)
- [ ] No changes were made to schemas, function signatures, or batch sizes

## ROLLBACK CONSIDERATIONS

- This change is two string constants and two integer constants. To roll back: restore the four original values in `ai/claude_client.py`. No migrations, no DB changes, no schema changes required.
- The original prompts are preserved in git history.

## ACCEPTANCE CRITERIA

- [ ] `_NOISE_MAX_BODY_CHARS == 300`
- [ ] `_REFINE_MAX_BODY_CHARS == 350`
- [ ] Noise prompt explicitly names session blurbs, purely-promotional ad copy, and tool-tip marketing as NOISE
- [ ] Noise prompt's keep rule for sponsor content requires "specific usable facts" — not just "explains a product"
- [ ] Refine prompt's `same_story` requires "same specific announcement" — not just same company/topic
- [ ] Refine prompt explicitly rejects "same company + same conference + same day" as sufficient for `same_story`
- [ ] Refine prompt includes conference multi-story anti-examples (broad recap vs. focused announcement)
- [ ] All existing tests pass with zero regressions (114 tests)
- [ ] No schema changes, no function signature changes, no new files

---

## COMPLETION CHECKLIST

- [ ] Task 1 completed: `_NOISE_SYSTEM_PROMPT` updated, `_NOISE_MAX_BODY_CHARS` = 300
- [ ] Task 2 completed: `_REFINE_SYSTEM_PROMPT` updated, `_REFINE_MAX_BODY_CHARS` = 350
- [ ] Task 3 completed: full test suite passes
- [ ] All validation commands executed
- [ ] Manual prompt review confirmed
- [ ] Acceptance criteria all met

---

## NOTES

**Why no schema changes?** The `is_noise` boolean and `relationship` enum already model the right decisions. The problem is in how the LLM is being instructed to apply them, not in the output structure.

**Why increase body chars?** The noise filter at 200 chars often cuts off before enough context is visible to distinguish "promotional copy with a tagline" from "sponsor content with specific facts." The dedup filter at 250 chars may cut off before the story's key development is mentioned — a conference story that starts with context before the actual announcement may look identical to another at 250 chars. The increases (200→300, 250→350) are modest and cost-negligible on haiku.

**Why no new tests?** Prompt quality cannot be meaningfully unit-tested with string assertions — if you reword a correct prompt, the assertion breaks even though the behavior is unchanged. The correct validation is human review of live results. Structural tests (schema, batch size, message format) already cover everything that can be meaningfully automated.

**Cost impact:** Each item in a noise filter batch adds ~100 additional input chars (200→300). For 30 items/batch, that's ~3,000 extra chars ≈ 750 extra tokens/batch on haiku. Each story in a refine pair adds ~100 chars (250→350), for 20 pairs that's ~4,000 extra chars ≈ 1,000 extra tokens/batch. Both are negligible cost increases on haiku pricing.

---

## VALIDATION OUTPUT REFERENCE

- Item to check:
  `cd "/Users/natalie/Documents/Agentic AI/Newsletter Digest Agent" && python -c "from ai.claude_client import _NOISE_MAX_BODY_CHARS, _REFINE_MAX_BODY_CHARS; assert _NOISE_MAX_BODY_CHARS == 300, f'expected 300, got {_NOISE_MAX_BODY_CHARS}'; assert _REFINE_MAX_BODY_CHARS == 350, f'expected 350, got {_REFINE_MAX_BODY_CHARS}'; print('constants OK')"`
  Expected output or result:
  constants OK

- Item to check:
  `cd "/Users/natalie/Documents/Agentic AI/Newsletter Digest Agent" && python -m pytest tests/test_claude_client.py -v -k "noise"`
  Expected output or result:
  All noise-related tests pass. Lines matching `test_noise_` show `PASSED`. Final line: `X passed` with no failures.

- Item to check:
  `cd "/Users/natalie/Documents/Agentic AI/Newsletter Digest Agent" && python -m pytest tests/test_claude_client.py -v -k "refine"`
  Expected output or result:
  All refine-related tests pass. Lines matching `test_refine_` show `PASSED`. Final line: `X passed` with no failures.

- Item to check:
  `cd "/Users/natalie/Documents/Agentic AI/Newsletter Digest Agent" && python -m pytest tests/ -v`
  Expected output or result:
  All 114 tests pass. Final line: `114 passed` with no failures, no errors.

- Item to check:
  `_NOISE_MAX_BODY_CHARS` is 300
  Expected output or result:
  Confirmed by constants OK check above.

- Item to check:
  `_REFINE_MAX_BODY_CHARS` is 350
  Expected output or result:
  Confirmed by constants OK check above.

- Item to check:
  Noise prompt includes session blurbs as a NOISE category
  Expected output or result:
  Running the manual validation command shows `_NOISE_SYSTEM_PROMPT` contains text referencing "Session blurbs and agenda items" (or equivalent phrasing covering conference session descriptions).

- Item to check:
  Noise prompt includes the "specific usable facts" test for sponsor content
  Expected output or result:
  Running the manual validation command shows `_NOISE_SYSTEM_PROMPT` contains text referencing "specific, usable facts" (or equivalent) in the KEEP rules for sponsor content.

- Item to check:
  Refine prompt includes "same specific announcement" as the `same_story` test
  Expected output or result:
  Running the manual validation command shows `_REFINE_SYSTEM_PROMPT` contains text referencing "same single announcement" or "same specific announcement" (or equivalent).

- Item to check:
  Refine prompt states same company + same conference + same day ≠ same story
  Expected output or result:
  Running the manual validation command shows `_REFINE_SYSTEM_PROMPT` contains text explicitly stating that same company + same conference + same day is not sufficient for `same_story`.

- Item to check:
  No changes were made to schemas, function signatures, or batch sizes
  Expected output or result:
  `_NOISE_BATCH_SIZE == 30`, `_REFINE_BATCH_SIZE == 20`, `_FILTER_BATCH_SIZE == 25` — confirmed by existing passing tests `test_noise_batch_size`, `test_refine_batch_size`, `test_filter_batch_size`.
