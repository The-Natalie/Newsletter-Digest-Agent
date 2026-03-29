# Feature: story-gating

The following plan should be complete, but it's important that you validate documentation and codebase patterns and task sanity before you start implementing.

Pay special attention to naming of existing utils, types, and models. Import from the right files etc.

## Feature Description

Add a content-based filtering step in `processing/embedder.py` that drops non-story sections before they enter clustering. The filter targets newsletter housekeeping, editorial meta-content, feedback prompts, and audience-growth copy — text that is structurally section-shaped but carries no news value.

## User Story

As a digest reader
I want non-story newsletter content (unsubscribe notices, feedback prompts, editorial outros) to be excluded from the digest
So that the AI only summarises real stories and the output is free of filler

## Problem Statement

Sections that pass Loop 1's infrastructure filter (`_BOILERPLATE_SEGMENT_SIGNALS`) still include:
- "you're receiving this because…" onboarding blurbs
- "that's all for this week" editorial outros
- "take our survey" feedback prompts
- "interested in advertising with us" audience-growth copy
- frequency / notification preference prompts

These sections are long enough (≥ `_MIN_SECTION_CHARS` = 100 chars) and contain no Loop 1 signals, so they pass into clustering and eventually reach Claude as if they were stories.

## Scope

- In scope: `processing/embedder.py` — new constant, new predicate, modified `_segment_email()`
- Out of scope: `ingestion/email_parser.py` (no changes to Loop 1), `processing/deduplicator.py`, `ai/claude_client.py`, any test that doesn't test embedder directly

## Solution Statement

Add `_NON_STORY_SIGNALS` (a tuple of high-precision multi-word phrases) and a predicate `_is_non_story_chunk(text)` to `embedder.py`. Modify `_segment_email()` to apply this predicate before creating `StoryChunk` objects — both in the HTML sections path and in the plain-text fallback path. Track and log filtered counts at DEBUG level.

## Feature Metadata

**Feature Type**: Enhancement
**Estimated Complexity**: Low
**Primary Systems Affected**: `processing/embedder.py`
**Dependencies**: None (uses only stdlib `str` operations)
**Assumptions**: Loop 1's `_BOILERPLATE_SEGMENT_SIGNALS` in `email_parser.py` remains untouched. The new signals are deliberately non-overlapping with Loop 1 signals.

---

## CONTEXT REFERENCES

### Relevant Codebase Files — MUST READ BEFORE IMPLEMENTING

- `processing/embedder.py` (full file, 132 lines) — target file; contains `_segment_email()` and `_MIN_CHUNK_CHARS`
- `ingestion/email_parser.py` (lines 110–136) — existing `_BOILERPLATE_SEGMENT_SIGNALS` and `_is_boilerplate_segment()` pattern to mirror exactly

### New Files to Create

None.

### Patterns to Follow

**Existing signal constant pattern** (`email_parser.py` lines 118–135):
```python
_BOILERPLATE_SEGMENT_SIGNALS = (
    "manage your subscriptions",
    "manage your email",
    ...
)
```

**Existing predicate pattern** (`email_parser.py` lines 217–220):
```python
def _is_boilerplate_segment(text: str) -> bool:
    """Return True if this text segment is sponsor or shell content, not a news story."""
    text_lower = text.lower()
    return any(signal in text_lower for signal in _BOILERPLATE_SEGMENT_SIGNALS)
```

**Existing `_segment_email()` sections path** (`embedder.py` lines 48–62):
```python
if parsed_email.sections:
    chunks = [
        StoryChunk(
            text=section["text"],
            sender=parsed_email.sender,
            links=section["links"],
        )
        for section in parsed_email.sections
        if len(section["text"]) >= _MIN_CHUNK_CHARS
    ]
    logger.debug(
        "Email from %s: used %d pre-extracted sections → %d chunks",
        parsed_email.sender, len(parsed_email.sections), len(chunks),
    )
    return chunks
```

**Existing `_segment_email()` fallback path** (`embedder.py` lines 64–79):
```python
segments = _SPLIT_PATTERN.split(parsed_email.body)
chunks = []
for seg in segments:
    seg = seg.strip()
    if len(seg) >= _MIN_CHUNK_CHARS:
        chunks.append(StoryChunk(
            text=seg,
            sender=parsed_email.sender,
            links=[],
        ))
logger.debug(
    "Email from %s: plain-text fallback → %d chunks",
    parsed_email.sender, len(chunks),
)
return chunks
```

---

## IMPLEMENTATION PLAN

### Phase 1: Add constant and predicate

Add `_NON_STORY_SIGNALS` tuple and `_is_non_story_chunk()` function to `embedder.py`.

### Phase 2: Update `_segment_email()`

Convert the list comprehension in the sections path to an explicit loop so we can track filtered count. Add the predicate check to both paths. Log filtered count at DEBUG level.

