# Feature: processing/digest_builder.py

The following plan should be complete, but validate codebase patterns before starting.

Pay special attention to: the SQLAlchemy Core async INSERT/UPDATE pattern using `async_session` from `database.py`, the exact shape of the response dict (matches PRD §10 API spec), and the `asyncio.run()` wrapper in `__main__` so the CLI works without an event loop.

## Feature Description

Create `processing/digest_builder.py` — the top-level pipeline orchestrator that chains all five pipeline stages (fetch → parse → embed/cluster → deduplicate → generate) into a single `async def build_digest()` function. It persists each run to the `digest_runs` SQLite table (status: "pending" → "complete" or "failed"), returns the completed digest as a dict, and exposes the pipeline as a CLI entry point runnable via `python -m processing.digest_builder`.

## User Story

As the digest pipeline,
I want a single `build_digest(folder, date_start, date_end)` function that runs all stages end-to-end and returns a structured digest JSON dict,
So that both the CLI (for testing) and the API layer (Phase 2) can trigger a full digest run with a single call.

## Problem Statement

All five pipeline stages are implemented but isolated. Nothing connects them. `digest_builder.py` provides that connection, adds the database persistence layer, and gives the developer a working CLI to validate the full pipeline against real data before building the web interface.

## Scope

- In scope: `processing/digest_builder.py` — `build_digest()` function, pipeline orchestration, DB INSERT/UPDATE, CLI `__main__` block
- Out of scope: FastAPI routing (Phase 2), PDF export (Phase 3), error formatting for HTTP responses (Phase 2)

## Solution Statement

`build_digest()` is `async` (because `generate_digest()` and SQLAlchemy async both require it). It:
1. Generates a UUID run ID and inserts a "pending" row into `digest_runs`
2. Runs the four sync stages (fetch, parse, embed/cluster, deduplicate) inline
3. Awaits `generate_digest()` for the AI step
4. On success: UPDATEs the row to "complete" with `story_count` and `output_json`
5. On failure: UPDATEs to "failed" with `error_message`, then re-raises
6. Returns the full digest response dict

The CLI `__main__` block uses `asyncio.run()` and prints JSON to stdout.

## Feature Metadata

**Feature Type**: New Capability
**Estimated Complexity**: Medium
**Primary Systems Affected**: `processing/digest_builder.py`, `digest_runs` table
**Dependencies**: all five pipeline modules (already implemented), `database.async_session`, `database.digest_runs`
**Assumptions**:
- `alembic upgrade head` has been run — `digest_runs` table exists in `data/digest.db`
- Valid IMAP credentials and `ANTHROPIC_API_KEY` are needed for live pipeline validation (Level 4)
- `datetime.utcnow()` produces a naive UTC datetime; SQLite `DateTime` column stores it as-is

---

## CONTEXT REFERENCES

### Relevant Codebase Files — READ BEFORE IMPLEMENTING

- `database.py` (lines 7–27) — `engine`, `async_session: async_sessionmaker[AsyncSession]`, `digest_runs` Table with all 9 columns; import both
- `ingestion/imap_client.py` (lines 29–32) — `fetch_emails(folder, date_start, date_end) -> list[bytes]` signature; synchronous; raises `FolderNotFoundError`
- `ingestion/email_parser.py` (lines 30–34) — `ParsedEmail` dataclass and `parse_emails(raw_messages: list[bytes]) -> list[ParsedEmail]` (synchronous)
- `processing/embedder.py` (lines 61–105) — `embed_and_cluster(parsed_emails: list[ParsedEmail]) -> list[list[StoryChunk]]` (synchronous)
- `processing/deduplicator.py` (lines 48–75) — `deduplicate(clusters: list[list[StoryChunk]]) -> list[StoryGroup]` (synchronous)
- `ai/claude_client.py` (lines 105–180) — `generate_digest(story_groups: list[StoryGroup], folder: str) -> list[dict]` (`async`)
- `config.py` — not directly used in digest_builder, but imported modules use `settings` internally

