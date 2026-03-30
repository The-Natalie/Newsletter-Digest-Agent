# Feature: fix-truncation-and-source-attribution-upstream

The following plan should be complete, but it is important that you validate documentation
and codebase patterns and task sanity before you start implementing.

Pay special attention to naming of existing utils, types, and models. Import from the
right files.

## Feature Description

Two separate remaining issues after Loop 8:

1. Generation batching still truncates occasionally. Even at `_BATCH_SIZE = 15`, some
   batches hit the `max_tokens` ceiling and return fewer entries than requested. The system
   currently does not detect this and silently drops the missing entries.

2. Source attribution contains wrong links that are not CTAs — real named-entity anchor
   texts ("Perplexity Computer", "JP Morgan Chase", "robots") appearing on unrelated
   stories. These contaminating links enter a chunk during HTML parsing, before
   deduplication, and cannot be filtered by scoring heuristics.

## User Story

As a user reading a newsletter digest,
I want every story to have a correct source link and a complete set of entries,
So that I can trust the digest reflects all reviewed stories without dropped entries or
mislabeled sources.

## Problem Statement

### Problem 1: Undetected generation truncation

`generate_digest()` in `ai/claude_client.py` calls the Claude API with `max_tokens=8192`.
When a batch contains unusually verbose entries, the model's output is cut mid-response.
When this happens, `stop_reason` is `"max_tokens"` instead of `"end_turn"`. The current
code does not check `stop_reason`, so it proceeds with a partial tool output, gets fewer
entries than requested, logs a count-mismatch warning, and silently drops the remainder.

Reducing `_BATCH_SIZE` pushes the ceiling further out but does not eliminate the risk —
entry verbosity varies unpredictably with content. The correct fix is to detect truncation
and recover, not to guess a safe static size.

### Problem 2: Within-chunk link contamination from parsing

After the per-chunk fix in Loop 8, cross-chunk contamination is solved. The remaining
wrong links come from within a single chunk's own `links` list — specifically, from
adjacent stories in the newsletter HTML being merged into one section.

The parser (`_extract_sections()` in `ingestion/email_parser.py`) splits HTML at
blank-line or HR boundaries. When newsletters use dense table-based or `<div>`-stacked
layouts, `html2text` may produce only a single newline between adjacent stories, causing
`_SECTION_SPLIT_PATTERN` (which requires `\n{2,}`) to miss the boundary. Both stories
and all their links land in one section dict. `_build_sources()` then scores these links
and picks what looks like the best one — which may belong to the adjacent story.

Because these are real, descriptive anchor texts, the CTA filter has no effect. **This is
a parsing bug, not a scoring bug.** The fix belongs in `_extract_sections()`.

**The fix approach for Problem 2 must not be assumed before inspection.** The exact
failure mode must be observed via a diagnostic script before any code is changed.

## Scope

- In scope:
  - Detecting `stop_reason == "max_tokens"` in `generate_digest()` and recovering by
    retrying the truncated batch in two halves
  - Creating a diagnostic script to inspect real section boundaries and link lists
  - A targeted fix to `_extract_sections()` based on inspection findings (Loop 9C)
  - Tests for both changes

- Out of scope:
  - Changing `_score_source()` or `_build_sources()` scoring logic
  - Changing `_BATCH_SIZE` as the primary fix
  - Changing the deduplication threshold
  - The 30-day validation run (deferred until both issues are resolved)

## Solution Statement

**Loop 9A** adds truncation detection to `generate_digest()`: when a batch returns
`stop_reason == "max_tokens"`, the batch is split in half and each half is retried as a
separate API call, with results merged in order. Retry is limited to one level (no
recursive splitting).

**Loop 9B** creates a diagnostic script (`scripts/inspect_sections.py`) that dumps real
section boundaries and link lists from a `.eml` file. Running it against an affected
newsletter reveals which of three failure modes is present: single-newline boundary miss,
heading-merge overreach, or mispositioned inline links.

