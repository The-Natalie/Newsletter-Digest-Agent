# Feature: Clustering Threshold Adjustment

The following plan should be complete, but it's important that you validate documentation and codebase patterns and task sanity before you start implementing.

Pay special attention to file paths — the threshold value appears in multiple places and must be kept in sync.

## Feature Description

Lower the semantic similarity threshold used by `community_detection` for story clustering from `0.82` to `0.78`. A lower threshold allows stories that are semantically related but framed differently (e.g., multiple newsletter angles on the same Nvidia/GTC story) to be grouped into the same cluster rather than appearing as separate story groups. This reduces fragmentation in the digest output.

## User Story

As a newsletter digest reader,
I want related stories about the same event to appear as one merged entry,
So that I don't see the same news story split into several near-duplicate digest entries.

## Problem Statement

At threshold `0.82`, stories that cover the same event with meaningfully different framing (different headlines, angles, or vocabulary) fail to cluster together. This results in digest fragmentation: multiple entries that all describe the same event, differing only in emphasis or phrasing. Lowering to `0.78` broadens the clustering window slightly without sacrificing precision for genuinely unrelated stories.

## Scope

- **In scope:** Change the default `DEDUP_THRESHOLD` value from `0.82` to `0.78` in the three locations where it appears as a maintained constant or comment.
- **Out of scope:** Algorithm changes, prompt changes, test infrastructure, any other pipeline modifications.

## Solution Statement

Update the default `dedup_threshold` in `config.py`, the value and comment in `.env.example`, and the two references in `CLAUDE.md`. The setting is already fully configurable via `DEDUP_THRESHOLD` in `.env` — this change only updates the out-of-the-box default.

Note: `PRD.md` and `.agents/plans/prime-summary.md` already reflect `0.78` and do not need changes.

## Feature Metadata

**Feature Type**: Bug Fix / Tuning
**Estimated Complexity**: Low
**Primary Systems Affected**: `config.py` (runtime default), `.env.example` (documented default), `CLAUDE.md` (project instructions)
**Dependencies**: None
**Assumptions**: The threshold is already plumbed end-to-end through `settings.dedup_threshold` in `embedder.py` — no code logic changes are needed, only the default value.

---

## CONTEXT REFERENCES

### Relevant Codebase Files — YOU MUST READ THESE FILES BEFORE IMPLEMENTING!

- `config.py` (line 19) — `dedup_threshold: float = 0.82` — the Pydantic Settings default to change
- `.env.example` (lines 49–53) — comment ("Default 0.82…") and value (`DEDUP_THRESHOLD=0.82`) to update
- `CLAUDE.md` (line 113) — inline reference to `0.82` in Deduplication pattern section
- `CLAUDE.md` (line 153) — `DEDUP_THRESHOLD=0.82` in the Environment Variables section
- `processing/embedder.py` (line 173–178) — confirms `settings.dedup_threshold` is passed directly to `community_detection`; no code change needed, context only

### New Files to Create

None.

### Relevant Documentation

No external documentation needed — this is a single numeric constant change.

### Patterns to Follow

**Config pattern** (`config.py`):
```python
# Pipeline tuning
max_emails_per_run: int = 50
dedup_threshold: float = 0.82   # ← change to 0.78
```

**`.env.example` comment style** (lines 49–53):
```
# DEDUP_THRESHOLD: cosine similarity threshold for story-level deduplication.
# Range: 0.0–1.0. Higher = stricter matching (fewer merges).
# Default 0.82 works well for most newsletter mixes; tune after first real run.

DEDUP_THRESHOLD=0.82
```
→ Comment and value both reference `0.82` and must both change to `0.78`.

---

## IMPLEMENTATION PLAN

### Phase 1: Update the default value

Change `dedup_threshold` default in `config.py` from `0.82` to `0.78`.

### Phase 2: Update the example config

Update `.env.example` — change the inline comment ("Default 0.82…") and the `DEDUP_THRESHOLD=0.82` value to `0.78`.

### Phase 3: Update project instructions

Update `CLAUDE.md` — change both occurrences of `0.82` that refer to the dedup threshold to `0.78`.

---

## STEP-BY-STEP TASKS

### UPDATE `config.py`

- **CHANGE**: `dedup_threshold: float = 0.82` → `dedup_threshold: float = 0.78`
- **LOCATION**: Line 19
- **GOTCHA**: Do not change any other line — this is a single-value edit
- **VALIDATE**: `python -c "from config import settings; assert settings.dedup_threshold == 0.78, settings.dedup_threshold; print('PASSED: dedup_threshold =', settings.dedup_threshold)"`

---

### UPDATE `.env.example`

- **CHANGE 1**: Comment line — `# Default 0.82 works well for most newsletter mixes; tune after first real run.` → `# Default 0.78 works well for most newsletter mixes; tune after first real run.`
- **CHANGE 2**: Value line — `DEDUP_THRESHOLD=0.82` → `DEDUP_THRESHOLD=0.78`
- **GOTCHA**: Both the comment and the value reference `0.82`; both must be updated
- **VALIDATE**: `grep "DEDUP_THRESHOLD" .env.example`

---

### UPDATE `CLAUDE.md`

- **CHANGE 1**: Line 113 — `Threshold: \`0.82\` cosine similarity` → `Threshold: \`0.78\` cosine similarity`
- **CHANGE 2**: Line 153 — `DEDUP_THRESHOLD=0.82` → `DEDUP_THRESHOLD=0.78`
- **GOTCHA**: These are in two different sections (Key Patterns and Environment Variables); update both
- **VALIDATE**: `grep "DEDUP_THRESHOLD\|dedup_threshold\|0\.82\|0\.78" CLAUDE.md`

