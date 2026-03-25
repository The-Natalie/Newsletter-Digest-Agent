# Feature: ingestion/imap_client.py

The following plan should be complete, but validate codebase patterns before starting.

Pay special attention to: IMAPClient's synchronous API (not async), correct IMAP date-range semantics, batch-fetch logic, and keeping this module free of AI/processing concerns.

## Feature Description

Create `ingestion/imap_client.py` — the module that opens an SSL IMAP connection, selects the requested folder in read-only mode, searches for messages within the requested date range, and returns raw MIME bytes for each matched email (batched in groups of 50, capped by `MAX_EMAILS_PER_RUN`). This is the first stage of the pipeline.

## User Story

As the digest pipeline,
I want a function that accepts a folder name and date range and returns a list of raw email bytes,
So that the email parser can extract structured content without knowing anything about IMAP.

## Problem Statement

No IMAP ingestion layer exists. Without it, the pipeline cannot retrieve any emails and the entire feature set is blocked.

## Scope

- In scope: SSL connection, read-only folder selection, SINCE/BEFORE date search, batched BODY.PEEK[] fetch, MAX_EMAILS_PER_RUN cap, `ingestion/__init__.py`
- Out of scope: MIME parsing (done in `email_parser.py`), async IMAP, multi-folder runs, OAuth2

## Solution Statement

Use `IMAPClient` (sync, version 3.1.0 installed) with SSL. Wrap the full lifecycle — connect, login, select, search, fetch, logout — inside a single `fetch_emails()` function that manages the connection internally. Return `list[bytes]` (raw MIME messages) so `email_parser.py` receives exactly what it needs. Raise `FolderNotFoundError` (a custom exception defined in this module) on unknown folder names so callers can produce a human-readable error message.

## Feature Metadata

**Feature Type**: New Capability
**Estimated Complexity**: Low
**Primary Systems Affected**: `ingestion/imap_client.py`, `ingestion/__init__.py`
**Dependencies**: `imapclient==3.1.0` (installed), `config.settings` (already implemented)
**Assumptions**: `.env` has valid IMAP credentials; `config.py` is implemented and working

---

## CONTEXT REFERENCES

### Relevant Codebase Files — READ BEFORE IMPLEMENTING

- `config.py` (whole file, 29 lines) — provides `settings.imap_host`, `settings.imap_port`, `settings.imap_username`, `settings.imap_password`, `settings.max_emails_per_run`; import `settings` directly
- `CLAUDE.md` — Key Patterns → Email Ingestion section: "Always select folders with `readonly=True` and fetch with `BODY.PEEK[]` — never modify mailbox state. Fetch emails in batches of 50."
- `PRD.md` §7 Feature 1 (lines 238–253) — full spec: SSL, read-only, SINCE/BEFORE, BODY.PEEK[], batch 50, folder-not-found error message format
- `PRD.md` §14 Risk 1 (lines 694–699) — IMAP provider quirks, error message requirements: "Folder '...' not found. Available folders: ..."
- `database.py` (whole file) — reference only; shows the module-level pattern: short, focused, no class, exports at top level

### New Files to Create

- `ingestion/__init__.py` — empty, marks `ingestion/` as a Python package
- `ingestion/imap_client.py` — `FolderNotFoundError`, `fetch_emails()` function

### Relevant Documentation — READ BEFORE IMPLEMENTING

- IMAPClient docs: https://imapclient.readthedocs.io/en/3.1.0/api.html
  - Why: exact method signatures for `select_folder`, `search`, `fetch`; confirms `IMAPClient` is a context manager
- IMAPClient search criteria: https://imapclient.readthedocs.io/en/3.1.0/api.html#imapclient.IMAPClient.search
  - Why: `SINCE` and `BEFORE` accept `datetime.date` objects directly; `BEFORE` is exclusive

### Patterns to Follow

**Module-level pattern** (mirror `database.py`):
- No class definitions; top-level functions only
- Import `settings` from `config` at module top
- Export the public function and the custom exception