**Loop 9C** implements the targeted fix in `_extract_sections()` based on the Loop 9B
findings. The exact change is determined by inspection. Constraints: do not over-split
legitimate single-story sections, do not filter sponsor or job-listing links.

## Feature Metadata

**Feature Type**: Bug Fix (two independent bugs)
**Estimated Complexity**: Medium
**Primary Systems Affected**: `ai/claude_client.py`, `ingestion/email_parser.py`
**Dependencies**: None new
**Assumptions**:
- `claude-haiku-4-5` maximum output tokens is 8192 and cannot be raised
- At least one affected newsletter `.eml` file is available locally for Loop 9B inspection

---

## CONTEXT REFERENCES

### Relevant Codebase Files — IMPORTANT: YOU MUST READ THESE FILES BEFORE IMPLEMENTING

- `ai/claude_client.py` (lines 143–213) — Why: `generate_digest()` batch loop; `response.stop_reason` is available on the response object after each API call; `_MAX_TOKENS` is the ceiling
- `ingestion/email_parser.py` (lines 237–301) — Why: `_extract_sections()` is where sections and their `links` lists are formed; this is the fix target for Problem 2
- `ingestion/email_parser.py` (lines 80–82) — Why: `_SECTION_SPLIT_PATTERN`; understanding the current split regex is required before changing it
- `ingestion/email_parser.py` (lines 257–269) — Why: heading-merge logic; one of the three failure modes for Problem 2
- `ingestion/email_parser.py` (lines 280–289) — Why: per-section link extraction loop; links are collected from all inline markdown in the section text
- `processing/embedder.py` (lines 78–109) — Why: `_segment_email()` converts `ParsedEmail.sections` into `StoryChunk` objects; `chunk.links = section["links"]`; confirms that link contamination in sections flows directly into chunks
- `processing/deduplicator.py` (lines 57–72) — Why: `_build_sources()` scores links per chunk; cannot distinguish same-story vs adjacent-story links if both are already in `chunk.links`
- `tests/test_claude_client.py` — Why: existing generation batch tests; new retry-split tests must be added here

### New Files to Create

- `tests/test_claude_client.py` — Updated (not new): add three retry-split arithmetic tests
- `tests/test_email_parser.py` — New: section boundary and link isolation tests (Loop 9C)
- `scripts/inspect_sections.py` — New: one-off diagnostic script for Loop 9B; not a permanent test file

### Patterns to Follow

**Stop-reason check** — `response.stop_reason` is a string on the Anthropic response
object. Pattern: check `== "max_tokens"` immediately after the debug log block (line
~166 in `claude_client.py`), before the `tool_input` extraction block.

**Logging pattern** (from `claude_client.py` line 166):
```python
logger.debug(
    "Batch %d/%d response: stop_reason=%r  input_tokens=%d  output_tokens=%d",
    batch_num, len(batches), response.stop_reason,
    response.usage.input_tokens, response.usage.output_tokens,
)
```

**Retry inline** — No retry utility exists in the project. Implement the half-split
retry inline within `generate_digest()`, not as a separate helper.

**Test pattern** (from `tests/test_claude_client.py`): Pure unit tests. No mocking, no
external imports beyond the module under test. Arithmetic tests only for split logic.

---

## IMPLEMENTATION PLAN

### Phase 1: Generation Truncation Detection (Loop 9A)

Add `stop_reason == "max_tokens"` detection to `generate_digest()`. When triggered,
split the affected batch into two halves and retry each half as a separate API call.
Append results in order. Cap retry at one level — if a retry half also truncates, accept
the partial output with a warning.

### Phase 2: Parser Section Boundary Inspection (Loop 9B)

Create `scripts/inspect_sections.py` — a standalone diagnostic script that prints
section boundaries and links from a real `.eml` file by calling `_extract_sections()`
directly. Run against affected newsletters. Observe and record the failure mode before
writing any fix.

