# Feature: fix-stage5-token-limit — Cap Story Groups Sent to Claude

The following plan should be complete, but validate codebase patterns and task sanity before implementing.

## Feature Description

Stage 5 returns 0 digest entries when the pipeline produces many story groups. With 150 groups, the required output is ~15,000 tokens, but `_MAX_TOKENS = 8192` truncates Claude's response before any entry is written, yielding `{"entries": []}`. The fix: sort story groups by source count (descending) and cap input at `_MAX_STORY_GROUPS = 50` before calling Claude. This keeps one API call (MVP principle), focuses on the most cross-covered stories, and keeps output well within the token limit.

## Diagnosis (confirmed pre-plan)

```
Story groups:          150
Prompt chars:          76,760
Prompt tokens (est):   19,190
Output needed (est):   15,000 tokens  (@100 tok/entry × 150 groups)
_MAX_TOKENS:            8,192  ← hard truncation before first entry written
```

Source distribution for the test run:
```
 1 source(s): 86 groups  ← single-newsletter singletons; lowest-value
 2 source(s): 24 groups
 3 source(s): 12 groups
 4 source(s): 13 groups
 5 source(s):  8 groups
 6 source(s):  4 groups
 9 source(s):  1 groups
10 source(s):  1 groups
34 source(s):  1 groups
```

Capping at top 50 by source count captures all 64 multi-source groups plus 14 of the best single-source ones. Output needed: ~5,000 tokens → well under 8,192.

## User Story

As the pipeline, I want Stage 5 to produce digest entries for the most newsworthy story groups without exceeding output token limits, so that the digest always completes successfully.

## Problem Statement

`generate_digest()` passes all story groups — however many the deduplicator produces — into a single prompt. With a large date range or busy newsletters, this can produce 100+ groups requiring more output tokens than `_MAX_TOKENS` allows, causing Claude to truncate before writing any entries.

## Scope

- In scope: `ai/claude_client.py` — cap logic, `_MAX_STORY_GROUPS` constant, stop_reason + token-usage logging
- Out of scope: `deduplicator.py`, `digest_builder.py`, `embedder.py`, all other files

## Solution Statement

1. Add `_MAX_STORY_GROUPS = 50` constant — the maximum number of groups sent per Claude call.
2. In `generate_digest()`, sort groups by `len(group.sources)` descending (most cross-covered first), take the top `_MAX_STORY_GROUPS`, log how many were trimmed.
3. Add `stop_reason` and token usage logging on the API response for observability.

`_MAX_TOKENS` stays at 8192 — sufficient for 50 entries at ~100 tokens each.

## Feature Metadata

**Feature Type**: Bug Fix
**Estimated Complexity**: Low
**Primary Systems Affected**: `ai/claude_client.py`
**Dependencies**: None
**Assumptions**: Source count is a valid proxy for cross-newsletter coverage and story significance.

---

## CONTEXT REFERENCES

### Relevant Codebase Files — READ BEFORE IMPLEMENTING

- `ai/claude_client.py` (full file) — `generate_digest()`, `_build_user_message()`, `_MAX_TOKENS`, `_TOOL_NAME`

### Patterns to Follow

**Existing logger.info pattern in the file:**
```python
logger.info(
    "Calling Claude (%s) with %d story group(s) for folder '%s'",
    settings.claude_model,
    len(story_groups),
    folder,
)
```

**Existing response handling block (lines 146–159 of current file):**
```python
tool_input: dict | None = None
for block in response.content:
    if block.type == "tool_use":
        tool_input = block.input
        break

if tool_input is None:
    raise ValueError(
        f"Claude response contained no tool_use block. "
        f"stop_reason={response.stop_reason!r}"
    )
```

---

## STEP-BY-STEP TASKS

### TASK 1: UPDATE `ai/claude_client.py` — add `_MAX_STORY_GROUPS` constant

After the existing `_MAX_CHUNK_CHARS = 600` line, add:

```python
_MAX_STORY_GROUPS = 50   # max groups per Claude call; keeps output within _MAX_TOKENS
```

- **VALIDATE**: `python -c "from ai.claude_client import _MAX_STORY_GROUPS; print(_MAX_STORY_GROUPS)"`

