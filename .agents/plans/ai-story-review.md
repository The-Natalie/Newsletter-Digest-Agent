# Feature: AI Pre-Flight Story Review

The following plan should be complete, but it's important that you validate documentation and codebase patterns and task sanity before you start implementing.

Pay special attention to:
- The tool-use schema pattern in `claude_client.py` — mirror it exactly
- The stage logging format in `digest_builder.py` — `"Stage N/M — description"`
- Fail-open behavior: if the reviewer fails, the pipeline continues with all groups unfiltered (never break the pipeline)
- Cap placement: after review, before generation (in `digest_builder.py`, not in `claude_client.py`)

## Feature Description

Insert a new AI-powered KEEP/DROP classifier between the deduplication step and the digest generation step. This "pre-flight review" passes all story groups to Claude (haiku) and asks it to classify each as either a real story worth including in the digest or non-story content that should be dropped. Only groups classified as KEEP reach the generation step.

This completes the hybrid architecture: deterministic rules (HTML extraction, signal matching, semantic clustering) do the heavy lifting, and the AI review step handles the ambiguous edge cases that rules cannot catch reliably — promotional sponsor shells, newsletter housekeeping that slipped through, generic CTA-only sections, etc.

## User Story

As a newsletter digest reader,
I want only real news stories to appear in my digest,
So that I don't see newsletter housekeeping, advertise-with-us copy, or empty sponsor shells mixed in with actual articles.

## Problem Statement

After the deterministic pipeline (Loops 1–5), a small number of non-story groups still reach Claude for generation. These include:
- Sponsor content formatted like an article but containing only a call-to-action (no actual content)
- Newsletter housekeeping sections that don't match the existing signal lists
- Editorial blurbs, outro content, or referral program text that is long enough to pass the `_MIN_SECTION_CHARS` filter

Deterministic rules cannot reliably catch all of these without also causing false positives on legitimate stories. An AI classifier is well-suited for this task.

## Scope

- **In scope:**
  - Create `ai/story_reviewer.py` — the KEEP/DROP classifier module
  - Update `processing/digest_builder.py` — insert Stage 5 (review), apply cap after review, renumber to 6 stages
  - Update `ai/claude_client.py` — remove the cap/sort logic (it moves to `digest_builder.py`)
- **Out of scope:**
  - Changing clustering, extraction, or deduplication logic
  - Adding new config settings (uses `settings.claude_model` and `settings.anthropic_api_key`)
  - Changing the generation prompt or tool schema in `claude_client.py`
  - Batched generation (Phase 2)

## Solution Statement

`ai/story_reviewer.py` exposes a single async function `review_story_groups(story_groups, folder)` that:
1. Sends all story groups to Claude in one batched call using tool use
2. Gets back a parallel list of `"KEEP"` / `"DROP"` decisions
3. Returns only the KEEP groups

`digest_builder.py` calls this between Stage 4 (dedup) and Stage 6 (generate), and applies the 50-group MVP cap immediately after review. If the reviewer call fails for any reason, the pipeline logs a warning and continues with all groups (fail-open).

`claude_client.py` loses its internal cap/sort logic — the public `generate_digest()` function becomes simpler: it just takes what it receives.

## Feature Metadata

**Feature Type**: New Capability + Enhancement
**Estimated Complexity**: Medium
**Primary Systems Affected**: `ai/story_reviewer.py` (new), `processing/digest_builder.py` (modified), `ai/claude_client.py` (modified)
**Dependencies**: `anthropic` SDK (already installed), `processing.deduplicator.StoryGroup` (existing type)
**Assumptions**:
- `settings.claude_model` and `settings.anthropic_api_key` are the correct config keys (verified in `config.py`)
- The reviewer uses the same model as generation (`claude_model`, haiku by default)
- If Claude returns the wrong number of decisions, default to KEEP for all groups (conservative — never accidentally drop things)
- If the reviewer API call fails, log a warning and return all groups unfiltered

---

## CONTEXT REFERENCES

### Relevant Codebase Files — YOU MUST READ THESE FILES BEFORE IMPLEMENTING!