**Error handling**:
- Raise custom `FolderNotFoundError(folder_name, available_folders)` when folder not found
- Let all other IMAPClient/socket errors propagate naturally to the caller (digest_builder catches and logs them)
- Do NOT swallow exceptions silently

**Naming conventions** (snake_case throughout):
- `fetch_emails(folder, date_start, date_end) -> list[bytes]`
- `FolderNotFoundError` — `Exception` subclass, stores `folder` and `available` attributes

**Batch chunking pattern**:
```python
def _chunks(lst, n):
    for i in range(0, len(lst), n):
        yield lst[i : i + n]
```

---

## IMPLEMENTATION PLAN

### Phase 1: Package scaffolding

Create `ingestion/__init__.py` to make `ingestion` a Python package.

### Phase 2: Core implementation

Write `ingestion/imap_client.py` with:
1. `FolderNotFoundError` custom exception
2. `_chunks()` private helper
3. `fetch_emails()` public function

### Phase 3: Validation

Import-check, then run against the live IMAP server to confirm real email bytes are returned.

---

## STEP-BY-STEP TASKS

### TASK 1 — CREATE `ingestion/__init__.py`

- **IMPLEMENT**: Create an empty file; its presence makes `ingestion` importable as a package
- **VALIDATE**: `python -c "import ingestion; print('ingestion package OK')"`

---

### TASK 2 — CREATE `ingestion/imap_client.py`

- **IMPLEMENT**: Full module with `FolderNotFoundError`, `_chunks()`, and `fetch_emails()`
- **IMPORTS**: `from __future__ import annotations`, `import ssl`, `from datetime import date, timedelta`, `from imapclient import IMAPClient`, `from config import settings`
- **PATTERN**: `IMAPClient` is used as a context manager — `with IMAPClient(host, port=port, ssl=True) as client:`; this handles `logout()` automatically on exit including on exceptions

**`FolderNotFoundError` spec:**
- Subclass of `Exception`
- Constructor: `__init__(self, folder: str, available: list[str])`
- Stores `self.folder` and `self.available`
- `__str__` returns: `f"Folder '{self.folder}' was not found. Available folders: {', '.join(self.available)}"`

**`_chunks(lst, n)` spec:**
- Private generator
- Yields successive `n`-sized slices of `lst`
- Used to split UID list into batches of `BATCH_SIZE = 50`

**`fetch_emails(folder, date_start, date_end)` spec — step by step:**

1. Open connection: `IMAPClient(settings.imap_host, port=settings.imap_port, ssl=True)`
2. Login: `client.login(settings.imap_username, settings.imap_password)`
3. Select folder — handle folder-not-found:
   ```python
   try:
       client.select_folder(folder, readonly=True)
   except client.Error:
       available = [str(f) for f in client.list_folders()]
       raise FolderNotFoundError(folder, available)
   ```
   - **GOTCHA**: `client.list_folders()` returns tuples of `(flags, delimiter, name)` — extract the name (index 2) from each tuple: `[str(f[2]) for f in client.list_folders()]`
   - **GOTCHA**: `select_folder` on a non-existent folder raises `imapclient.exceptions.IMAPClientError` (subclass of `Exception`). Catching `Exception` is too broad; use `IMAPClient.Error` (the base error class exposed on the instance at `client.Error`) — but actually `imapclient` raises `imaplib.IMAP4.error` for folder not found. The safest catch is `Exception` narrowed by checking the error message, OR catch `imapclient.exceptions.IMAPClientError`. See GOTCHA below.
   - **GOTCHA**: The exact exception type varies by server. The safest approach is to **pre-check** by listing folders before selecting:
     ```python
     folders_raw = client.list_folders()
     folder_names = [str(f[2]) for f in folders_raw]
     if folder not in folder_names:
         raise FolderNotFoundError(folder, folder_names)
     client.select_folder(folder, readonly=True)
     ```
     This is more reliable than catching the exception from `select_folder`.