---

## TESTING STRATEGY

### Unit Tests

No test suite exists yet. Validation is via `python -c` one-liners and `grep`.

### Integration Tests

None required for a constant-value change. The threshold is exercised by the full pipeline run, which is a manual validation step.

### Edge Cases

- **`.env` override**: If a local `.env` file has `DEDUP_THRESHOLD=0.82` set explicitly, pydantic-settings will use that value instead of the new default. This is expected behavior — the user controls their own `.env`. The plan does not modify `.env` (it is gitignored and user-managed). Add a note to the manual verification checklist to remind the user to check their `.env` if they want the new default applied.
- **Stale residual 0.82 references**: After changes, `grep -r "0\.82" .` (excluding `.venv`) should return no remaining references in maintained source files.

---

## VALIDATION COMMANDS

### Level 1: Syntax check

```bash
python -c "from config import settings; print('config OK')"
```

### Level 2: Assert new default value

```bash
python -c "from config import settings; assert settings.dedup_threshold == 0.78, settings.dedup_threshold; print('PASSED: dedup_threshold =', settings.dedup_threshold)"
```

### Level 3: Verify no stale 0.82 in maintained files

```bash
grep -rn "0\.82" config.py .env.example CLAUDE.md
```
Expected: no output (zero matches across these three files).

### Level 4: Verify 0.78 in all updated files

```bash
grep -n "0\.78" config.py .env.example CLAUDE.md
```
Expected: three matches — one per file.

### Level 5: Manual verification

Run the pipeline against a real newsletter folder and confirm the log line shows the new threshold:
```
Clustered N story chunks into M groups (threshold=0.78)
```

---

## MANUAL VERIFICATION CHECKLIST

- [ ] `config.py` default is `0.78` (confirmed by Level 2 assertion command above)
- [ ] `.env.example` comment and value both say `0.78`
- [ ] `CLAUDE.md` Key Patterns section says `0.78`
- [ ] `CLAUDE.md` Environment Variables section says `0.78`
- [ ] No `0.82` remains in `config.py`, `.env.example`, or `CLAUDE.md` (confirmed by Level 3 grep above)
- [ ] Local `.env` checked — if it contains `DEDUP_THRESHOLD=0.82`, update it to `0.78` to receive the new default (user action, not automated)

## ROLLBACK CONSIDERATIONS

Revert is three one-line edits: change `0.78` back to `0.82` in `config.py` (line 19), `.env.example` (comment + value), and `CLAUDE.md` (two lines). No migrations, no DB changes, no dependencies.

## ACCEPTANCE CRITERIA

- [ ] `settings.dedup_threshold` returns `0.78` when no `.env` override is present
- [ ] `.env.example` documents `DEDUP_THRESHOLD=0.78`
- [ ] `CLAUDE.md` reflects `0.78` in both the Key Patterns and Environment Variables sections
- [ ] No remaining `0.82` in `config.py`, `.env.example`, or `CLAUDE.md`
- [ ] Full pipeline run logs `threshold=0.78`

---

## COMPLETION CHECKLIST

- [ ] All tasks completed in order
- [ ] Each task validation passed immediately
- [ ] All validation commands executed successfully
- [ ] Manual verification checklist complete
- [ ] Acceptance criteria all met

---

## NOTES

- `PRD.md` and `.agents/plans/prime-summary.md` already reference `0.78` — do not re-edit them.
- `.agents/plans/project-summary.md` contains a stale `0.82` reference but is a historical snapshot, not a maintained config file — leave it unchanged.
- `processing/embedder.py` passes `settings.dedup_threshold` directly to `community_detection` with no hardcoded fallback — the pipeline will use the new default automatically with no code changes.
- The user may want to test `0.77` as a next step if `0.78` still shows fragmentation. This is not in scope here.

---

## VALIDATION OUTPUT REFERENCE

- Item to check:
  `python -c "from config import settings; assert settings.dedup_threshold == 0.78, settings.dedup_threshold; print('PASSED: dedup_threshold =', settings.dedup_threshold)"`
  Expected output or result:
  `PASSED: dedup_threshold = 0.78`

- Item to check:
  `grep "DEDUP_THRESHOLD" .env.example`
  Expected output or result:
  ```
  # DEDUP_THRESHOLD: cosine similarity threshold for story-level deduplication.
  DEDUP_THRESHOLD=0.78
  ```

- Item to check:
  `grep -n "0\.82" config.py .env.example CLAUDE.md`
  Expected output or result:
  (no output — zero matches)

- Item to check:
  `grep -n "0\.78" config.py .env.example CLAUDE.md`
  Expected output or result:
  ```
  config.py:19:    dedup_threshold: float = 0.78
  .env.example:51:# Default 0.78 works well for most newsletter mixes; tune after first real run.
  .env.example:53:DEDUP_THRESHOLD=0.78
  CLAUDE.md:113:- Threshold: `0.78` cosine similarity (configurable via `DEDUP_THRESHOLD` in `.env`).
  CLAUDE.md:153:DEDUP_THRESHOLD=0.78
  ```

- Item to check:
  Local `.env` file checked for stale `DEDUP_THRESHOLD=0.82`
  Expected output or result:
  Either `DEDUP_THRESHOLD=0.78` (if set) or the line is absent (user relies on config.py default). If `DEDUP_THRESHOLD=0.82` is present in `.env`, user must update it manually.