- `ai/claude_client.py` (full file) — **Mirror this pattern exactly** for the new reviewer module: lazy `_get_client()`, tool schema dict, system prompt function, user message builder, async public function, `anthropic.APIError` handling, logging conventions
- `processing/digest_builder.py` (full file) — **Understand the 5-stage pipeline** before modifying; note the `try/except` structure, stage logging format (`"Stage N/M — description"`), and DB update pattern
- `processing/deduplicator.py` (lines 12–16) — `StoryGroup` dataclass: `chunks: list[StoryChunk]`, `sources: list[dict]` — this is the input/output type for the reviewer
- `config.py` (lines 13–19) — `settings.anthropic_api_key`, `settings.claude_model` — the correct attribute names to use in reviewer

### New Files to Create

- `ai/story_reviewer.py` — the KEEP/DROP pre-flight classifier

### Files to Modify

- `processing/digest_builder.py` — add Stage 5 (review), cap after review, renumber to 6 total stages
- `ai/claude_client.py` — remove `_MAX_STORY_GROUPS = 50` constant and the sort/cap block from `generate_digest()`

### Relevant Documentation

No new library documentation needed — the `anthropic` SDK patterns are already in `claude_client.py`. Mirror that file exactly.

### Patterns to Follow

**Lazy client initialization** (`claude_client.py:60-69`):
```python
_client: AsyncAnthropic | None = None

def _get_client() -> AsyncAnthropic:
    """Lazy-initialize and cache the AsyncAnthropic client."""
    global _client
    if _client is None:
        logger.info("Initializing AsyncAnthropic client (model=%s)", settings.claude_model)
        _client = AsyncAnthropic(api_key=settings.anthropic_api_key)
    return _client
```
story_reviewer.py has its own `_client` module-level variable and its own `_get_client()` — do not import or share the client from `claude_client.py`.

**Tool schema dict** (`claude_client.py:18-58`):
```python
_TOOL_NAME = "create_digest_entries"
_TOOL_SCHEMA: dict = {
    "name": _TOOL_NAME,
    "description": "...",
    "input_schema": {
        "type": "object",
        "properties": { ... },
        "required": [...]
    }
}
```

**Tool use call** (`claude_client.py:146-157`):
```python
response = await client.messages.create(
    model=settings.claude_model,
    max_tokens=_MAX_TOKENS,
    system=_system_prompt(folder),
    messages=[{"role": "user", "content": user_message}],
    tools=[_TOOL_SCHEMA],
    tool_choice={"type": "tool", "name": _TOOL_NAME},
)
```

**Tool input extraction** (`claude_client.py:167-177`):
```python
tool_input: dict | None = None
for block in response.content:
    if block.type == "tool_use":
        tool_input = block.input
        break
if tool_input is None:
    raise ValueError(...)
```

**Stage logging format** (`digest_builder.py:69-91`):
```python
logger.info("Stage 1/5 — Fetching emails from '%s'", folder)
...
logger.info("Stage 1/5 — Fetched %d raw email(s)", len(raw_emails))
```
After this change, use `N/6` since there will be 6 stages.

**Error handling in pipeline** (`digest_builder.py:124-137`):
The outer `try/except` in `build_digest()` already handles all exceptions — do NOT add an inner try/except for the review step. Instead, use fail-open: catch the reviewer exception, log a warning, and set `reviewed_groups = story_groups` to continue with all groups.

---

## IMPLEMENTATION PLAN

### Phase 1: Create `ai/story_reviewer.py`

Implement the full reviewer module following `claude_client.py` patterns exactly.

### Phase 2: Update `ai/claude_client.py`

Remove the internal cap logic — `_MAX_STORY_GROUPS = 50` constant and the sort/cap block inside `generate_digest()`. The function should accept whatever groups it receives.

### Phase 3: Update `processing/digest_builder.py`

Insert Stage 5 (review) between Stage 4 (dedup) and Stage 6 (generate). Apply the 50-group cap after review. Import `review_story_groups` from `ai.story_reviewer`. Add a `_MAX_STORY_GROUPS = 50` module-level constant. Renumber all stage log lines to `N/6`.

---

## STEP-BY-STEP TASKS

IMPORTANT: Execute every task in order, top to bottom. Each task is atomic and independently testable.

---

### TASK 1: CREATE `ai/story_reviewer.py`

**IMPLEMENT** the complete module. Here is the full specification:

**Module-level constants:**
```python
_TOOL_NAME = "classify_story_groups"
_MAX_TOKENS = 1024          # decisions are short strings; 1024 is more than enough
_MAX_CHUNK_CHARS = 300      # show less text than generation — enough to classify
_MAX_REVIEW_GROUPS = 100    # MVP safety cap on reviewer input; Phase 2 removes with batching
```

