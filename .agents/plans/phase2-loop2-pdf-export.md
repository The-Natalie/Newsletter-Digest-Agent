# Feature: Phase 2 Loop 2 — PDF Export

The following plan should be complete, but it's important that you validate documentation and codebase patterns and task sanity before you start implementing.

Pay special attention to naming of existing utils, types, and models. Import from the right files.

## Feature Description

Add `GET /api/digests/{digest_id}/pdf` endpoint in a new `api/export.py` module. The endpoint fetches the specified digest from the `digest_runs` table by ID, renders it as a PDF, and streams it back as a file attachment. weasyprint is the primary renderer; reportlab is the fallback if weasyprint raises.

## User Story

As a user
I want to download a digest as a PDF file
So that I can save, print, or share the digest offline

## Problem Statement

The API has no export capability. Users can only view digests in the browser. A PDF endpoint enables offline access and sharing without requiring a frontend change.

## Scope

- In scope: `api/export.py` (`GET /{digest_id}/pdf`), register router in `main.py`, `tests/test_export.py`
- Out of scope: new DB tables, migrations, email delivery, scheduled export, HTML template styling

## Solution Statement

Fetch `output_json` from `digest_runs` by `id`. Parse JSON into a story list, build an HTML string, render with weasyprint. If weasyprint raises, fall back to reportlab. Stream bytes as `application/pdf` attachment.

## Feature Metadata

**Feature Type**: New Capability
**Estimated Complexity**: Low
**Primary Systems Affected**: `api/export.py` (new), `main.py` (router registration)
**Dependencies**: weasyprint (already in requirements.txt), reportlab (already in requirements.txt)
**Assumptions**: `digest_id` is the `id` TEXT column (UUID string) in `digest_runs`. `output_json` is a JSON string containing `{id, generated_at, folder, date_start, date_end, story_count, stories[]}`.

---

## CONTEXT REFERENCES

### Relevant Codebase Files — MUST READ BEFORE IMPLEMENTING

- `api/digests.py` — Error response pattern (`JSONResponse(status_code=N, content={"error": "..."})`), DB query pattern (`async with async_session() as session: result = await session.execute(...); row = result.first()`), router declaration
- `main.py` — Router registration order; StaticFiles mount MUST remain last
- `database.py` (lines 9-27) — `async_session`, `digest_runs` table; column `id` is TEXT PK, `output_json` is TEXT
- `tests/test_api.py` — TestClient + mock pattern; how `async_session` context manager is mocked

### New Files to Create

- `api/export.py` — GET `/{digest_id}/pdf` route
- `tests/test_export.py` — Unit tests (TestClient + mocked rendering)

### Files to Modify

- `main.py` — Add `from api.export import router as export_router` and `app.include_router(export_router, prefix="/api/digests")`

### Relevant Documentation

- weasyprint: `HTML(string=html_str).write_pdf()` → `bytes`. Constructor accepts `string=` for in-memory HTML.
- reportlab: `from io import BytesIO; from reportlab.lib.pagesizes import letter; from reportlab.pdfgen import canvas; buf = BytesIO(); c = canvas.Canvas(buf, pagesize=letter); c.drawString(x, y, text); c.showPage(); c.save(); pdf_bytes = buf.getvalue()`
- FastAPI streaming response: `from fastapi.responses import StreamingResponse; from io import BytesIO; StreamingResponse(BytesIO(pdf_bytes), media_type="application/pdf", headers={"Content-Disposition": 'attachment; filename="digest-2026-04-01.pdf"'})`

### Patterns to Follow

**Router declaration** (mirror `api/digests.py:16`):
```python
from fastapi import APIRouter
router = APIRouter()
```

**DB query pattern** (mirror `api/digests.py:53-60`):
```python
async with async_session() as session:
    result = await session.execute(
        digest_runs.select().where(digest_runs.c.id == digest_id)
    )
    row = result.first()
if row is None or not row.output_json:
    return JSONResponse(status_code=404, content={"error": "Digest not found"})
```