Three failure modes to distinguish:
1. **Single-newline boundary** — `html2text` emits `\n` (not `\n\n`) between adjacent
   stories; `_SECTION_SPLIT_PATTERN` misses it
2. **Heading-merge overreach** — a heading is merged with a following section that
   already contains multiple stories
3. **Inline link position** — `html2text` floats links from a table element to the end
   of the block, placing them in the next story's section

### Phase 3: Parser Section Boundary Fix (Loop 9C)

Implement the targeted fix in `_extract_sections()` per the Loop 9B finding. Add
`tests/test_email_parser.py`. Run full test suite to confirm no regressions.

Fix approach depends on failure mode found:
- Mode 1: strengthen split pattern (e.g. also split on mid-section `\n#+\s` heading lines)
- Mode 2: narrow heading-merge condition (e.g. only merge if following section is short)
- Mode 3: clip link extraction to links appearing before the first subsequent heading

---

## STEP-BY-STEP TASKS

IMPORTANT: Execute every task in order, top to bottom. Each task is atomic and
independently testable.

### UPDATE `ai/claude_client.py` — truncation detection + retry

- **WHERE**: After the `logger.debug(...)` response log block (~line 166); before the `tool_input` extraction block
- **IMPLEMENT**: Add `if response.stop_reason == "max_tokens":` block that:
  1. Logs a warning with batch number, entry count, and stop reason
  2. Splits the current `batch` into two halves: `half_a = batch[:len(batch)//2 + len(batch)%2]`, `half_b = batch[len(batch)//2 + len(batch)%2:]`
  3. For each half, calls `_build_user_message(half, folder)`, calls the API, runs the same `tool_input` extraction and count-mismatch check as the main loop, and appends results to `result`
  4. If a retry half itself returns `stop_reason == "max_tokens"`, logs a warning and proceeds with its partial output (no recursion)
  5. `continue` after processing both halves to skip the normal extraction code for this iteration
- **GOTCHA**: The retry halves are full API calls — they need the same `try/except anthropic.APIError` wrapping as the main loop
- **GOTCHA**: `half_a` takes the ceiling half for odd-numbered batches so no entry is silently omitted from the split
- **VALIDATE**: `python -m pytest tests/test_claude_client.py -v`

### UPDATE `tests/test_claude_client.py` — retry-split arithmetic tests

- **IMPLEMENT**: Add three tests:
  - `test_retry_split_15_entries`: `batch = list(range(15))`, split at `len//2 + len%2 = 8` → halves of 8 and 7
  - `test_retry_split_1_entry`: `batch = [0]` → halves of 1 and 0 (or just 1); verify no entry is lost
  - `test_retry_split_2_entries`: `batch = [0, 1]` → halves of 1 and 1
- **PATTERN**: Mirror the existing `test_batch_split_*` tests in the same file
- **VALIDATE**: `python -m pytest tests/test_claude_client.py -v`

### CREATE `scripts/inspect_sections.py` — diagnostic script

- **IMPLEMENT**: Standalone script that:
  1. Accepts a `.eml` file path as a CLI argument (`sys.argv[1]`)
  2. Reads and parses the file with `email.message_from_bytes()` / `policy.default`
  3. Extracts the HTML part with `msg.get_body(preferencelist=("html",)).get_content()`
  4. Calls `_extract_sections(html_text)` directly from `ingestion.email_parser`
  5. Prints for each section: index, char count, full text, and all links with anchor text
- **PURPOSE**: Reproduce the exact section boundaries the production pipeline sees; no AI or network calls
- **NOT a test file** — does not use pytest; lives in `scripts/`, not `tests/`
- **VALIDATE**: `python scripts/inspect_sections.py path/to/affected_email.eml` runs without error and prints at least one section

### RUN + OBSERVE Loop 9B inspection