**Tool schema** — returns a parallel list of "KEEP"/"DROP" strings, one per group, in order:
```python
_TOOL_SCHEMA: dict = {
    "name": _TOOL_NAME,
    "description": (
        "Classify each story group as KEEP or DROP. "
        "Return one decision per group, in the same order as the input."
    ),
    "input_schema": {
        "type": "object",
        "properties": {
            "decisions": {
                "type": "array",
                "description": "One decision per story group, in input order.",
                "items": {
                    "type": "string",
                    "enum": ["KEEP", "DROP"],
                },
            }
        },
        "required": ["decisions"],
    },
}
```

**System prompt** (function `_system_prompt(folder: str) -> str`):
```
You are a content filter for a newsletter digest focused on {folder}.

Your job is to classify each story group as KEEP or DROP.

KEEP if the group contains:
- A real news story, article, or announcement
- A product launch, tool release, research paper, or report
- A job listing or career opportunity
- Sponsor or partner content that includes a concrete offer, discount, free tool, webinar, report, or substantive explanation — any sponsor section with real informational content for the reader

DROP if the group contains only:
- Newsletter housekeeping (subscription management, preferences, unsubscribe prompts)
- Audience growth content: "advertise with us," sponsorship sales copy, referral programs, or generic brand-awareness blurbs with no real content
- Legal / footer boilerplate (terms of service, privacy policy, all rights reserved)
- Reader feedback requests (surveys, polls, "share your thoughts")
- Editorial shell content with no actual information (intros, outros, "that's all for this week")
- Pure call-to-action blocks with no substantive content beyond the CTA itself

When in doubt, KEEP. Only DROP on clear non-story signals.
```

**User message builder** (function `_build_review_message(story_groups: list[StoryGroup], folder: str) -> str`):
- Header: `f"Below are {len(story_groups)} story group(s) from newsletters about {folder}."`
- For each group (1-indexed): show `"## Group {i}"`, then for each chunk show `<source newsletter="{chunk.sender}">{chunk.text[:_MAX_CHUNK_CHARS]}</source>`
- Footer: `f"Use the {_TOOL_NAME!r} tool to return {len(story_groups)} decisions (KEEP or DROP) in the same order."`

**Main function signature:**
```python
async def review_story_groups(story_groups: list[StoryGroup], folder: str) -> list[StoryGroup]:
```

**Behavior:**
- If `story_groups` is empty, return `[]` immediately (no API call)
- Apply reviewer input cap: if `len(story_groups) > _MAX_REVIEW_GROUPS`, log a warning and slice to `story_groups[:_MAX_REVIEW_GROUPS]` before sending; work with this capped list for the remainder of the function
- Log: `logger.info("Reviewing %d story group(s) for folder '%s'", len(capped_groups), folder)`
- Call Claude with `tool_choice={"type": "tool", "name": _TOOL_NAME}`
- **Fail-open on malformed tool output** (handle inside the reviewer):
  - If `tool_input is None` (no tool_use block in response): log a warning, return the capped groups unfiltered
  - If `len(decisions) != len(capped_groups)`: log a warning, return the capped groups unfiltered
- Zip decisions with capped groups; keep only groups where decision == "KEEP"
- Log: `logger.info("Review: kept %d / %d group(s) (dropped %d)", kept, total, dropped)`
- Return kept groups
- **Do NOT catch `anthropic.APIError` in the reviewer** — let it propagate to `digest_builder.py`, which catches it in the Stage 5 try/except and continues with all groups

**Imports required:**
```python
from __future__ import annotations
import logging
import anthropic
from anthropic import AsyncAnthropic
from config import settings
from processing.deduplicator import StoryGroup
```

**PATTERN**: Mirror `claude_client.py` module structure exactly — lazy `_client`, `_get_client()`, constants, schema, system prompt, message builder, public async function.
**GOTCHA**: Do NOT import or reuse the `_client` from `claude_client.py`. Each module has its own module-level client variable.
**GOTCHA**: `_MAX_TOKENS = 1024` (not 8192 — decisions are short; this also keeps cost low).
**GOTCHA — fail-open split responsibility:**
- `story_reviewer.py` handles malformed tool output itself: if `tool_input is None` or `len(decisions) != len(capped_groups)`, it returns all (capped) groups unfiltered. No exception is raised.
- `anthropic.APIError` (and any other unexpected exception) is NOT caught inside `story_reviewer.py` — it propagates out to `digest_builder.py`, where the Stage 5 try/except catches it, logs a warning, and sets `reviewed_groups = story_groups` to continue unfiltered. The outer `build_digest()` try/except is NOT used for this — the Stage 5 inner try/except handles it specifically.
**VALIDATE**: `python -c "from ai.story_reviewer import review_story_groups; print('import OK')"`