### New Files to Create

- `processing/digest_builder.py` — full pipeline orchestrator + CLI

### Patterns to Follow

**Module structure** (mirror `ai/claude_client.py` lines 1–11):
```python
from __future__ import annotations

import argparse
import asyncio
import json
import logging
import uuid
from datetime import date, datetime

import sqlalchemy as sa

from ai.claude_client import generate_digest
from database import async_session, digest_runs
from ingestion.email_parser import parse_emails
from ingestion.imap_client import fetch_emails
from processing.deduplicator import deduplicate
from processing.embedder import embed_and_cluster

logger = logging.getLogger(__name__)
```

**SQLAlchemy Core async INSERT** (pattern to use in `build_digest`):
```python
async with async_session() as session:
    await session.execute(
        digest_runs.insert().values(
            id=run_id,
            run_at=run_at,
            folder=folder,
            date_start=date_start,
            date_end=date_end,
            status="pending",
        )
    )
    await session.commit()
```

**SQLAlchemy Core async UPDATE**:
```python
async with async_session() as session:
    await session.execute(
        digest_runs.update()
        .where(digest_runs.c.id == run_id)
        .values(status="complete", story_count=len(stories), output_json=json.dumps(response))
    )
    await session.commit()
```

**Logging pattern** (mirror `processing/deduplicator.py` lines 66–70):
```python
logger.info("Stage name: %d item(s)", count)
logger.error("Pipeline failed: %s", exc)
```

**Datetime formatting for response** — use `datetime.utcnow()` (naive UTC, compatible with SQLite DateTime):
```python
run_at = datetime.utcnow()
generated_at_str = run_at.strftime("%Y-%m-%dT%H:%M:%SZ")
```

**Response dict shape** (must match PRD §10 API spec exactly):
```python
{
    "id": run_id,                         # str UUID
    "generated_at": generated_at_str,     # "2026-03-17T09:14:00Z"
    "folder": folder,                     # str
    "date_start": date_start.isoformat(), # "2026-03-10"
    "date_end": date_end.isoformat(),     # "2026-03-17"
    "story_count": len(stories),          # int
    "stories": stories,                   # list[dict] from generate_digest()
}
```

---

## IMPLEMENTATION PLAN

### Phase 1: Pipeline function

Implement `build_digest()` — the async orchestrator with all five stages, DB persistence, and error handling.

### Phase 2: CLI entry point

Implement the `__main__` block with `argparse` and `asyncio.run()`.

---

## STEP-BY-STEP TASKS

### TASK 1 — CREATE `processing/digest_builder.py`

All sub-tasks build the same file.

#### 1a — Imports and module setup

- **IMPORTS** (exact list, in this order):
  ```python
  from __future__ import annotations

  import argparse
  import asyncio
  import json
  import logging
  import uuid
  from datetime import date, datetime

  import sqlalchemy as sa

  from ai.claude_client import generate_digest
  from database import async_session, digest_runs
  from ingestion.email_parser import parse_emails
  from ingestion.imap_client import fetch_emails
  from processing.deduplicator import deduplicate
  from processing.embedder import embed_and_cluster

  logger = logging.getLogger(__name__)
  ```
- **GOTCHA**: `import sqlalchemy as sa` is required for `sa.select()` in the DB read-back validation command (Level 3). Even if not used in the main function body, keep it for consistency with `database.py` imports.

#### 1b — `build_digest()` function