4. Search by date range:
   ```python
   uids = client.search(["SINCE", date_start, "BEFORE", date_end + timedelta(days=1)])
   ```
   - **GOTCHA**: IMAP `SINCE` is inclusive (from date_start); `BEFORE` is exclusive (messages strictly before the given date). To include `date_end`, pass `date_end + timedelta(days=1)` to `BEFORE`.
   - **GOTCHA**: `client.search()` accepts `datetime.date` objects directly for `SINCE`/`BEFORE` criteria — no string formatting needed with IMAPClient.

5. Cap at `MAX_EMAILS_PER_RUN`: `uids = uids[:settings.max_emails_per_run]`

6. Batch fetch and collect raw bytes:
   ```python
   raw_messages: list[bytes] = []
   for batch in _chunks(uids, BATCH_SIZE):
       response = client.fetch(batch, ["BODY.PEEK[]"])
       for uid in batch:
           raw_messages.append(response[uid][b"BODY[]"])
   return raw_messages
   ```
   - **GOTCHA**: The fetch response key is `b"BODY[]"` (bytes), not `b"BODY.PEEK[]"`. `BODY.PEEK[]` is the IMAP command to fetch without setting the \Seen flag; the response key in IMAPClient is always `b"BODY[]"`.
   - **GOTCHA**: If `uids` is empty (no emails match the date range), `client.fetch()` must not be called — it will raise an error with an empty UID list. Check `if not uids: return []` before the batch loop.

- **VALIDATE**: `python -c "from ingestion.imap_client import fetch_emails, FolderNotFoundError; print('import OK')"`

**Full module layout to implement:**
```
from __future__ import annotations

import ssl
from datetime import date, timedelta

from imapclient import IMAPClient

from config import settings

BATCH_SIZE = 50


class FolderNotFoundError(Exception):
    def __init__(self, folder: str, available: list[str]) -> None:
        self.folder = folder
        self.available = available

    def __str__(self) -> str:
        return f"Folder '{self.folder}' was not found. Available folders: {', '.join(self.available)}"


def _chunks(lst: list, n: int):
    for i in range(0, len(lst), n):
        yield lst[i : i + n]


def fetch_emails(folder: str, date_start: date, date_end: date) -> list[bytes]:
    """Connect to IMAP, select folder (read-only), search by date range, return raw MIME bytes.

    Args:
        folder: IMAP folder name (exact string, case-sensitive on most servers).
        date_start: First day of the date range (inclusive).
        date_end: Last day of the date range (inclusive).

    Returns:
        List of raw MIME email bytes, capped at settings.max_emails_per_run.

    Raises:
        FolderNotFoundError: If the folder does not exist on the server.
    """
    with IMAPClient(settings.imap_host, port=settings.imap_port, ssl=True) as client:
        client.login(settings.imap_username, settings.imap_password)

        # Pre-check folder existence before selecting
        folders_raw = client.list_folders()
        folder_names = [str(f[2]) for f in folders_raw]
        if folder not in folder_names:
            raise FolderNotFoundError(folder, folder_names)

        client.select_folder(folder, readonly=True)

        # SINCE is inclusive; BEFORE is exclusive — add 1 day to include date_end
        uids = client.search(["SINCE", date_start, "BEFORE", date_end + timedelta(days=1)])

        # Cap total emails processed per run
        uids = uids[: settings.max_emails_per_run]

        if not uids:
            return []

        raw_messages: list[bytes] = []
        for batch in _chunks(uids, BATCH_SIZE):
            response = client.fetch(batch, ["BODY.PEEK[]"])
            for uid in batch:
                raw_messages.append(response[uid][b"BODY[]"])

        return raw_messages
```

---

## TESTING STRATEGY

No dedicated test file is required for this module in Phase 1. The primary validation is a live connection check — mocking IMAP yields low confidence given provider quirks. Full unit tests with mock IMAP belong in Phase 4.

### Smoke Test (live IMAP)