---

### TASK 2: UPDATE `ai/claude_client.py` — remove internal cap

**REMOVE** the following lines from `claude_client.py`:

1. The module-level constant (line 16):
   ```python
   _MAX_STORY_GROUPS = 50   # max groups per Claude call; keeps output within _MAX_TOKENS
   ```

2. The entire cap/sort block inside `generate_digest()` (lines 124–134 approximately):
   ```python
   # Sort by source count descending (most cross-covered stories first), then cap.
   # This prioritises multi-newsletter coverage and keeps output within _MAX_TOKENS.
   if len(story_groups) > _MAX_STORY_GROUPS:
       total_available = len(story_groups)
       story_groups = sorted(story_groups, key=lambda g: len(g.sources), reverse=True)
       story_groups = story_groups[:_MAX_STORY_GROUPS]
       logger.info(
           "Capped story groups to top %d by source count (%d total available)",
           _MAX_STORY_GROUPS,
           total_available,
       )
   ```

After removal, `generate_digest()` goes straight from the `if not story_groups: return []` guard to `client = _get_client()`. No other changes to `claude_client.py`.

**GOTCHA**: Do NOT change anything else in `claude_client.py`. The tool schema, prompt, batching, and response parsing are all unchanged.
**VALIDATE**: `python -c "from ai.claude_client import generate_digest; import inspect; src = inspect.getsource(generate_digest); assert '_MAX_STORY_GROUPS' not in src; print('PASSED: cap removed from generate_digest')"`

---

### TASK 3: UPDATE `processing/digest_builder.py` — insert Stage 5, apply cap, renumber

**Three changes in one file:**

**3a. Add import** at the top of the import block:
```python
from ai.story_reviewer import review_story_groups
```
Place it after the existing `from ai.claude_client import generate_digest` line.

**3b. Add module-level constant** after the `logger = ...` line:
```python
_MAX_STORY_GROUPS = 50  # MVP cap: applied after AI review, before generation (Phase 2: replace with batching)
```

**3c. Update the pipeline** inside `build_digest()`:
- Renumber all existing stage log lines from `N/5` to `N/6` (Stages 1–4)
- Insert Stage 5 (review) after Stage 4 (dedup) and before the old Stage 5 (now Stage 6)
- Apply cap between Stage 5 and Stage 6

Full Stage 4 → 5 → 6 block (replace the existing Stage 4 + Stage 5 block):

```python
        # ── Stage 4: Deduplicate ──────────────────────────────────────────
        logger.info("Stage 4/6 — Deduplicating clusters into story groups")
        story_groups = deduplicate(clusters)
        logger.info("Stage 4/6 — Produced %d story group(s)", len(story_groups))

        # ── Stage 5: AI review ────────────────────────────────────────────
        logger.info("Stage 5/6 — Running AI review to filter non-story groups")
        try:
            reviewed_groups = await review_story_groups(story_groups, folder)
        except Exception as exc:
            logger.warning(
                "AI review failed (%s) — continuing with all %d group(s) unfiltered",
                exc,
                len(story_groups),
            )
            reviewed_groups = story_groups
        logger.info(
            "Stage 5/6 — Review complete: %d group(s) kept (dropped %d)",
            len(reviewed_groups),
            len(story_groups) - len(reviewed_groups),
        )

        # Apply MVP cap after review (temporary constraint; Phase 2 replaces with batching)
        if len(reviewed_groups) > _MAX_STORY_GROUPS:
            logger.info(
                "Capping story groups: %d → %d (MVP limit; Phase 2 will batch instead)",
                len(reviewed_groups),
                _MAX_STORY_GROUPS,
            )
            reviewed_groups = reviewed_groups[:_MAX_STORY_GROUPS]

        # ── Stage 6: AI generation ────────────────────────────────────────
        logger.info("Stage 6/6 — Generating digest entries via Claude")
        stories = await generate_digest(reviewed_groups, folder)
        logger.info("Stage 6/6 — Generated %d digest entry/entries", len(stories))
```