**Error response pattern** (mirror `api/digests.py:46`):
```python
return JSONResponse(status_code=500, content={"error": str(exc)})
```

**Router registration in main.py** (insert before StaticFiles mount, mirror lines 22-23):
```python
from api.export import router as export_router
app.include_router(export_router, prefix="/api/digests")
```

**Logging** (mirror `api/digests.py:14`):
```python
logger = logging.getLogger(__name__)
```

**Mock pattern for async_session** (mirror `tests/test_api.py:91-102`):
```python
mock_row = MagicMock()
mock_row.output_json = json.dumps(stored)
mock_result = MagicMock()
mock_result.first.return_value = mock_row
mock_session = AsyncMock()
mock_session.execute.return_value = mock_result
mock_cm = MagicMock()
mock_cm.__aenter__ = AsyncMock(return_value=mock_session)
mock_cm.__aexit__ = AsyncMock(return_value=False)
with patch("api.export.async_session", return_value=mock_cm):
    response = client.get("/api/digests/test-uuid/pdf")
```

---

## IMPLEMENTATION PLAN

### Phase 1: Create api/export.py

Build the route handler with weasyprint primary + reportlab fallback.

### Phase 2: Register router in main.py

Add import and `include_router` call before the StaticFiles mount.

### Phase 3: Tests

Create `tests/test_export.py` with 5 test cases covering 200 (weasyprint), 200 (fallback), 404 (no row), 404 (no output_json), 500 (both renderers fail).

---

## STEP-BY-STEP TASKS

### CREATE api/export.py

- **IMPLEMENT**: `GET /{digest_id}/pdf` endpoint using `APIRouter`
- **IMPLEMENT**: DB fetch via `async with async_session()` → query `digest_runs` by `id`; return 404 if row missing or `output_json` is null/empty
- **IMPLEMENT**: Parse `output_json` → build minimal HTML string containing folder name, date range, and all story items (title, body, link, newsletter, date)
- **IMPLEMENT**: `_render_pdf(html: str) -> bytes` — tries weasyprint first, falls back to reportlab; raises `RuntimeError` only if both fail
- **IMPLEMENT**: weasyprint: `from weasyprint import HTML; return HTML(string=html).write_pdf()`
- **IMPLEMENT**: reportlab fallback: write title line + story lines onto letter-size canvas; use `BytesIO` buffer; wrap long lines with `textwrap.wrap`
- **IMPLEMENT**: Derive filename from `date_start` in the stored JSON: `f"digest-{data['date_start']}.pdf"`
- **IMPLEMENT**: Return `StreamingResponse(BytesIO(pdf_bytes), media_type="application/pdf", headers={"Content-Disposition": f'attachment; filename="{filename}"'})`
- **IMPLEMENT**: Catch all exceptions from `_render_pdf`; return `JSONResponse(status_code=500, content={"error": str(exc)})`
- **PATTERN**: DB query → `api/digests.py:53-60`; error response → `api/digests.py:44-46`; logger → `api/digests.py:14`
- **IMPORTS**: `from __future__ import annotations`, `import json`, `import logging`, `import textwrap`, `from io import BytesIO`, `from fastapi import APIRouter`, `from fastapi.responses import JSONResponse, StreamingResponse`, `from database import async_session, digest_runs`
- **GOTCHA**: weasyprint may emit warnings to stderr — that is fine; do not suppress them
- **GOTCHA**: Route path inside export.py must be `/{digest_id}/pdf` (not `/api/digests/...`) since the router is registered with `prefix="/api/digests"` in main.py
- **GOTCHA**: reportlab `canvas.Canvas` draws from the bottom of the page upward; start `y` near top of page (e.g., `750`) and decrement for each line; add a new page when `y < 50`
- **VALIDATE**: `python -c "import api.export; print('ok')"`

### UPDATE main.py