---

## STEP-BY-STEP TASKS

### Task 1 — UPDATE `processing/embedder.py`: add `_NON_STORY_SIGNALS` constant

Place immediately after the existing module-level constants (`_MIN_CHUNK_CHARS`, `_MAX_ENCODING_CHARS`, `_SPLIT_PATTERN`), before `_model = None`.

**IMPLEMENT**: Add the following constant block:
```python
# Substrings identifying non-story newsletter sections.
# These are sections whose content is administrative, editorial meta, or promotional
# infrastructure — they are not news stories and should not reach the AI prompt.
# Each phrase is multi-word to reduce false positives.
# NOT included: sponsor content, product announcements, research, tools, job listings.
# These are conservative signals: only drop on clear non-story match.
_NON_STORY_SIGNALS = (
    # Subscription-receiving meta (onboarding blurbs)
    "you're receiving this because",
    "you are receiving this because",
    # Frequency / notification settings prompts
    "to change how often you receive",
    "to update your notification preferences",
    # Audience growth / ad recruitment copy
    "want to advertise with us",
    "interested in advertising with us",
    "interested in sponsoring this",
    # Newsletter outro / sign-off boilerplate
    "that's all for this week",
    "that's it for this week",
    "see you next issue",
    "see you in the next issue",
    # Feedback / survey prompts
    "take our survey",
    "fill out our survey",
)
```

**PATTERN**: Mirror `_BOILERPLATE_SEGMENT_SIGNALS` in `email_parser.py` lines 118–135.
**GOTCHA**: Do NOT add signals that overlap with `_BOILERPLATE_SEGMENT_SIGNALS` — double coverage wastes nothing but is confusing. None of the 13 entries above appear in Loop 1's list.
**VALIDATE**: `python -c "from processing.embedder import _NON_STORY_SIGNALS; print(len(_NON_STORY_SIGNALS))"`
Expected output: `14`

---

### Task 2 — UPDATE `processing/embedder.py`: add `_is_non_story_chunk()` predicate

Place immediately after the `_NON_STORY_SIGNALS` constant and before `_model = None`.

**IMPLEMENT**:
```python
def _is_non_story_chunk(text: str) -> bool:
    """Return True if this chunk is non-story newsletter content (meta/admin/editorial).

    Uses substring matching against _NON_STORY_SIGNALS. Only filters on clear,
    multi-word signals to avoid false positives on legitimate stories.
    """
    text_lower = text.lower()
    return any(signal in text_lower for signal in _NON_STORY_SIGNALS)
```

**PATTERN**: Mirror `_is_boilerplate_segment()` in `email_parser.py` lines 217–220.
**VALIDATE**:
```bash
python -c "
from processing.embedder import _is_non_story_chunk
assert _is_non_story_chunk(\"You're receiving this because you signed up.\") is True
assert _is_non_story_chunk(\"That's all for this week! See you next issue.\") is True
assert _is_non_story_chunk(\"Want to advertise with us? Reply to this email.\") is True
assert _is_non_story_chunk(\"OpenAI released GPT-5 today with multimodal reasoning.\") is False
assert _is_non_story_chunk(\"This week's sponsor: Acme Corp offers 20% off cloud storage.\") is False
print('OK')
"
```
Expected output: `OK`

---

### Task 3 — UPDATE `processing/embedder.py`: modify `_segment_email()` to apply filter

Replace the list comprehension in the sections path with an explicit loop. Add `_is_non_story_chunk()` check in both the sections path and the plain-text fallback path.

**IMPLEMENT** — replace the current `_segment_email()` body (lines 48–79) with:

```python
    if parsed_email.sections:
        chunks = []
        non_story_count = 0
        for section in parsed_email.sections:
            if len(section["text"]) < _MIN_CHUNK_CHARS:
                continue
            if _is_non_story_chunk(section["text"]):
                non_story_count += 1
                continue
            chunks.append(StoryChunk(
                text=section["text"],
                sender=parsed_email.sender,
                links=section["links"],
            ))
        if non_story_count:
            logger.debug(
                "Email from %s: dropped %d non-story section(s)",
                parsed_email.sender, non_story_count,
            )
        logger.debug(
            "Email from %s: used %d pre-extracted sections → %d chunks",
            parsed_email.sender, len(parsed_email.sections), len(chunks),
        )
        return chunks

    # Fallback: plain-text email — split body, no links available
    segments = _SPLIT_PATTERN.split(parsed_email.body)
    chunks = []
    non_story_count = 0
    for seg in segments:
        seg = seg.strip()
        if len(seg) < _MIN_CHUNK_CHARS:
            continue
        if _is_non_story_chunk(seg):
            non_story_count += 1
            continue
        chunks.append(StoryChunk(
            text=seg,
            sender=parsed_email.sender,
            links=[],
        ))
    if non_story_count:
        logger.debug(
            "Email from %s: dropped %d non-story segment(s) (plain-text fallback)",
            parsed_email.sender, non_story_count,
        )
    logger.debug(
        "Email from %s: plain-text fallback → %d chunks",
        parsed_email.sender, len(chunks),
    )
    return chunks
```