Also renumber Stages 1–3 log lines from `N/5` to `N/6` (6 occurrences total — 2 per stage × 3 stages).

**GOTCHA**: The review step has its OWN try/except (fail-open) — this is intentional. If the reviewer fails, the pipeline continues. The outer try/except in `build_digest()` still catches everything else (DB failure, generation errors, etc.).
**GOTCHA**: `reviewed_groups[:_MAX_STORY_GROUPS]` is a plain slice (no sort). The sort-by-source-count was removed from `claude_client.py` and is NOT reintroduced here. The cap is applied to groups in their existing order after review.
**GOTCHA**: Pass `reviewed_groups` (not `story_groups`) to `generate_digest()`.
**VALIDATE**: `python -c "from processing.digest_builder import build_digest; print('import OK')"`

---

## TESTING STRATEGY

### Unit Tests

No test suite exists yet. Validation is via import checks and `python -c` one-liners.

### Integration Tests

Manual pipeline run after implementation (see Level 4).

### Edge Cases

**In `story_reviewer.py`:**
- Empty `story_groups` list → return `[]` immediately (no API call)
- `len(story_groups) > _MAX_REVIEW_GROUPS` → log warning, slice to first 100 before sending
- `tool_input is None` (no tool_use block in response) → log warning, return capped groups unfiltered
- Claude returns wrong number of decisions → log warning, return capped groups unfiltered
- All groups classified as DROP → return `[]` (valid — empty digest is correct behavior)
- All groups classified as KEEP → return all groups unchanged

**In `digest_builder.py`:**
- Reviewer raises `anthropic.APIError` or any other exception → Stage 5 try/except catches it, logs warning, `reviewed_groups = story_groups`, pipeline continues
- `reviewed_groups` is empty after review → `generate_digest([])` returns `[]` (already handles empty input)
- `len(reviewed_groups) <= _MAX_STORY_GROUPS` → no cap applied, log line not emitted

---

## VALIDATION COMMANDS

### Level 1: Import checks

```bash
cd "/Users/natalie/Documents/Agentic AI/Newsletter Digest Agent" && python -c "from ai.story_reviewer import review_story_groups; print('PASSED: story_reviewer import OK')"
```

```bash
cd "/Users/natalie/Documents/Agentic AI/Newsletter Digest Agent" && python -c "from ai.claude_client import generate_digest; print('PASSED: claude_client import OK')"
```

```bash
cd "/Users/natalie/Documents/Agentic AI/Newsletter Digest Agent" && python -c "from processing.digest_builder import build_digest; print('PASSED: digest_builder import OK')"
```

### Level 2: Cap removed from `claude_client.py`

```bash
cd "/Users/natalie/Documents/Agentic AI/Newsletter Digest Agent" && python -c "
from ai.claude_client import generate_digest
import inspect
src = inspect.getsource(generate_digest)
assert '_MAX_STORY_GROUPS' not in src, 'FAILED: cap still in generate_digest'
assert 'story_groups = sorted' not in src, 'FAILED: sort still in generate_digest'
print('PASSED: cap removed from generate_digest')
"
```

### Level 3: Cap present in `digest_builder.py`

```bash
cd "/Users/natalie/Documents/Agentic AI/Newsletter Digest Agent" && python -c "
import processing.digest_builder as db
assert hasattr(db, '_MAX_STORY_GROUPS'), 'FAILED: _MAX_STORY_GROUPS not in digest_builder'
assert db._MAX_STORY_GROUPS == 50, f'FAILED: expected 50, got {db._MAX_STORY_GROUPS}'
print('PASSED: _MAX_STORY_GROUPS =', db._MAX_STORY_GROUPS, 'in digest_builder')
"
```

### Level 4: Stage count in `digest_builder.py`