- **RUN**: `python scripts/inspect_sections.py path/to/affected_email.eml`
- **OBSERVE**: For each section that contains links from a different story's domain than its text, note whether:
  - The section text contains two distinct story headlines (→ Mode 1: single-newline miss)
  - The section text starts with a heading belonging to a different story (→ Mode 2: heading-merge overreach)
  - The link anchor text appears after the section's main prose ends (→ Mode 3: link position)
- **DELIVERABLE**: Written observation of the failure mode before Loop 9C begins

### UPDATE `ingestion/email_parser.py` — fix `_extract_sections()` section boundaries

- **IMPLEMENT**: [Determined by Loop 9B inspection — do not implement until failure mode is confirmed]
- **CONSTRAINTS**:
  - Do not filter links by anchor text beyond `_is_boilerplate_link()` already does
  - Do not reduce link pool for legitimate single-story sponsor sections
  - Do not change `_build_sources()` or `_score_source()`
  - Any change to `_SECTION_SPLIT_PATTERN` must not over-split sections that were correctly formed
- **GOTCHA**: `html2text` output varies by newsletter; test against multiple newsletter types before finalising
- **VALIDATE**: `python scripts/inspect_sections.py path/to/affected_email.eml` — section previously merging two stories is now split

### CREATE `tests/test_email_parser.py` — section boundary unit tests

- **IMPLEMENT**: Unit tests for `_extract_sections()` covering at minimum:
  - Adjacent story HTML blocks separated by `\n\n` in `html2text` output (baseline — must still split)
  - Adjacent story HTML blocks separated by `\n` only (must now split after fix)
  - Heading-only section merged with its correct following body section
  - Links from story A's section do not appear in story B's section when stories are adjacent
  - A section with a single legitimate sponsor link with a descriptive anchor is preserved unchanged
- **VALIDATE**: `python -m pytest tests/test_email_parser.py -v`

---

## TESTING STRATEGY

### Unit Tests

**Loop 9A** — Pure arithmetic tests on the half-split calculation. No mocking. Three
cases: odd-sized batch (15), single entry (1), two entries (2). These test that the split
arithmetic produces the right half sizes and that concatenating both halves preserves
input order.

**Loop 9C** — Unit tests for `_extract_sections()` using minimal synthetic HTML strings.
Each test constructs a small HTML snippet that reproduces the failure mode and asserts
the corrected section count and link assignment. Legitimate sponsor and job-listing
sections must be tested to confirm they are unaffected.

### Integration Tests

None for this loop. The diagnostic script (`scripts/inspect_sections.py`) serves as a
manual integration check against real email HTML.

### Edge Cases

- Batch of size 1 that truncates: half_a has 1 entry, half_b is empty — verify no crash
- All links in a section are from adjacent stories (no correct link available): fallback
  to existing behavior — do not drop the section
- Section that is legitimately long (single detailed story): must not be split by the fix

---

## VALIDATION COMMANDS

### Level 1: Syntax

```bash
cd "/Users/natalie/Documents/Agentic AI/Newsletter Digest Agent" && \
  .venv/bin/python -c "import ai.claude_client; import ingestion.email_parser; print('PASSED: syntax ok')"
```

### Level 2: Unit Tests — After Loop 9A

```bash
cd "/Users/natalie/Documents/Agentic AI/Newsletter Digest Agent" && \
  .venv/bin/python -m pytest tests/test_claude_client.py -v
```

### Level 2: Unit Tests — After Loop 9C (full suite)

```bash
cd "/Users/natalie/Documents/Agentic AI/Newsletter Digest Agent" && \
  .venv/bin/python -m pytest tests/ -v
```

### Level 3: Diagnostic Inspection — After Loop 9B

```bash
cd "/Users/natalie/Documents/Agentic AI/Newsletter Digest Agent" && \
  .venv/bin/python scripts/inspect_sections.py path/to/affected_email.eml
```

### Level 3: Diagnostic Inspection — After Loop 9C (confirm fix)