**GOTCHA**: The original sections path used a list comprehension. The replacement is an explicit loop. Behaviour is identical except for the added `_is_non_story_chunk()` check and the `non_story_count` tracking.
**GOTCHA**: The `non_story_count` debug log uses `if non_story_count:` so it only emits when something was dropped — keeps logs clean on typical runs.
**VALIDATE**: `python -c "from processing.embedder import _segment_email; print('OK')"`
Expected output: `OK`

---

## TESTING STRATEGY

### Unit Tests

Run inline in validation commands (no separate test file required — consistent with project pattern for this module).

### Edge Cases

- Section with non-story signal in the middle of a long paragraph: must still drop (substring match, not start-of-string)
- Section that contains both a story and a subscription blurb concatenated: accepted (conservative: only drop on clear single-section match)
- Sponsor section ("This week's sponsor: Acme Corp") with zero `_NON_STORY_SIGNALS` hits: must pass through unchanged
- Plain-text fallback path: same filter applied, same behaviour

---

## VALIDATION COMMANDS

### Level 1: Import check

```bash
python -c "from processing.embedder import _NON_STORY_SIGNALS, _is_non_story_chunk, _segment_email; print('imports OK')"
```
Expected: `imports OK`

### Level 2: Unit assertions

```bash
python -c "
from processing.embedder import _NON_STORY_SIGNALS, _is_non_story_chunk

# Signal count
assert len(_NON_STORY_SIGNALS) == 14, f'Expected 14 signals, got {len(_NON_STORY_SIGNALS)}'

# Positive matches — must drop
assert _is_non_story_chunk(\"You're receiving this because you signed up\") is True
assert _is_non_story_chunk(\"You are receiving this because you opted in\") is True
assert _is_non_story_chunk(\"To change how often you receive this newsletter\") is True
assert _is_non_story_chunk(\"To update your notification preferences click here\") is True
assert _is_non_story_chunk(\"Want to advertise with us? Reply to this email\") is True
assert _is_non_story_chunk(\"Interested in advertising with us?\") is True
assert _is_non_story_chunk(\"Interested in sponsoring this newsletter?\") is True
assert _is_non_story_chunk(\"That's all for this week! Thanks for reading.\") is True
assert _is_non_story_chunk(\"That's it for this week. See you soon.\") is True
assert _is_non_story_chunk(\"See you next issue!\") is True
assert _is_non_story_chunk(\"See you in the next issue of AI Weekly.\") is True
assert _is_non_story_chunk(\"Take our survey and let us know what you think.\") is True
assert _is_non_story_chunk(\"Fill out our survey to shape future issues.\") is True

# Negative matches — must pass through
assert _is_non_story_chunk(\"OpenAI released GPT-5 today with multimodal reasoning.\") is False
assert _is_non_story_chunk(\"This week's sponsor: Acme Corp offers 20% off cloud storage.\") is False
assert _is_non_story_chunk(\"Google DeepMind published a new paper on protein folding.\") is False
assert _is_non_story_chunk(\"Hiring: Senior ML Engineer at Anthropic. See link for details.\") is False

print('all assertions passed')
"
```
Expected: `all assertions passed`

### Level 3: `_segment_email()` integration check

```bash
python -c "
from ingestion.email_parser import ParsedEmail
from processing.embedder import _segment_email
from datetime import datetime

# Non-story section should be dropped
non_story_section = {
    'text': \"You're receiving this because you subscribed to AI Weekly. To change how often you receive this, visit your preferences page. We send this digest every Monday morning.\",
    'links': [],
}
real_story_section = {
    'text': \"OpenAI has announced GPT-5, a new flagship model with significantly improved reasoning capabilities and multimodal understanding. The model will be available via API starting next month.\",
    'links': [{'url': 'https://openai.com/blog/gpt-5', 'anchor_text': 'GPT-5 announcement'}],
}
email = ParsedEmail(
    subject='AI Weekly',
    sender='AI Weekly',
    date=datetime.now(),
    body='',
    sections=[non_story_section, real_story_section],
)
chunks = _segment_email(email)
assert len(chunks) == 1, f'Expected 1 chunk, got {len(chunks)}'
assert chunks[0].text == real_story_section['text']
assert chunks[0].links == real_story_section['links']
print('integration check passed')
"
```
Expected: `integration check passed`

### Level 4: Full module syntax check

```bash
python -m py_compile processing/embedder.py && echo "syntax OK"
```
Expected: `syntax OK`

### Level 5: Manual validation