```bash
cd "/Users/natalie/Documents/Agentic AI/Newsletter Digest Agent" && grep -c "Stage.*6" processing/digest_builder.py
```
Expected: `10` (5 stages × 2 log lines each = 10 occurrences of `/6`... actually: stages 1–6, each has 2 log lines = 12, minus stage 5 which has slightly different structure. Let's just check for the existence of Stage 5/6 and Stage 6/6):

```bash
cd "/Users/natalie/Documents/Agentic AI/Newsletter Digest Agent" && grep "Stage 5/6\|Stage 6/6" processing/digest_builder.py
```
Expected output (at minimum):
```
        logger.info("Stage 5/6 — Running AI review to filter non-story groups")
        logger.info("Stage 5/6 — Review complete: %d group(s) kept (dropped %d)",
        logger.info("Stage 6/6 — Generating digest entries via Claude")
        logger.info("Stage 6/6 — Generated %d digest entry/entries", len(stories))
```

### Level 5: `review_story_groups` handles empty input without API call

```bash
cd "/Users/natalie/Documents/Agentic AI/Newsletter Digest Agent" && python -c "
import asyncio
from ai.story_reviewer import review_story_groups
result = asyncio.run(review_story_groups([], 'test'))
assert result == [], f'Expected [], got {result}'
print('PASSED: empty input returns [] without API call')
"
```

### Level 6: Manual pipeline run

```bash
cd "/Users/natalie/Documents/Agentic AI/Newsletter Digest Agent" && python -m processing.digest_builder --folder "AI" --start 2026-03-28 --end 2026-03-29
```
Expected log output must include:
```
Stage 5/6 — Running AI review to filter non-story groups
Stage 5/6 — Review complete: N group(s) kept (dropped M)
Stage 6/6 — Generating digest entries via Claude
```

---

## MANUAL VERIFICATION CHECKLIST

- [ ] `ai/story_reviewer.py` exists and imports cleanly
- [ ] `review_story_groups([], "test")` returns `[]` without making an API call
- [ ] `generate_digest()` in `claude_client.py` no longer contains `_MAX_STORY_GROUPS` or `sorted(story_groups, ...)`
- [ ] `_MAX_STORY_GROUPS = 50` exists in `digest_builder.py` at module level
- [ ] `digest_builder.py` stage log lines all use `N/6` format
- [ ] Pipeline run log shows `Stage 5/6` and `Stage 6/6` entries
- [ ] Pipeline run completes successfully and returns valid digest JSON
- [ ] If reviewer drops groups, `"dropped M"` count appears in Stage 5/6 log

## ROLLBACK CONSIDERATIONS

To revert:
1. Delete `ai/story_reviewer.py`
2. In `claude_client.py`, restore `_MAX_STORY_GROUPS = 50` constant and the sort/cap block inside `generate_digest()`
3. In `digest_builder.py`, remove the Stage 5 block, remove `_MAX_STORY_GROUPS`, remove `review_story_groups` import, renumber stages back to `N/5`, restore `generate_digest(story_groups, folder)` call

No DB migrations, no config changes, no data loss.

## ACCEPTANCE CRITERIA

- [ ] `ai/story_reviewer.py` exists with `review_story_groups()` as public API
- [ ] Reviewer uses Claude tool use with `"KEEP"` / `"DROP"` schema
- [ ] Reviewer is fail-open: exception returns all groups unfiltered
- [ ] Cap (50 groups) is applied in `digest_builder.py` after review, not in `claude_client.py`
- [ ] `generate_digest()` in `claude_client.py` has no internal cap logic
- [ ] Pipeline has 6 stages with correct stage numbering in log output
- [ ] All Level 1–5 validation commands pass
- [ ] Manual pipeline run produces a valid digest with Stage 5/6 and Stage 6/6 in logs

---

## COMPLETION CHECKLIST

- [ ] All tasks completed in order
- [ ] Each task validation passed immediately
- [ ] All validation commands executed successfully
- [ ] Manual pipeline run succeeds
- [ ] Acceptance criteria all met

---

## NOTES

**Why fail-open for the reviewer?**
If the reviewer Claude call fails (network error, rate limit, etc.), the digest should still be generated from whatever story groups the deterministic pipeline produced. Failing the entire pipeline because of a review error would be worse than including a few non-story entries. The outer `try/except` in `build_digest()` is reserved for truly fatal errors (IMAP, DB, generation failure).

**Why not sort by source count in the cap?**
The sort-by-source-count was a heuristic to prioritize multi-newsletter stories when capping at 50. With the AI review step in place, the cap is less likely to be hit (review drops non-stories first). And sorting introduces non-determinism that makes the output harder to reason about. The cap is applied in arrival order; if batching is added in Phase 2, ordering will be reconsidered then.

**Why `_MAX_TOKENS = 1024` for the reviewer?**
Each decision is a 4-character string ("KEEP" or "DROP"). For 100 groups, the output is at most ~600 tokens. 1024 is generous and keeps cost minimal.

**Why `_MAX_REVIEW_GROUPS = 100`?**
The reviewer call uses `_MAX_CHUNK_CHARS = 300` per chunk, which keeps input tokens far lower than generation. But without a bound, a large run (e.g., 120 story groups) could still produce an unexpectedly large prompt before batching exists in Phase 2. 100 is high enough to cover any realistic single-day newsletter run without being unlimited. Phase 2 removes this cap and replaces it with batched reviewer calls alongside batched generation.

**Sponsor content policy:**
The system prompt says KEEP sponsor/partner content that provides genuine value (discounts, offers, free tools, webinars, reports). Only DROP empty promotional shells (no substantive content beyond a CTA). Job listings are explicitly KEEP.

---

## VALIDATION OUTPUT REFERENCE

- Item to check:
  `cd "/Users/natalie/Documents/Agentic AI/Newsletter Digest Agent" && python -c "from ai.story_reviewer import review_story_groups; print('PASSED: story_reviewer import OK')"`
  Expected output or result:
  `PASSED: story_reviewer import OK`

- Item to check:
  `cd "/Users/natalie/Documents/Agentic AI/Newsletter Digest Agent" && python -c "from ai.claude_client import generate_digest; print('PASSED: claude_client import OK')"`
  Expected output or result:
  `PASSED: claude_client import OK`

- Item to check:
  `cd "/Users/natalie/Documents/Agentic AI/Newsletter Digest Agent" && python -c "from processing.digest_builder import build_digest; print('PASSED: digest_builder import OK')"`
  Expected output or result:
  `PASSED: digest_builder import OK`

- Item to check:
  ```
  cd "/Users/natalie/Documents/Agentic AI/Newsletter Digest Agent" && python -c "
  from ai.claude_client import generate_digest
  import inspect
  src = inspect.getsource(generate_digest)
  assert '_MAX_STORY_GROUPS' not in src, 'FAILED: cap still in generate_digest'
  assert 'story_groups = sorted' not in src, 'FAILED: sort still in generate_digest'
  print('PASSED: cap removed from generate_digest')
  "
  ```
  Expected output or result:
  `PASSED: cap removed from generate_digest`

- Item to check:
  ```
  cd "/Users/natalie/Documents/Agentic AI/Newsletter Digest Agent" && python -c "
  import processing.digest_builder as db
  assert hasattr(db, '_MAX_STORY_GROUPS'), 'FAILED: _MAX_STORY_GROUPS not in digest_builder'
  assert db._MAX_STORY_GROUPS == 50, f'FAILED: expected 50, got {db._MAX_STORY_GROUPS}'
  print('PASSED: _MAX_STORY_GROUPS =', db._MAX_STORY_GROUPS, 'in digest_builder')
  "
  ```
  Expected output or result:
  `PASSED: _MAX_STORY_GROUPS = 50 in digest_builder`

- Item to check:
  `cd "/Users/natalie/Documents/Agentic AI/Newsletter Digest Agent" && grep "Stage 5/6\|Stage 6/6" processing/digest_builder.py`
  Expected output or result:
  ```
          logger.info("Stage 5/6 — Running AI review to filter non-story groups")
          logger.info("Stage 5/6 — Review complete: %d group(s) kept (dropped %d)",
          logger.info("Stage 6/6 — Generating digest entries via Claude")
          logger.info("Stage 6/6 — Generated %d digest entry/entries", len(stories))
  ```

- Item to check:
  ```
  cd "/Users/natalie/Documents/Agentic AI/Newsletter Digest Agent" && python -c "
  import asyncio
  from ai.story_reviewer import review_story_groups
  result = asyncio.run(review_story_groups([], 'test'))
  assert result == [], f'Expected [], got {result}'
  print('PASSED: empty input returns [] without API call')
  "
  ```
  Expected output or result:
  `PASSED: empty input returns [] without API call`

- Item to check:
  `ai/story_reviewer.py` file exists
  Expected output or result:
  File present at `/Users/natalie/Documents/Agentic AI/Newsletter Digest Agent/ai/story_reviewer.py`

- Item to check:
  Manual pipeline run log includes Stage 5/6 and Stage 6/6 entries
  Expected output or result:
  Log output contains lines matching:
  ```
  Stage 5/6 — Running AI review to filter non-story groups
  Stage 5/6 — Review complete: N group(s) kept (dropped M)
  Stage 6/6 — Generating digest entries via Claude
  Stage 6/6 — Generated N digest entry/entries
  ```