```bash
cd "/Users/natalie/Documents/Agentic AI/Newsletter Digest Agent" && \
  .venv/bin/python scripts/inspect_sections.py path/to/affected_email.eml
```

### Level 4: Manual Validation

Run a 1-day digest and verify:
- No "entry count mismatch" warnings in the log
- All story entries have source links with anchor text matching their own story content
- No anchor texts from unrelated stories appear in any source attribution

---

## MANUAL VERIFICATION CHECKLIST

- [ ] `generate_digest()` in `ai/claude_client.py` contains a `stop_reason == "max_tokens"` check
- [ ] When truncation is detected, the batch is split into two halves and both are retried in order
- [ ] If a retry half also truncates, a warning is logged and execution continues (no infinite retry)
- [ ] `scripts/inspect_sections.py` exists and runs against a real `.eml` file without error
- [ ] Loop 9B failure mode has been identified and recorded before Loop 9C begins
- [ ] `_extract_sections()` fix is implemented per the confirmed failure mode
- [ ] Sponsor sections with single descriptive links are unaffected by the parser fix
- [ ] All 32 tests (29 existing + 3 new retry-split tests) pass after Loop 9A
- [ ] All tests including new `test_email_parser.py` tests pass after Loop 9C

## ROLLBACK CONSIDERATIONS

- Loop 9A: changes are isolated to `generate_digest()`. Removing the `if stop_reason ==
  "max_tokens":` block exactly restores pre-Loop-9A behavior.
- Loop 9C: changes `_extract_sections()`. If the fix over-splits, reverting the pattern
  change restores previous section boundaries. `scripts/inspect_sections.py` can confirm
  section counts before and after.
- `scripts/inspect_sections.py` is a diagnostic tool — no production changes. Can be
  deleted at any time after Loop 9C is complete.

## ACCEPTANCE CRITERIA

### Loop 9A
- [ ] `generate_digest()` detects `stop_reason == "max_tokens"` and retries the truncated batch
- [ ] Retry uses two ordered halves; results are appended in input order
- [ ] Retry-half truncation is accepted with a warning, not recursed
- [ ] `python -m pytest tests/test_claude_client.py -v` — 9 passed

### Loop 9B
- [ ] `scripts/inspect_sections.py` exists and runs against a real `.eml` file
- [ ] At least one affected newsletter's sections have been inspected
- [ ] The failure mode is identified and recorded before Loop 9C begins

### Loop 9C
- [ ] The identified failure mode is fixed in `_extract_sections()`
- [ ] `scripts/inspect_sections.py` confirms previously-merged stories are now separate sections
- [ ] Sponsor sections with descriptive single-story links are unaffected
- [ ] `python -m pytest tests/ -v` — all existing 32 tests plus new `test_email_parser.py` tests pass

---

## COMPLETION CHECKLIST

- [ ] All tasks completed in order
- [ ] Each task validation passed immediately after implementation
- [ ] All validation commands executed successfully
- [ ] Full test suite passes (unit tests)
- [ ] Manual testing confirms no mislabeled source links and no dropped entries
- [ ] Acceptance criteria all met

---

## NOTES

**Why not cap links per section?** A `links[:1]` cap would pick the first link regardless
of quality, losing `_score_source()` benefit for multi-link single-story sections (common
in TLDR-style newsletters). The fix must be at the section-boundary level.

**Why detect truncation rather than lowering `_BATCH_SIZE` further?** At `_BATCH_SIZE =
10`, you'd make 5 API calls for 50 stories. Token variance is the real issue, not batch
size. Truncation detection + retry addresses variance directly and is robust to any
content. Well-behaved batches still run at 15 entries; only truncated ones split.

**Loop 9B/9C ordering is intentional.** Previous fix loops that skipped parser inspection
ended up fixing the wrong layer (deduplicator per-chunk fix, CTA filter). Inspect first,
fix second.

---