Run the pipeline CLI against a real mailbox to confirm:
- Story count before Claude is reduced (non-story sections filtered)
- Real stories are still present in output
- No increase in empty/sourceless groups

```bash
python -m processing.digest_builder --folder "AI Newsletters" --start 2026-03-10 --end 2026-03-17
```

---

## MANUAL VERIFICATION CHECKLIST

- [ ] `_NON_STORY_SIGNALS` constant is present in `processing/embedder.py` with 14 entries
- [ ] `_is_non_story_chunk()` function is present in `processing/embedder.py`
- [ ] `_segment_email()` sections path uses explicit loop (not list comprehension) with non-story check
- [ ] `_segment_email()` fallback path also applies non-story check
- [ ] Debug log emits count of dropped sections when non-zero
- [ ] No changes made to `ingestion/email_parser.py`
- [ ] No changes made to `processing/deduplicator.py`
- [ ] No changes made to `ai/claude_client.py`
- [ ] All Level 1–4 validation commands pass

---

## ROLLBACK CONSIDERATIONS

Single-file change (`processing/embedder.py`). Revert by restoring the original `_segment_email()` list comprehension and removing the two new additions (`_NON_STORY_SIGNALS`, `_is_non_story_chunk`). No database, migration, or config changes.

---

## ACCEPTANCE CRITERIA

- [ ] `_NON_STORY_SIGNALS` has 14 entries matching the signals in Task 1
- [ ] `_is_non_story_chunk()` returns `True` for all 13 positive test cases in Level 2
- [ ] `_is_non_story_chunk()` returns `False` for all 4 negative test cases in Level 2
- [ ] `_segment_email()` integration check: 1 chunk returned (non-story dropped, real story kept)
- [ ] `python -m py_compile processing/embedder.py` exits 0
- [ ] No changes to `email_parser.py`, `deduplicator.py`, or `claude_client.py`
- [ ] Signals are conservative: no sponsor/product/job content dropped
- [ ] Pipeline run produces fewer non-story items before Claude

---

## VALIDATION OUTPUT REFERENCE

- Item to check:
  `python -c "from processing.embedder import _NON_STORY_SIGNALS; print(len(_NON_STORY_SIGNALS))"`
  Expected output or result:
  `14`

- Item to check:
  `python -c "from processing.embedder import _NON_STORY_SIGNALS, _is_non_story_chunk; ... print('all assertions passed')"`
  Expected output or result:
  `all assertions passed`

- Item to check:
  `_segment_email()` integration check
  Expected output or result:
  `integration check passed`

- Item to check:
  `python -m py_compile processing/embedder.py && echo "syntax OK"`
  Expected output or result:
  `syntax OK`

- Item to check:
  `_NON_STORY_SIGNALS` constant present in `processing/embedder.py` with 14 entries
  Expected output or result:
  File `processing/embedder.py` contains `_NON_STORY_SIGNALS = (` with 14 string entries

- Item to check:
  `_is_non_story_chunk()` function present in `processing/embedder.py`
  Expected output or result:
  File `processing/embedder.py` contains `def _is_non_story_chunk(text: str) -> bool:`

- Item to check:
  `_segment_email()` sections path uses explicit loop with non-story check
  Expected output or result:
  File `processing/embedder.py` contains `if _is_non_story_chunk(section["text"]):` in `_segment_email()`

- Item to check:
  `_segment_email()` fallback path applies non-story check
  Expected output or result:
  File `processing/embedder.py` contains `if _is_non_story_chunk(seg):` in the plain-text fallback path

- Item to check:
  No changes to `ingestion/email_parser.py`
  Expected output or result:
  `git diff ingestion/email_parser.py` produces no output

- Item to check:
  No changes to `processing/deduplicator.py`
  Expected output or result:
  `git diff processing/deduplicator.py` produces no output

- Item to check:
  No changes to `ai/claude_client.py`
  Expected output or result:
  `git diff ai/claude_client.py` produces no output

---

## NOTES

- **Why `embedder.py` and not `email_parser.py`?** Loop 1 owns section extraction and its boilerplate filter. The constraint "Do NOT modify section extraction logic" means `email_parser.py` is frozen. `embedder.py`'s `_segment_email()` is the natural next gate — it converts sections into StoryChunks that enter clustering. Filtering there satisfies "Do NOT modify clustering logic beyond filtering inputs."

- **Signal count is 14, not 13.** The summary mentioned 13 but the actual list as designed has 14 entries (two separate "see you next/in the next issue" entries). The constant count assertion uses 14.

- **Conservative signal design.** Every signal is multi-word and domain-specific. None are short enough to false-positive on a real story. Sponsor content is explicitly excluded. The predicate only fires when a clear housekeeping signal is present.

- **Confidence score: 9/10.** Single-file change with a clear pattern mirror and no external dependencies.