Run against the real IMAP server to confirm the function returns bytes:
```bash
python -c "
from datetime import date
from ingestion.imap_client import fetch_emails
emails = fetch_emails('INBOX', date(2026, 3, 1), date(2026, 3, 25))
print(f'Fetched {len(emails)} emails')
if emails:
    print(f'First email size: {len(emails[0])} bytes')
    print(f'First 100 bytes: {emails[0][:100]}')
"
```
Expected: prints fetch count and first bytes of a raw MIME message (starts with `b'Received:'` or `b'MIME-Version:'` or similar headers).

### Error Path Test

Confirm `FolderNotFoundError` is raised and contains useful information:
```bash
python -c "
from datetime import date
from ingestion.imap_client import fetch_emails, FolderNotFoundError
try:
    fetch_emails('__nonexistent_folder_xyz__', date(2026, 3, 1), date(2026, 3, 25))
except FolderNotFoundError as e:
    print('FolderNotFoundError raised OK')
    print(str(e))
"
```
Expected: prints `FolderNotFoundError raised OK` then the error message listing available folders.

### Edge Cases

- Empty date range (no emails match): `uids` is empty → returns `[]` without calling `fetch()`
- `MAX_EMAILS_PER_RUN` cap: only first N UIDs are fetched even if more match
- Folder name case sensitivity: Gmail folder names are case-sensitive; `"inbox"` ≠ `"INBOX"` on some servers
- `date_start == date_end`: should return emails from that single day (SINCE date_start, BEFORE date_start + 1 day)

---

## VALIDATION COMMANDS

### Level 1: Syntax & Import Check

```bash
cd "/Users/natalie/Documents/Agentic AI/Newsletter Digest Agent" && .venv/bin/python -c "import ingestion; print('ingestion package OK')"
```
Expected output: `ingestion package OK`

```bash
cd "/Users/natalie/Documents/Agentic AI/Newsletter Digest Agent" && .venv/bin/python -c "from ingestion.imap_client import fetch_emails, FolderNotFoundError; print('import OK')"
```
Expected output: `import OK`

### Level 2: FolderNotFoundError string format

```bash
cd "/Users/natalie/Documents/Agentic AI/Newsletter Digest Agent" && .venv/bin/python -c "
from ingestion.imap_client import FolderNotFoundError
e = FolderNotFoundError('Test', ['INBOX', 'Sent'])
print(str(e))
"
```
Expected output: `Folder 'Test' was not found. Available folders: INBOX, Sent`

### Level 3: Live IMAP smoke test

```bash
cd "/Users/natalie/Documents/Agentic AI/Newsletter Digest Agent" && .venv/bin/python -c "
from datetime import date
from ingestion.imap_client import fetch_emails
emails = fetch_emails('INBOX', date(2026, 3, 1), date(2026, 3, 25))
print(f'Fetched {len(emails)} emails')
if emails:
    print(f'First email size: {len(emails[0])} bytes')
    print(f'Type: {type(emails[0])}')
"
```
Expected output: `Fetched N emails` (N ≥ 0), followed by size and `<class 'bytes'>` if N > 0.

### Level 4: FolderNotFoundError on live server

```bash
cd "/Users/natalie/Documents/Agentic AI/Newsletter Digest Agent" && .venv/bin/python -c "
from datetime import date
from ingestion.imap_client import fetch_emails, FolderNotFoundError
try:
    fetch_emails('__nonexistent_folder_xyz__', date(2026, 3, 1), date(2026, 3, 25))
    print('ERROR: no exception raised')
except FolderNotFoundError as e:
    print('FolderNotFoundError raised OK')
    print(str(e))
"
```
Expected output: `FolderNotFoundError raised OK` then `Folder '__nonexistent_folder_xyz__' was not found. Available folders: <comma-separated list>`

---

## MANUAL VERIFICATION CHECKLIST