- **IMPLEMENT** (complete function body):

  ```python
  async def build_digest(
      folder: str,
      date_start: date,
      date_end: date,
  ) -> dict:
      """Run the full digest pipeline end-to-end and persist the result.

      Args:
          folder: IMAP folder name to read newsletters from.
          date_start: Start of the date range (inclusive).
          date_end: End of the date range (inclusive).

      Returns:
          Digest response dict with keys:
          id, generated_at, folder, date_start, date_end, story_count, stories.

      Raises:
          Exception: Any pipeline or API error. The DB row is updated to status="failed"
                     before the exception propagates to the caller.
      """
      run_id = str(uuid.uuid4())
      run_at = datetime.utcnow()

      # ── Insert pending row ──────────────────────────────────────────────────
      async with async_session() as session:
          await session.execute(
              digest_runs.insert().values(
                  id=run_id,
                  run_at=run_at,
                  folder=folder,
                  date_start=date_start,
                  date_end=date_end,
                  status="pending",
              )
          )
          await session.commit()

      logger.info(
          "Digest run started: id=%s folder='%s' %s→%s",
          run_id[:8],
          folder,
          date_start,
          date_end,
      )

      try:
          # ── Stage 1: Fetch emails ──────────────────────────────────────────
          logger.info("Stage 1/5 — Fetching emails from '%s'", folder)
          raw_emails = fetch_emails(folder, date_start, date_end)
          logger.info("Stage 1/5 — Fetched %d raw email(s)", len(raw_emails))

          # ── Stage 2: Parse emails ─────────────────────────────────────────
          logger.info("Stage 2/5 — Parsing emails")
          parsed_emails = parse_emails(raw_emails)
          logger.info("Stage 2/5 — Parsed %d email(s)", len(parsed_emails))

          # ── Stage 3: Embed and cluster ────────────────────────────────────
          logger.info("Stage 3/5 — Embedding and clustering story chunks")
          clusters = embed_and_cluster(parsed_emails)
          logger.info("Stage 3/5 — Produced %d cluster(s)", len(clusters))

          # ── Stage 4: Deduplicate ──────────────────────────────────────────
          logger.info("Stage 4/5 — Deduplicating clusters into story groups")
          story_groups = deduplicate(clusters)
          logger.info("Stage 4/5 — Produced %d story group(s)", len(story_groups))

          # ── Stage 5: AI generation ────────────────────────────────────────
          logger.info("Stage 5/5 — Generating digest entries via Claude")
          stories = await generate_digest(story_groups, folder)
          logger.info("Stage 5/5 — Generated %d digest entry/entries", len(stories))

          # ── Build response dict ───────────────────────────────────────────
          response: dict = {
              "id": run_id,
              "generated_at": run_at.strftime("%Y-%m-%dT%H:%M:%SZ"),
              "folder": folder,
              "date_start": date_start.isoformat(),
              "date_end": date_end.isoformat(),
              "story_count": len(stories),
              "stories": stories,
          }

          # ── Update DB: complete ───────────────────────────────────────────
          async with async_session() as session:
              await session.execute(
                  digest_runs.update()
                  .where(digest_runs.c.id == run_id)
                  .values(
                      status="complete",
                      story_count=len(stories),
                      output_json=json.dumps(response),
                  )
              )
              await session.commit()

          logger.info(
              "Digest run complete: id=%s stories=%d",
              run_id[:8],
              len(stories),
          )
          return response

      except Exception as exc:
          # ── Update DB: failed ─────────────────────────────────────────────
          logger.error("Digest run failed: id=%s error=%s", run_id[:8], exc)
          async with async_session() as session:
              await session.execute(
                  digest_runs.update()
                  .where(digest_runs.c.id == run_id)
                  .values(
                      status="failed",
                      error_message=str(exc),
                  )
              )
              await session.commit()
          raise
  ```

- **GOTCHA**: `generate_digest()` is `async` — it must be `await`ed. The four preceding stages are synchronous and called directly (no `await`).
- **GOTCHA**: Both `session.execute()` and `session.commit()` must be `await`ed. Missing an `await` on `session.commit()` is a silent bug — the row update never lands.
- **GOTCHA**: Use separate `async with async_session()` context managers for each DB operation (insert, update-complete, update-failed). Do NOT reuse a single session across the full pipeline — the session would be held open during the multi-second IMAP fetch and Claude API call.
- **GOTCHA**: `output_json=json.dumps(response)` — `stories` is a `list[dict]` with `sources` as `list[dict]`. All values are JSON-serializable natively.