- **ADD**: `from api.export import router as export_router` import alongside existing router imports (lines 9-10)
- **ADD**: `app.include_router(export_router, prefix="/api/digests")` after the digests router line (line 23) and before the StaticFiles mount (line 26)
- **PATTERN**: Mirror lines 9-10 and 22-23 of `main.py`
- **GOTCHA**: StaticFiles mount (`app.mount(...)`) must remain the LAST line in the app setup
- **VALIDATE**: `python -c "from main import app; print('ok')"`

### CREATE tests/test_export.py

- **IMPLEMENT**: 5 test functions using `TestClient(app)` and `unittest.mock`
- **IMPLEMENT**: `test_pdf_returns_200_weasyprint` — mock `api.export._render_pdf` to return `b"%PDF-fake"`, mock `async_session`, assert 200, `content-type: application/pdf`, `content-disposition` contains `digest-`
- **IMPLEMENT**: `test_pdf_fallback_reportlab` — same as above but name implies fallback path (mock still returns `b"%PDF-fake"`; the distinction is tested via the render function unit test below, not the route test)
- **IMPLEMENT**: `test_pdf_no_row_returns_404` — mock `async_session` with `first()` returning `None`; assert 404 and `"error"` in body
- **IMPLEMENT**: `test_pdf_no_output_json_returns_404` — mock row with `output_json = None`; assert 404 and `"error"` in body
- **IMPLEMENT**: `test_pdf_render_error_returns_500` — mock `api.export._render_pdf` to raise `RuntimeError("both renderers failed")`; mock `async_session` with valid row; assert 500 and `"error"` in body
- **IMPLEMENT**: `test_render_pdf_uses_weasyprint` — unit test for `_render_pdf` directly: patch `weasyprint.HTML` to return a mock whose `write_pdf()` returns `b"pdf"`, assert return value is `b"pdf"`
- **IMPLEMENT**: `test_render_pdf_falls_back_to_reportlab` — patch `weasyprint.HTML` to raise `Exception("no weasyprint")`, patch `reportlab.pdfgen.canvas.Canvas` to return a mock that correctly fakes save/getvalue, assert bytes returned
- **PATTERN**: Mirror `tests/test_api.py` for mock shape, client setup, import order
- **IMPORTS**: `from __future__ import annotations`, `import json`, `import os`, `import sys`, `sys.path.insert(0, ...)`, `from unittest.mock import AsyncMock, MagicMock, patch`, `from fastapi.testclient import TestClient`, `from main import app`, `from api.export import _render_pdf`
- **VALIDATE**: `python -m pytest tests/test_export.py -v`

---

## TESTING STRATEGY

### Unit Tests

- `test_render_pdf_uses_weasyprint` — verify weasyprint called with correct HTML string
- `test_render_pdf_falls_back_to_reportlab` — verify fallback invoked when weasyprint raises

### Route Tests (via TestClient)

- 200 with `application/pdf` content-type and attachment header
- 404 when row not found
- 404 when `output_json` is null
- 500 when `_render_pdf` raises

### Edge Cases

- `output_json` is empty string `""` → treat as missing → 404
- `date_start` present in JSON → used in filename
- Stories with `title=None` → render gracefully (use placeholder or skip title line)
- Stories with `link=None` → render gracefully (omit link line)

---

## VALIDATION COMMANDS

### Level 1: Syntax & Style

```bash
python -c "import api.export; print('import ok')"
python -c "from main import app; print('main import ok')"
```

### Level 2: Unit Tests

```bash
python -m pytest tests/test_export.py -v
```

### Level 3: Full Test Suite (no regressions)

```bash
python -m pytest tests/ -v
```

### Level 4: Manual Validation

```bash
# Start server (needs .env with valid DB path)
# curl http://localhost:8000/api/digests/<id>/pdf --output /tmp/test.pdf
# Check file is valid PDF: file /tmp/test.pdf
# Should print: /tmp/test.pdf: PDF document, version ...
```

---