- [ ] `ingestion/__init__.py` exists (empty file)
- [ ] `ingestion/imap_client.py` imports cleanly
- [ ] `FolderNotFoundError.__str__` matches PRD §14 error message format
- [ ] Live IMAP smoke test returns `list[bytes]` with at least one element
- [ ] Invalid folder raises `FolderNotFoundError` with available folder list
- [ ] Response key `b"BODY[]"` used (not `b"BODY.PEEK[]"`)
- [ ] `readonly=True` passed to `select_folder`
- [ ] `BEFORE` receives `date_end + timedelta(days=1)` (inclusive end)

## ROLLBACK CONSIDERATIONS

- This is a new file in a new directory; rollback = delete `ingestion/`
- No database changes, no migrations, no config changes required

## ACCEPTANCE CRITERIA

- [ ] `ingestion/__init__.py` exists
- [ ] `fetch_emails()` returns `list[bytes]` on success
- [ ] `FolderNotFoundError` raised with correct message for unknown folder
- [ ] `readonly=True` always set on `select_folder`
- [ ] `BODY.PEEK[]` used for fetching (no \Seen flag modification)
- [ ] UIDs capped at `settings.max_emails_per_run` before fetching
- [ ] Empty UID list handled without calling `fetch()`
- [ ] All Level 1–4 validation commands pass

---

## COMPLETION CHECKLIST

- [ ] Task 1: `ingestion/__init__.py` created and validated
- [ ] Task 2: `ingestion/imap_client.py` created and validated
- [ ] All validation commands executed with passing output

---

## NOTES

**Why synchronous IMAPClient, not async?**
CLAUDE.md explicitly requires `IMAPClient` (not `aioimaplib`). The Phase 1 pipeline runs synchronously as a CLI script. FastAPI (Phase 2) will call it via `run_in_executor` if needed, but that is out of scope for this plan.

**Why pre-check folder existence instead of catching `select_folder` exception?**
Different IMAP servers raise different exception types for unknown folders — some raise `IMAPClient.Error`, others raise `imaplib.IMAP4.error`, others return an `[NO]` response that IMAPClient converts in inconsistent ways. Pre-listing folders avoids this fragility entirely and has the added benefit of providing the list of available folders for the error message without a second round-trip (since we already fetched them).

**Why `ssl=True` and not a custom `ssl_context`?**
Port 993 always uses IMAPS (SSL from the start). `ssl=True` creates a default SSL context with certificate verification enabled — correct and secure for all major providers. Custom SSL contexts would only be needed for self-signed certificates or unusual configurations.

**Why no `__all__` export list?**
The module is small and internal. `from ingestion.imap_client import fetch_emails, FolderNotFoundError` is explicit enough.

---

## VALIDATION OUTPUT REFERENCE — EXACT OUTPUTS TO CHECK

- Command or step:
  `.venv/bin/python -c "import ingestion; print('ingestion package OK')"`
  Expected output:
  `ingestion package OK`

- Command or step:
  `.venv/bin/python -c "from ingestion.imap_client import fetch_emails, FolderNotFoundError; print('import OK')"`
  Expected output:
  `import OK`

- Command or step:
  `.venv/bin/python -c "from ingestion.imap_client import FolderNotFoundError; e = FolderNotFoundError('Test', ['INBOX', 'Sent']); print(str(e))"`
  Expected output:
  `Folder 'Test' was not found. Available folders: INBOX, Sent`

- Command or step:
  Live IMAP smoke test — `.venv/bin/python -c "from datetime import date; from ingestion.imap_client import fetch_emails; emails = fetch_emails('INBOX', date(2026, 3, 1), date(2026, 3, 25)); print(f'Fetched {len(emails)} emails'); ..."`
  Expected output:
  `Fetched N emails` (N ≥ 0); if N > 0: `First email size: X bytes` and `Type: <class 'bytes'>`

- Command or step:
  FolderNotFoundError live test — `.venv/bin/python -c "... fetch_emails('__nonexistent_folder_xyz__', ...) ..."`
  Expected output:
  `FolderNotFoundError raised OK`
  `Folder '__nonexistent_folder_xyz__' was not found. Available folders: <comma-separated list of real folder names>`