## VALIDATION OUTPUT REFERENCE — EXACT OUTPUTS TO CHECK (DO NOT SKIP)

- Item to check:
  `cd "/Users/natalie/Documents/Agentic AI/Newsletter Digest Agent" && .venv/bin/python -c "import ai.claude_client; import ingestion.email_parser; print('PASSED: syntax ok')"`
  Expected output or result:
  ```
  PASSED: syntax ok
  ```

- Item to check:
  `cd "/Users/natalie/Documents/Agentic AI/Newsletter Digest Agent" && .venv/bin/python -c "import inspect; from ai.claude_client import generate_digest; src = inspect.getsource(generate_digest); assert 'max_tokens' in src; print('PASSED: stop_reason check present in generate_digest')"`
  Expected output or result:
  ```
  PASSED: stop_reason check present in generate_digest
  ```

- Item to check:
  `cd "/Users/natalie/Documents/Agentic AI/Newsletter Digest Agent" && .venv/bin/python -m pytest tests/test_claude_client.py -v`
  Expected output or result:
  ```
  collected 9 items

  tests/test_claude_client.py::test_batch_size_value PASSED
  tests/test_claude_client.py::test_batch_split_50_groups PASSED
  tests/test_claude_client.py::test_batch_split_single_group PASSED
  tests/test_claude_client.py::test_batch_split_exactly_one_batch PASSED
  tests/test_claude_client.py::test_batch_split_16_groups PASSED
  tests/test_claude_client.py::test_batch_split_preserves_order PASSED
  tests/test_claude_client.py::test_retry_split_15_entries PASSED
  tests/test_claude_client.py::test_retry_split_1_entry PASSED
  tests/test_claude_client.py::test_retry_split_2_entries PASSED

  ========================= 9 passed in Xs =========================
  ```

- Item to check:
  File `scripts/inspect_sections.py` exists after Loop 9B
  Expected output or result:
  Running `ls "/Users/natalie/Documents/Agentic AI/Newsletter Digest Agent/scripts/inspect_sections.py"` returns the file path without error.

- Item to check:
  `cd "/Users/natalie/Documents/Agentic AI/Newsletter Digest Agent" && .venv/bin/python scripts/inspect_sections.py path/to/affected_email.eml`
  Expected output or result:
  Script runs without error and prints at least one block in this format (exact counts will vary):
  ```
  === Section 1 (NNN chars) ===
  <first 200 chars of section text>
  Links:
    [anchor text] -> https://...
  ```
  At least one section must be printed. No Python traceback.

- Item to check:
  After Loop 9C: `cd "/Users/natalie/Documents/Agentic AI/Newsletter Digest Agent" && .venv/bin/python scripts/inspect_sections.py path/to/affected_email.eml`
  Expected output or result:
  The section that previously contained links from two different stories now appears as
  two separate section blocks. Each section's links must have anchor texts that match
  the story described in that section's text — no cross-story link anchor texts.

- Item to check:
  `cd "/Users/natalie/Documents/Agentic AI/Newsletter Digest Agent" && .venv/bin/python -m pytest tests/ -v`
  Expected output or result:
  All 32 tests from the pre-Loop-9A suite plus all new `tests/test_email_parser.py` tests
  pass. Output ends with:
  ```
  ========================= NN passed in Xs =========================
  ```
  where NN is at least 37 (32 existing + at minimum 5 new email parser tests).
  No failures, no errors.

- Item to check:
  `generate_digest()` does not log "entry count mismatch" when running a real 1-day digest
  Expected output or result:
  The string "entry count mismatch" does not appear in the digest run log output.
  Confirmed by running a real digest and scanning log output.

- Item to check:
  File `tests/test_email_parser.py` exists after Loop 9C
  Expected output or result:
  Running `ls "/Users/natalie/Documents/Agentic AI/Newsletter Digest Agent/tests/test_email_parser.py"` returns the file path without error.