#### 1c — CLI `__main__` block

- **IMPLEMENT**:
  ```python
  if __name__ == "__main__":
      logging.basicConfig(
          level=logging.INFO,
          format="%(asctime)s %(levelname)-8s %(name)s — %(message)s",
          datefmt="%H:%M:%S",
      )

      parser = argparse.ArgumentParser(
          description="Generate a newsletter digest from an IMAP folder."
      )
      parser.add_argument("--folder", required=True, help="IMAP folder name")
      parser.add_argument("--start", required=True, metavar="YYYY-MM-DD", help="Start date (inclusive)")
      parser.add_argument("--end", required=True, metavar="YYYY-MM-DD", help="End date (inclusive)")
      args = parser.parse_args()

      date_start = date.fromisoformat(args.start)
      date_end = date.fromisoformat(args.end)

      result = asyncio.run(build_digest(args.folder, date_start, date_end))
      print(json.dumps(result, indent=2, ensure_ascii=False))
  ```
- **GOTCHA**: `asyncio.run()` creates a new event loop and runs the coroutine to completion. This is the correct pattern for calling an `async` function from a synchronous CLI entry point.
- **GOTCHA**: `date.fromisoformat("2026-03-10")` requires Python 3.7+. We're on 3.11+ so this is safe.
- **GOTCHA**: `ensure_ascii=False` preserves non-ASCII characters in newsletter text (accented letters, em dashes, etc.) in the printed output.
- **VALIDATE**: `cd "/Users/natalie/Documents/Agentic AI/Newsletter Digest Agent" && .venv/bin/python -m processing.digest_builder --help`

---

## TESTING STRATEGY

No separate test file. Validation uses a lightweight DB round-trip test (Level 3) and — if credentials are available — a live CLI run (Level 4).

### Edge Cases

- Empty email range (no emails match the date filter) → `fetch_emails` returns `[]` → `parse_emails([])` → `embed_and_cluster([])` → `deduplicate([])` → `generate_digest([], ...)` → all return empty → `story_count=0, stories=[]`; status="complete" (NOT "failed")
- `FolderNotFoundError` from `imap_client.py` → caught by `except Exception`, written to DB as status="failed", re-raised
- `anthropic.APIError` → same path as above

---

## VALIDATION COMMANDS

### Level 1: Import check

```bash
cd "/Users/natalie/Documents/Agentic AI/Newsletter Digest Agent" && .venv/bin/python -c "from processing.digest_builder import build_digest; print('import OK')"
```
Expected output:
```
import OK
```

### Level 2: Signature and async check

```bash
cd "/Users/natalie/Documents/Agentic AI/Newsletter Digest Agent" && .venv/bin/python -c "
import asyncio, inspect
from processing.digest_builder import build_digest
print('async:', asyncio.iscoroutinefunction(build_digest))
print('sig:', inspect.signature(build_digest))
"
```
Expected output:
```
async: True
sig: (folder: str, date_start: datetime.date, date_end: datetime.date) -> dict
```

### Level 3: CLI --help (no credentials required)

```bash
cd "/Users/natalie/Documents/Agentic AI/Newsletter Digest Agent" && .venv/bin/python -m processing.digest_builder --help
```
Expected output:
```
usage: digest_builder.py [-h] --folder FOLDER --start YYYY-MM-DD --end YYYY-MM-DD

Generate a newsletter digest from an IMAP folder.

options:
  -h, --help          show this help message and exit
  --folder FOLDER     IMAP folder name
  --start YYYY-MM-DD  Start date (inclusive)
  --end YYYY-MM-DD    End date (inclusive)
```

### Level 4: DB round-trip test (requires alembic upgrade head to have been run)