### TASK 2: UPDATE `ai/claude_client.py` — cap and sort story groups in `generate_digest()`

At the top of `generate_digest()`, after the `if not story_groups: return []` guard, add the cap logic before `_build_user_message()` is called:

```python
    # Sort by source count descending (most cross-covered stories first), then cap.
    # This prioritises multi-newsletter coverage and keeps output within _MAX_TOKENS.
    if len(story_groups) > _MAX_STORY_GROUPS:
        story_groups = sorted(story_groups, key=lambda g: len(g.sources), reverse=True)
        story_groups = story_groups[:_MAX_STORY_GROUPS]
        logger.info(
            "Capped story groups to top %d by source count (%d total available)",
            _MAX_STORY_GROUPS,
            len(story_groups),
        )
```

Note: `story_groups` is a local variable here — the caller's list is not mutated.

- **VALIDATE**: `python -c "import ai.claude_client; print('ok')"`

### TASK 3: UPDATE `ai/claude_client.py` — log stop_reason and token usage after API call

After the `response = await client.messages.create(...)` call (before the `tool_input` extraction block), add:

```python
    logger.debug(
        "Claude response: stop_reason=%r  input_tokens=%d  output_tokens=%d",
        response.stop_reason,
        response.usage.input_tokens,
        response.usage.output_tokens,
    )
```

- **VALIDATE**: `python -c "import ai.claude_client; print('ok')"`

---

## VALIDATION COMMANDS

### Level 1: Import and constant check

```bash
python -c "from ai.claude_client import _MAX_STORY_GROUPS; print('_MAX_STORY_GROUPS =', _MAX_STORY_GROUPS)"
```

Expected:
```
_MAX_STORY_GROUPS = 50
```

### Level 2: Full import chain

```bash
python -c "
from ingestion.email_parser import parse_emails, ParsedEmail
from processing.embedder import embed_and_cluster
from processing.deduplicator import deduplicate
from ai.claude_client import generate_digest
print('All imports OK')
"
```

Expected:
```
All imports OK
```

### Level 3: Cap logic unit test

```bash
python -c "
from processing.deduplicator import StoryGroup, StoryChunk
from ai.claude_client import _MAX_STORY_GROUPS

# Build 60 fake groups with varying source counts
groups = []
for i in range(60):
    src_count = i % 10 + 1
    sources = [{'url': f'https://example.com/{i}/{j}', 'anchor_text': 'link', 'newsletter': 'X'} for j in range(src_count)]
    groups.append(StoryGroup(chunks=[], sources=sources))

# Simulate the cap logic
if len(groups) > _MAX_STORY_GROUPS:
    capped = sorted(groups, key=lambda g: len(g.sources), reverse=True)[:_MAX_STORY_GROUPS]
else:
    capped = groups

assert len(capped) == _MAX_STORY_GROUPS, f'Expected {_MAX_STORY_GROUPS}, got {len(capped)}'
assert len(capped[0].sources) >= len(capped[-1].sources), 'Not sorted descending'
print('Cap logic test PASSED')
print(f'Top source count: {len(capped[0].sources)}, bottom: {len(capped[-1].sources)}')
"
```

Expected:
```
Cap logic test PASSED
Top source count: 10, bottom: ...
```

### Level 4: Full pipeline run

```bash
python -m processing.digest_builder --folder "AI Newsletters" --start 2026-03-16 --end 2026-03-17 2>&1 | grep -E "(Stage|Capped|Claude returned|story_count|stories)"
```

Expected: Stage 5 produces > 0 digest entries; no "Claude returned 0" line.

### Level 5: Full pipeline run (full output)

```bash
python -m processing.digest_builder --folder "AI Newsletters" --start 2026-03-16 --end 2026-03-17 2>&1
```

Expected: `"story_count"` > 0 in the final JSON output; at least one `"headline"` entry printed.

---

## MANUAL VERIFICATION CHECKLIST

- [ ] `_MAX_STORY_GROUPS` is defined and equals 50
- [ ] The pipeline run produces > 0 digest entries
- [ ] The log contains "Capped story groups to top 50" (confirming cap triggered for 150 groups)
- [ ] Each digest entry has a non-empty `headline`, `summary`, `significance`
- [ ] Each digest entry has a non-empty `sources` array
- [ ] The final JSON `story_count` is > 0