## MANUAL VERIFICATION CHECKLIST

- [ ] `api/export.py` exists and imports cleanly
- [ ] `main.py` includes export router before StaticFiles mount
- [ ] `tests/test_export.py` exists
- [ ] All `test_export.py` tests pass
- [ ] Full test suite passes with no regressions
- [ ] 404 returned for unknown digest ID
- [ ] 404 returned when `output_json` is null
- [ ] 500 returned when both renderers raise
- [ ] 200 response has `content-type: application/pdf`
- [ ] 200 response has `content-disposition: attachment; filename="digest-....pdf"`

---

## ROLLBACK CONSIDERATIONS

- Delete `api/export.py` and `tests/test_export.py`
- Revert `main.py` two-line change (import + include_router)
- No DB changes, no migrations needed

## ACCEPTANCE CRITERIA

- [ ] `GET /api/digests/{digest_id}/pdf` returns 200 with `application/pdf` for a valid completed digest
- [ ] Filename in `Content-Disposition` is `digest-{date_start}.pdf`
- [ ] weasyprint is tried first; reportlab used only as fallback
- [ ] 404 returned when digest ID not found or `output_json` is null
- [ ] 500 returned when both renderers fail
- [ ] All validation commands pass
- [ ] No regressions in existing 8 tests in `tests/test_api.py`

---

## COMPLETION CHECKLIST

- [ ] All tasks completed in order
- [ ] Each task validation passed
- [ ] All validation commands executed successfully
- [ ] Full test suite passes (unit + route)
- [ ] No linting or import errors
- [ ] Acceptance criteria all met

---

## VALIDATION OUTPUT REFERENCE

- Item to check:
  `python -c "import api.export; print('import ok')"`
  Expected output or result:
  `import ok`

- Item to check:
  `python -c "from main import app; print('main import ok')"`
  Expected output or result:
  `main import ok`

- Item to check:
  `python -m pytest tests/test_export.py -v`
  Expected output or result:
  All 7 tests listed as PASSED, 0 failed, 0 errors

- Item to check:
  `python -m pytest tests/ -v`
  Expected output or result:
  All tests (existing 8 from test_api.py + 7 from test_export.py = 15 total) PASSED, 0 failed

- Item to check:
  `api/export.py` file exists
  Expected output or result:
  File present at `api/export.py`

- Item to check:
  `tests/test_export.py` file exists
  Expected output or result:
  File present at `tests/test_export.py`

- Item to check:
  `main.py` includes export router before StaticFiles mount
  Expected output or result:
  `from api.export import router as export_router` and `app.include_router(export_router, prefix="/api/digests")` present in `main.py`, appearing before `app.mount(...)`

- Item to check:
  404 returned for unknown digest ID
  Expected output or result:
  `test_pdf_no_row_returns_404` PASSED in pytest output

- Item to check:
  404 returned when `output_json` is null
  Expected output or result:
  `test_pdf_no_output_json_returns_404` PASSED in pytest output

- Item to check:
  500 returned when both renderers raise
  Expected output or result:
  `test_pdf_render_error_returns_500` PASSED in pytest output

- Item to check:
  200 response has `content-type: application/pdf` and correct `content-disposition`
  Expected output or result:
  `test_pdf_returns_200_weasyprint` PASSED in pytest output, asserting both headers

## NOTES

- The `_render_pdf` function is intentionally public (no leading underscore) in the module for direct unit testing. The plan uses a single underscore to signal internal-only use while keeping it importable in tests.
- reportlab fallback does not need to be beautiful — plain text output is acceptable for MVP. Line-wrapping at ~90 chars prevents text overflow.
- Story items with `title=None` should render as `"(untitled)"` placeholder, not crash.
- The HTML built for weasyprint should be self-contained (inline CSS, no external resources) to avoid weasyprint network calls.
- Confidence score: **9/10** — all patterns are directly mirrored from existing code; only new dependency is weasyprint/reportlab which are already installed.