```bash
cd "/Users/natalie/Documents/Agentic AI/Newsletter Digest Agent" && .venv/bin/python -c "
import asyncio
import sqlalchemy as sa
import uuid
from datetime import date, datetime
from database import async_session, digest_runs

async def test_db_round_trip():
    run_id = str(uuid.uuid4())
    run_at = datetime.utcnow()

    # INSERT pending
    async with async_session() as session:
        await session.execute(
            digest_runs.insert().values(
                id=run_id,
                run_at=run_at,
                folder='test-folder',
                date_start=date.today(),
                date_end=date.today(),
                status='pending',
            )
        )
        await session.commit()

    # UPDATE complete
    async with async_session() as session:
        await session.execute(
            digest_runs.update()
            .where(digest_runs.c.id == run_id)
            .values(status='complete', story_count=3, output_json='{\"test\":true}')
        )
        await session.commit()

    # READ BACK
    async with async_session() as session:
        result = await session.execute(
            sa.select(digest_runs).where(digest_runs.c.id == run_id)
        )
        row = result.fetchone()

    assert row.folder == 'test-folder', f'folder mismatch: {row.folder}'
    assert row.status == 'complete', f'status mismatch: {row.status}'
    assert row.story_count == 3, f'story_count mismatch: {row.story_count}'
    assert row.output_json == '{\"test\":true}', f'output_json mismatch: {row.output_json}'
    print('DB round-trip test PASSED')
    print('run_id prefix:', run_id[:8])
    print('status:', row.status)
    print('story_count:', row.story_count)

asyncio.run(test_db_round_trip())
"
```
Expected output:
```
DB round-trip test PASSED
run_id prefix: <first 8 chars of UUID>
status: complete
story_count: 3
```

### Level 5: Live CLI run (requires valid IMAP + ANTHROPIC_API_KEY in .env)

```bash
cd "/Users/natalie/Documents/Agentic AI/Newsletter Digest Agent" && .venv/bin/python -m processing.digest_builder --folder "AI Newsletters" --start 2026-03-10 --end 2026-03-17
```
Expected output (values will vary):
```
HH:MM:SS INFO     processing.digest_builder — Digest run started: id=<8-chars> ...
HH:MM:SS INFO     processing.digest_builder — Stage 1/5 — Fetching emails from 'AI Newsletters'
HH:MM:SS INFO     processing.digest_builder — Stage 1/5 — Fetched <N> raw email(s)
...
HH:MM:SS INFO     processing.digest_builder — Digest run complete: id=<8-chars> stories=<N>
{
  "id": "<uuid>",
  "generated_at": "<ISO timestamp>Z",
  "folder": "AI Newsletters",
  "date_start": "2026-03-10",
  "date_end": "2026-03-17",
  "story_count": <N>,
  "stories": [...]
}
```
Note: Level 5 is blocked by the credential issue documented in prior sessions (IMAP auth failed). Skip and document as a follow-up item.

---

## MANUAL VERIFICATION CHECKLIST

- [ ] `processing/digest_builder.py` exists
- [ ] `build_digest` is `async` with signature `(folder: str, date_start: date, date_end: date) -> dict`
- [ ] `--help` output shows all three required CLI arguments
- [ ] DB round-trip test (Level 4) passes: INSERT pending, UPDATE complete, read-back matches
- [ ] `output_json` stores the full response dict as a JSON string (confirmed by Level 4 read-back)
- [ ] Each DB write uses a separate `async with async_session()` context (not one shared session)
- [ ] `asyncio.run()` is used in `__main__` (not `loop.run_until_complete`)

## ROLLBACK CONSIDERATIONS

- New file only; rollback = delete `processing/digest_builder.py`
- No schema changes; `digest_runs` table already exists from the Alembic migration

## ACCEPTANCE CRITERIA