---

## VALIDATION OUTPUT REFERENCE — EXACT OUTPUTS TO CHECK

- Item to check:
  `python -c "from ai.claude_client import _MAX_STORY_GROUPS; print('_MAX_STORY_GROUPS =', _MAX_STORY_GROUPS)"`
  Expected output or result:
  ```
  _MAX_STORY_GROUPS = 50
  ```

- Item to check:
  ```
  python -c "
  from ingestion.email_parser import parse_emails, ParsedEmail
  from processing.embedder import embed_and_cluster
  from processing.deduplicator import deduplicate
  from ai.claude_client import generate_digest
  print('All imports OK')
  "
  ```
  Expected output or result:
  ```
  All imports OK
  ```

- Item to check:
  ```
  python -c "
  from processing.deduplicator import StoryGroup, StoryChunk
  from ai.claude_client import _MAX_STORY_GROUPS

  groups = []
  for i in range(60):
      src_count = i % 10 + 1
      sources = [{'url': f'https://example.com/{i}/{j}', 'anchor_text': 'link', 'newsletter': 'X'} for j in range(src_count)]
      groups.append(StoryGroup(chunks=[], sources=sources))

  if len(groups) > _MAX_STORY_GROUPS:
      capped = sorted(groups, key=lambda g: len(g.sources), reverse=True)[:_MAX_STORY_GROUPS]
  else:
      capped = groups

  assert len(capped) == _MAX_STORY_GROUPS, f'Expected {_MAX_STORY_GROUPS}, got {len(capped)}'
  assert len(capped[0].sources) >= len(capped[-1].sources), 'Not sorted descending'
  print('Cap logic test PASSED')
  print(f'Top source count: {len(capped[0].sources)}, bottom: {len(capped[-1].sources)}')
  "
  ```
  Expected output or result:
  ```
  Cap logic test PASSED
  Top source count: 10, bottom: <some number ≤ 10>
  ```

- Item to check:
  File `ai/claude_client.py` was modified to add `_MAX_STORY_GROUPS = 50`, cap-and-sort logic in `generate_digest()`, and stop_reason + token-usage logging.
  Expected output or result:
  Import passes (confirmed by Level 1 and Level 2 checks above) and `_MAX_STORY_GROUPS = 50` is printed.

- Item to check:
  The pipeline log contains "Capped story groups to top 50" (manual run: `python -m processing.digest_builder --folder "AI Newsletters" --start 2026-03-16 --end 2026-03-17`)
  Expected output or result:
  A log line matching: `Capped story groups to top 50 by source count (50 total available)` appears in the run output.

- Item to check:
  The pipeline produces > 0 digest entries (manual run: `python -m processing.digest_builder --folder "AI Newsletters" --start 2026-03-16 --end 2026-03-17`)
  Expected output or result:
  The final JSON output contains `"story_count": <N>` where N > 0, and at least one story entry with non-empty `"headline"`, `"summary"`, `"significance"`, and `"sources"`.

- Item to check:
  Each digest entry has a non-empty `sources` array (manual run: `python -m processing.digest_builder --folder "AI Newsletters" --start 2026-03-16 --end 2026-03-17`)
  Expected output or result:
  Every story in the printed JSON has `"sources": [...]` with at least one item containing a non-empty `"url"`.

---

## NOTES

- `story_groups` in `generate_digest()` is a parameter (local copy of the reference). Reassigning it (`story_groups = story_groups[:_MAX_STORY_GROUPS]`) does not mutate the caller's list.
- `_MAX_STORY_GROUPS = 50` gives ~5,000 output tokens at 100 tok/entry, leaving comfortable headroom under `_MAX_TOKENS = 8192`. If the model is changed to one with higher output limits, this cap can be revisited.
- Sorting by `len(group.sources)` (unique source URLs) is a lightweight proxy for cross-newsletter coverage. Groups covered by more newsletters tend to be higher-signal stories.
- The stop_reason and token-usage log is `DEBUG` level so it does not appear in normal runs but is available with `--log-level DEBUG` for future diagnosis.