- [ ] `build_digest(folder, date_start, date_end)` is `async` and returns the PRD §10 response dict shape
- [ ] On success: DB row has `status="complete"`, `story_count`, and `output_json` set
- [ ] On failure: DB row has `status="failed"` and `error_message` set; exception propagates
- [ ] All five pipeline stages called in order with correct inputs/outputs
- [ ] `python -m processing.digest_builder --folder X --start Y --end Z` prints formatted JSON to stdout
- [ ] All Levels 1–4 validation commands pass

---

## COMPLETION CHECKLIST

- [ ] Task 1a: imports written
- [ ] Task 1b: `build_digest()` implemented
- [ ] Task 1c: `__main__` block implemented
- [ ] Level 1 passed
- [ ] Level 2 passed
- [ ] Level 3 passed
- [ ] Level 4 passed
- [ ] Level 5 attempted (or skip documented with reason)

---

## NOTES

**Why three separate `async_session()` context managers (not one)?**
Each stage in the pipeline may take several seconds (IMAP fetch ~2–5s, Claude API ~5–15s). Holding an SQLAlchemy async session open across the entire pipeline would monopolize the connection unnecessarily. The "pending" row is committed immediately so the API layer can track in-progress runs if needed. The "complete"/"failed" update is a quick single-statement write at the end.

**Why `output_json` stores the full response dict?**
The Phase 2 API `GET /api/digests/latest` endpoint will read the most recent complete row and return the response. Storing the full dict means the API handler just parses `output_json` and returns it — no reconstruction logic needed.

**Why `datetime.utcnow()` instead of `datetime.now(tz=timezone.utc)`?**
SQLite's `DateTime` column type stores naive datetimes. Passing a timezone-aware datetime causes SQLAlchemy to emit a deprecation warning. `datetime.utcnow()` is naive UTC — consistent with the `server_default=sa.func.now()` behavior (SQLite's `now()` also returns naive UTC).

**Why `ensure_ascii=False` in the CLI print?**
Newsletter text routinely contains em dashes, curly quotes, and accented characters. `ensure_ascii=True` (the default) would produce `\u2014` escape sequences in the terminal output, making it hard to read during development.

---

## VALIDATION OUTPUT REFERENCE — EXACT OUTPUTS TO CHECK

- Item to check:
  `cd "/Users/natalie/Documents/Agentic AI/Newsletter Digest Agent" && .venv/bin/python -c "from processing.digest_builder import build_digest; print('import OK')"`
  Expected output or result:
  ```
  import OK
  ```

- Item to check:
  `cd "/Users/natalie/Documents/Agentic AI/Newsletter Digest Agent" && .venv/bin/python -c "import asyncio, inspect; from processing.digest_builder import build_digest; print('async:', asyncio.iscoroutinefunction(build_digest)); print('sig:', inspect.signature(build_digest))"`
  Expected output or result:
  ```
  async: True
  sig: (folder: str, date_start: datetime.date, date_end: datetime.date) -> dict
  ```

- Item to check:
  `cd "/Users/natalie/Documents/Agentic AI/Newsletter Digest Agent" && .venv/bin/python -m processing.digest_builder --help`
  Expected output or result:
  ```
  usage: digest_builder.py [-h] --folder FOLDER --start YYYY-MM-DD --end YYYY-MM-DD

  Generate a newsletter digest from an IMAP folder.

  options:
    -h, --help          show this help message and exit
    --folder FOLDER     IMAP folder name
    --start YYYY-MM-DD  Start date (inclusive)
    --end YYYY-MM-DD    End date (inclusive)
  ```

- Item to check:
  DB round-trip test (Level 4 command)
  Expected output or result:
  ```
  DB round-trip test PASSED
  run_id prefix: <first 8 chars of a valid UUID>
  status: complete
  story_count: 3
  ```

- Item to check:
  `processing/digest_builder.py` exists
  Expected output or result:
  File present at `processing/digest_builder.py` (visible in Completed Tasks section of execution report)
