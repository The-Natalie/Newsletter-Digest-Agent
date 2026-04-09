# Feature: phase2-loop1-core-api

The following plan should be complete, but validate codebase patterns and task sanity before implementing.

Pay special attention to: router prefix structure, StaticFiles mount order (must come LAST), patch targets in tests (import location, not definition location), and the static/ directory existing before main.py is imported.

## Feature Description

Wrap the existing pipeline in FastAPI. Four new files: `main.py` (app factory), `api/health.py` (health check), `api/digests.py` (generate + latest routes), and `tests/test_api.py` (route tests). One supporting directory + placeholder: `api/__init__.py` and `static/index.html`. The pipeline (`build_digest`) and database (`digest_runs`, `async_session`) already exist and are not modified.

## User Story

As a developer
I want the digest pipeline exposed via HTTP endpoints
So that a browser frontend can trigger generation and retrieve the latest digest

## Problem Statement

The pipeline is fully functional as a CLI script but has no HTTP interface. Phase 2 adds a thin FastAPI wrapper — routes validate input, call the pipeline, and return results. No business logic in route handlers.

## Scope

- In scope: `main.py`, `api/__init__.py`, `api/health.py`, `api/digests.py`, `static/index.html` (placeholder), `tests/test_api.py`
- Out of scope: PDF export (`api/export.py` — Loop 2), frontend implementation (`static/app.js`, `static/style.css` — Loop 3), authentication, rate limiting

## Solution Statement

Create a FastAPI app in `main.py` that registers two routers (`/api` for health, `/api/digests` for digest endpoints) and mounts `static/` for frontend files. The generate route validates the request with a Pydantic model and calls `await build_digest(...)`. The latest route queries `digest_runs` for the most recent completed row and returns its `output_json`. Tests use `TestClient` with `unittest.mock` patches — no real IMAP or Claude calls.

## Feature Metadata

**Feature Type**: New Capability
**Estimated Complexity**: Low/Medium
**Primary Systems Affected**: `main.py`, `api/`, `tests/test_api.py`
**Dependencies**: FastAPI, uvicorn (already in requirements.txt); httpx 0.28.1 (already installed, required by TestClient)
**Assumptions**: `alembic upgrade head` has been run and `data/digest.db` exists before the server starts. `static/` dir must exist at startup or StaticFiles will crash.

---

## CONTEXT REFERENCES

### Relevant Codebase Files — IMPORTANT: YOU MUST READ THESE FILES BEFORE IMPLEMENTING!

- `processing/digest_builder.py` (lines 24–51, 128–165) — Why: `build_digest(folder, date_start, date_end) -> dict` signature and return shape: `{id, generated_at, folder, date_start, date_end, story_count, stories}`. Stories have `{title, body, link, links, newsletter, date, source_count}`. Raises on pipeline failure.
- `database.py` (lines 1–27) — Why: `async_session` is `async_sessionmaker[AsyncSession]`, `digest_runs` is the SQLAlchemy `Table`. Import pattern: `from database import async_session, digest_runs`. Query pattern: `await session.execute(digest_runs.select()...)`.
- `config.py` (lines 1–29) — Why: `settings.host`, `settings.port` for the uvicorn run block. `settings` is a module-level singleton.
- `tests/test_claude_client.py` (lines 1–10) — Why: sys.path insert pattern for test files: `sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))`.
- `PRD.md` (lines 538–628) — Why: Exact API spec. POST /api/digests/generate request/response shapes. GET /api/digests/latest response shape. Error format: `{"error": "message"}` (not FastAPI's default `{"detail": ...}`). GET /api/health returns `{"status": "ok"}`.

### New Files to Create

- `main.py` — FastAPI app factory, router registration, StaticFiles mount
- `api/__init__.py` — empty package marker
- `api/health.py` — GET /api/health router
- `api/digests.py` — POST /api/digests/generate and GET /api/digests/latest routers
- `static/index.html` — placeholder; prevents StaticFiles startup crash; replaced in Loop 3
- `tests/test_api.py` — 8 route tests using TestClient + mocking

### Relevant Documentation

- FastAPI routing: https://fastapi.tiangolo.com/tutorial/bigger-applications/
  - Why: APIRouter prefix/tag pattern, `include_router` call order
- FastAPI StaticFiles: https://fastapi.tiangolo.com/tutorial/static-files/
  - Why: Mount order requirement (static LAST), `html=True` for SPA fallback
- FastAPI TestClient: https://fastapi.tiangolo.com/tutorial/testing/
  - Why: `TestClient(app)` usage, async route testing

### Patterns to Follow

**Logging (from digest_builder.py:19–21):**
```python
import logging
logger = logging.getLogger(__name__)
```
Configure root logger in `main.py` with basicConfig (same format as digest_builder.py __main__ block).

**DB query pattern (from database.py + digest_builder.py:56–67, 152–162):**
```python
async with async_session() as session:
    await session.execute(digest_runs.insert().values(...))
    await session.commit()
```
For SELECT: `result = await session.execute(digest_runs.select().where(...).order_by(...).limit(1))` then `row = result.first()`.

**sys.path in tests (from tests/test_claude_client.py:3–5):**
```python
import sys, os
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
```

**Error response shape (from PRD.md §10):**
All non-2xx responses use `{"error": "message"}` at top level. Use `JSONResponse` directly (not `HTTPException`) to avoid FastAPI's default `{"detail": ...}` wrapping:
```python
from fastapi.responses import JSONResponse
return JSONResponse(status_code=500, content={"error": str(exc)})
```

**Router prefix convention:** health router included at prefix `/api`; digests router included at prefix `/api/digests`. Route decorators use relative paths: `@router.get("/health")`, `@router.post("/generate")`, `@router.get("/latest")`.

**StaticFiles mount order:** CRITICAL — include all routers before mounting static files. If StaticFiles is mounted first, it intercepts all `/api/...` requests as file lookups.

---

## IMPLEMENTATION PLAN

### Phase 1: Foundation — directories and package markers

Create the `api/` package and `static/` placeholder so the app can start.

### Phase 2: Core routes

Implement health, generate, and latest endpoints.

### Phase 3: App factory

Wire everything together in `main.py`.

### Phase 4: Tests

Write `tests/test_api.py` covering all routes and key error paths.

---

## STEP-BY-STEP TASKS

### Task 1: CREATE `api/__init__.py`

- **IMPLEMENT**: Empty file — marks `api/` as a Python package
- **VALIDATE**: `test -f "/Users/natalie/Documents/Agentic AI/Newsletter Digest Agent/api/__init__.py" && echo "EXISTS"`

---

### Task 2: CREATE `static/index.html`

- **IMPLEMENT**: Minimal HTML placeholder that will be replaced by the real frontend in Loop 3. Must exist so `StaticFiles(directory="static", html=True)` does not crash at app startup.
- **CONTENT**:
```html
<!DOCTYPE html>
<html lang="en">
<head><meta charset="UTF-8"><title>Newsletter Digest</title></head>
<body><p>Frontend coming in Phase 3.</p></body>
</html>
```
- **VALIDATE**: `test -f "/Users/natalie/Documents/Agentic AI/Newsletter Digest Agent/static/index.html" && echo "EXISTS"`

---

### Task 3: CREATE `api/health.py`

- **IMPLEMENT**: Single route `GET /health` returning `{"status": "ok"}`. Uses `APIRouter()` with no prefix (prefix applied in `main.py`).
- **IMPORTS**: `from fastapi import APIRouter`
- **CONTENT**:
```python
from __future__ import annotations

from fastapi import APIRouter

router = APIRouter()


@router.get("/health")
async def health_check() -> dict:
    return {"status": "ok"}
```
- **VALIDATE**: `cd "/Users/natalie/Documents/Agentic AI/Newsletter Digest Agent" && python -c "from api.health import router; print('health OK')"`

---

### Task 4: CREATE `api/digests.py`

- **IMPLEMENT**: Two routes. Pydantic `GenerateRequest` model with field validation. Imports `build_digest` from `processing.digest_builder` and `async_session`, `digest_runs` from `database` — these import locations are the patch targets in tests.
- **IMPORTS**: `from fastapi import APIRouter`, `from fastapi.responses import JSONResponse`, `from pydantic import BaseModel, field_validator, model_validator`, `from datetime import date`, `import json, logging`, `from database import async_session, digest_runs`, `from processing.digest_builder import build_digest`
- **GOTCHA**: Use `JSONResponse` for error responses (not `HTTPException`) to produce `{"error": "..."}` at top level, matching the PRD spec. FastAPI's `HTTPException` wraps detail in `{"detail": ...}`.
- **GOTCHA**: `@model_validator(mode="after")` requires pydantic v2. pydantic-settings 2.x installs pydantic v2 — confirmed in requirements.txt.
- **GOTCHA**: `build_digest` returns `date_start` and `date_end` as ISO strings (already converted in `digest_builder.py:144,146`). Return the dict directly — no post-processing needed.
- **CONTENT**:
```python
from __future__ import annotations

import json
import logging
from datetime import date

from fastapi import APIRouter
from fastapi.responses import JSONResponse
from pydantic import BaseModel, field_validator, model_validator

from database import async_session, digest_runs
from processing.digest_builder import build_digest

logger = logging.getLogger(__name__)

router = APIRouter()


class GenerateRequest(BaseModel):
    folder: str
    date_start: date
    date_end: date

    @field_validator("folder")
    @classmethod
    def folder_not_empty(cls, v: str) -> str:
        v = v.strip()
        if not v:
            raise ValueError("folder must not be empty")
        return v

    @model_validator(mode="after")
    def dates_in_order(self) -> "GenerateRequest":
        if self.date_start > self.date_end:
            raise ValueError("date_start must be on or before date_end")
        return self


@router.post("/generate")
async def generate_digest(request: GenerateRequest) -> dict:
    """Trigger digest generation. Runs synchronously; returns completed story list."""
    try:
        result = await build_digest(request.folder, request.date_start, request.date_end)
    except Exception as exc:
        logger.error("Digest generation failed: %s", exc)
        return JSONResponse(status_code=500, content={"error": str(exc)})
    return result


@router.get("/latest")
async def get_latest_digest() -> dict:
    """Return the most recently completed digest from the database."""
    async with async_session() as session:
        result = await session.execute(
            digest_runs.select()
            .where(digest_runs.c.status == "complete")
            .order_by(digest_runs.c.run_at.desc())
            .limit(1)
        )
        row = result.first()

    if row is None or not row.output_json:
        return JSONResponse(status_code=404, content={"error": "No completed digest found"})

    return json.loads(row.output_json)
```
- **VALIDATE**: `cd "/Users/natalie/Documents/Agentic AI/Newsletter Digest Agent" && python -c "from api.digests import router; print('digests OK')"`

---

### Task 5: CREATE `main.py`

- **IMPLEMENT**: FastAPI app factory. Registers health router at `/api`, digests router at `/api/digests`. Mounts `static/` LAST with `html=True`. Configures root logging. Includes a `__main__` block for `uvicorn.run`.
- **GOTCHA**: `app.mount("/", StaticFiles(...))` MUST come after all `app.include_router(...)` calls. If mounted first, the static file handler intercepts all `/api/...` paths as file lookups.
- **GOTCHA**: `static/` must exist before `StaticFiles(directory="static")` is called at module load time. Task 2 creates it. Do not add a runtime `os.makedirs` guard — rely on Task 2 having created the directory.
- **GOTCHA**: Do NOT run `alembic upgrade head` on startup. That is a deployment step run manually. The app assumes the DB is already initialized.
- **IMPORTS**: `from fastapi import FastAPI`, `from fastapi.staticfiles import StaticFiles`, `from api.health import router as health_router`, `from api.digests import router as digests_router`, `import logging, uvicorn`, `from config import settings`
- **CONTENT**:
```python
from __future__ import annotations

import logging

import uvicorn
from fastapi import FastAPI
from fastapi.staticfiles import StaticFiles

from api.digests import router as digests_router
from api.health import router as health_router
from config import settings

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s %(levelname)-8s %(name)s — %(message)s",
    datefmt="%H:%M:%S",
)

app = FastAPI(title="Newsletter Digest Agent")

# API routers — registered before static mount
app.include_router(health_router, prefix="/api")
app.include_router(digests_router, prefix="/api/digests")

# Static files — MUST be last; catches all remaining paths
app.mount("/", StaticFiles(directory="static", html=True), name="static")


if __name__ == "__main__":
    uvicorn.run("main:app", host=settings.host, port=settings.port, reload=True)
```
- **VALIDATE**: `cd "/Users/natalie/Documents/Agentic AI/Newsletter Digest Agent" && python -c "from main import app; print('app OK')"`

---

### Task 6: CREATE `tests/test_api.py`

- **IMPLEMENT**: 8 tests covering all routes and key error paths. Uses `TestClient(app)` from `fastapi.testclient`. Patches `api.digests.build_digest` and `api.digests.async_session` — the import location, not the definition location.
- **IMPORTS**: `from fastapi.testclient import TestClient`, `from main import app`, `from unittest.mock import AsyncMock, MagicMock, patch`, `import json`
- **GOTCHA**: Patch target for `build_digest` is `"api.digests.build_digest"` (where it is imported), not `"processing.digest_builder.build_digest"` (where it is defined).
- **GOTCHA**: Patch target for `async_session` is `"api.digests.async_session"`.
- **GOTCHA**: `async_session` is called as a context manager: `async with async_session() as session`. The mock must simulate this call chain. Use `patch("api.digests.async_session", return_value=mock_cm)` where `mock_cm` is an async context manager mock.
- **GOTCHA**: `TestClient` runs the ASGI app synchronously using `anyio`. It works with async routes without any special configuration. Do not add `asyncio_mode` markers.
- **CONTENT**:
```python
from __future__ import annotations

import json
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from unittest.mock import AsyncMock, MagicMock, patch

from fastapi.testclient import TestClient

from main import app

client = TestClient(app)


def test_health_returns_ok():
    """GET /api/health returns 200 {"status": "ok"}."""
    response = client.get("/api/health")
    assert response.status_code == 200
    assert response.json() == {"status": "ok"}


def test_generate_missing_folder_returns_422():
    """POST without required field returns 422."""
    response = client.post("/api/digests/generate", json={
        "date_start": "2026-04-01",
        "date_end": "2026-04-07",
    })
    assert response.status_code == 422


def test_generate_date_order_invalid_returns_422():
    """POST with date_start after date_end returns 422."""
    response = client.post("/api/digests/generate", json={
        "folder": "AI",
        "date_start": "2026-04-07",
        "date_end": "2026-04-01",
    })
    assert response.status_code == 422


def test_generate_empty_folder_returns_422():
    """POST with blank folder returns 422."""
    response = client.post("/api/digests/generate", json={
        "folder": "   ",
        "date_start": "2026-04-01",
        "date_end": "2026-04-07",
    })
    assert response.status_code == 422


def test_generate_valid_request_returns_200():
    """POST with valid body calls build_digest and returns its result."""
    mock_result = {
        "id": "test-uuid",
        "generated_at": "2026-04-08T00:00:00Z",
        "folder": "AI Newsletters",
        "date_start": "2026-04-01",
        "date_end": "2026-04-07",
        "story_count": 0,
        "stories": [],
    }
    with patch("api.digests.build_digest", new=AsyncMock(return_value=mock_result)):
        response = client.post("/api/digests/generate", json={
            "folder": "AI Newsletters",
            "date_start": "2026-04-01",
            "date_end": "2026-04-07",
        })
    assert response.status_code == 200
    data = response.json()
    assert data["folder"] == "AI Newsletters"
    assert "stories" in data


def test_generate_pipeline_error_returns_500():
    """POST where build_digest raises returns 500 {"error": ...}."""
    with patch("api.digests.build_digest", new=AsyncMock(side_effect=RuntimeError("IMAP failed"))):
        response = client.post("/api/digests/generate", json={
            "folder": "AI Newsletters",
            "date_start": "2026-04-01",
            "date_end": "2026-04-07",
        })
    assert response.status_code == 500
    assert "error" in response.json()


def test_latest_no_completed_digest_returns_404():
    """GET /api/digests/latest with no completed rows returns 404 {"error": ...}."""
    mock_result = MagicMock()
    mock_result.first.return_value = None
    mock_session = AsyncMock()
    mock_session.execute.return_value = mock_result
    mock_cm = MagicMock()
    mock_cm.__aenter__ = AsyncMock(return_value=mock_session)
    mock_cm.__aexit__ = AsyncMock(return_value=False)

    with patch("api.digests.async_session", return_value=mock_cm):
        response = client.get("/api/digests/latest")

    assert response.status_code == 404
    assert "error" in response.json()


def test_latest_returns_stored_output_json():
    """GET /api/digests/latest with a completed row returns its output_json."""
    stored = {
        "id": "abc123",
        "generated_at": "2026-04-08T00:00:00Z",
        "folder": "AI",
        "date_start": "2026-04-01",
        "date_end": "2026-04-07",
        "story_count": 1,
        "stories": [{
            "title": "Test Story",
            "body": "body text",
            "link": None,
            "newsletter": "TLDR",
            "date": "2026-04-01",
        }],
    }
    mock_row = MagicMock()
    mock_row.output_json = json.dumps(stored)
    mock_result = MagicMock()
    mock_result.first.return_value = mock_row
    mock_session = AsyncMock()
    mock_session.execute.return_value = mock_result
    mock_cm = MagicMock()
    mock_cm.__aenter__ = AsyncMock(return_value=mock_session)
    mock_cm.__aexit__ = AsyncMock(return_value=False)

    with patch("api.digests.async_session", return_value=mock_cm):
        response = client.get("/api/digests/latest")

    assert response.status_code == 200
    data = response.json()
    assert data["id"] == "abc123"
    assert len(data["stories"]) == 1
```
- **VALIDATE**: `cd "/Users/natalie/Documents/Agentic AI/Newsletter Digest Agent" && python -m pytest tests/test_api.py -v`

---

### Task 7: Run full test suite

- **VALIDATE**: `cd "/Users/natalie/Documents/Agentic AI/Newsletter Digest Agent" && python -m pytest tests/ -v`

---

### Task 8: Smoke-test the server starts

- **VALIDATE**: `cd "/Users/natalie/Documents/Agentic AI/Newsletter Digest Agent" && python -c "from main import app; from fastapi.testclient import TestClient; c = TestClient(app); r = c.get('/api/health'); assert r.status_code == 200; print('server smoke test OK')"`

---

## TESTING STRATEGY

### Unit Tests

8 tests in `tests/test_api.py` using `TestClient` + `unittest.mock`:
- Health endpoint: no mocking needed
- Generate endpoint: mock `api.digests.build_digest` (AsyncMock) to avoid real pipeline calls
- Latest endpoint: mock `api.digests.async_session` to avoid real DB calls

No new test infrastructure required. Existing `anyio` installation (already a pytest plugin) handles async route execution inside TestClient.

### Integration Tests

Manual validation via curl (see Level 4) after `uvicorn main:app --reload` is running.

### Edge Cases

- POST with whitespace-only folder → 422 (Pydantic field_validator strips then checks empty)
- POST with date_start == date_end → 200 (single-day range is valid)
- GET /api/digests/latest when row exists but output_json is None → 404
- Pipeline exception propagation → 500 with error message in body

---

## VALIDATION COMMANDS

### Level 1: Module import checks

```bash
cd "/Users/natalie/Documents/Agentic AI/Newsletter Digest Agent" && python -c "from api.health import router; print('health OK')"
cd "/Users/natalie/Documents/Agentic AI/Newsletter Digest Agent" && python -c "from api.digests import router; print('digests OK')"
cd "/Users/natalie/Documents/Agentic AI/Newsletter Digest Agent" && python -c "from main import app; print('app OK')"
```

### Level 2: New API tests

```bash
cd "/Users/natalie/Documents/Agentic AI/Newsletter Digest Agent" && python -m pytest tests/test_api.py -v
```

### Level 3: Full test suite (no regressions)

```bash
cd "/Users/natalie/Documents/Agentic AI/Newsletter Digest Agent" && python -m pytest tests/ -v
```

### Level 4: Manual smoke test via TestClient

```bash
cd "/Users/natalie/Documents/Agentic AI/Newsletter Digest Agent" && python -c "from main import app; from fastapi.testclient import TestClient; c = TestClient(app); r = c.get('/api/health'); assert r.status_code == 200; print('server smoke test OK')"
```

---

## MANUAL VERIFICATION CHECKLIST

- [ ] `api/__init__.py` exists
- [ ] `static/index.html` exists
- [ ] `api/health.py` exists with `GET /health` route on `router`
- [ ] `api/digests.py` exists with `POST /generate` and `GET /latest` routes on `router`
- [ ] `main.py` exists and imports cleanly
- [ ] `StaticFiles` mount is the last statement in `main.py` after `include_router` calls
- [ ] `GET /api/health` returns `{"status": "ok"}`
- [ ] `POST /api/digests/generate` with missing field returns 422
- [ ] `POST /api/digests/generate` with invalid date order returns 422
- [ ] `POST /api/digests/generate` with valid body and mocked pipeline returns 200
- [ ] `GET /api/digests/latest` with no DB row returns 404 with `{"error": ...}`
- [ ] `GET /api/digests/latest` with a completed row returns the stored JSON
- [ ] All 8 new tests pass
- [ ] Full suite still shows no regressions (114 existing + 8 new = 122 passing)

## ROLLBACK CONSIDERATIONS

- All changes are additive new files. To roll back: delete `main.py`, `api/`, `static/`, `tests/test_api.py`.
- No DB migrations, no schema changes, no modifications to existing files.

## ACCEPTANCE CRITERIA

- [ ] `GET /api/health` returns `200 {"status": "ok"}`
- [ ] `POST /api/digests/generate` with valid JSON body calls `build_digest` and returns its dict
- [ ] `POST /api/digests/generate` with invalid input returns 422
- [ ] `POST /api/digests/generate` when pipeline raises returns `500 {"error": "..."}`
- [ ] `GET /api/digests/latest` returns the most recent completed digest's `output_json`
- [ ] `GET /api/digests/latest` when no completed digest returns `404 {"error": "..."}`
- [ ] All 8 new tests pass; full suite has no regressions (122 total)
- [ ] `from main import app` imports cleanly with no errors
- [ ] `static/` directory exists and `StaticFiles` mount does not crash at startup

---

## COMPLETION CHECKLIST

- [ ] Task 1: `api/__init__.py` created
- [ ] Task 2: `static/index.html` created
- [ ] Task 3: `api/health.py` created and imports cleanly
- [ ] Task 4: `api/digests.py` created and imports cleanly
- [ ] Task 5: `main.py` created and imports cleanly
- [ ] Task 6: `tests/test_api.py` created; all 8 tests pass
- [ ] Task 7: Full suite passes (122 tests)
- [ ] Task 8: Smoke test passes

---

## NOTES

**Why JSONResponse for errors instead of HTTPException?**
FastAPI's `HTTPException` wraps detail as `{"detail": ...}`. The PRD specifies `{"error": "..."}` at the top level. Using `return JSONResponse(status_code=N, content={"error": "..."})` directly produces the correct shape without a custom exception handler.

**Why mock at import location (`api.digests.build_digest`) not definition (`processing.digest_builder.build_digest`)?**
Python's `unittest.mock.patch` replaces the name in the module where it is used, not where it is defined. If `api/digests.py` imports `from processing.digest_builder import build_digest`, the name `build_digest` is bound in `api.digests`. Patching `processing.digest_builder.build_digest` would not affect the already-imported name in `api.digests`.

**Why `static/index.html` is a placeholder?**
`StaticFiles(directory="static")` raises `RuntimeError` if the directory does not exist. The placeholder ensures the app starts cleanly in Phase 2. The real frontend (index.html, style.css, app.js) is implemented in Loop 3.

**`date_start == date_end` is valid.** The Pydantic validator uses `>` not `>=`. A single-day range is a legitimate request.

**`uvicorn main:app --reload` notes:** For development, `--reload` watches for file changes. The `main.py __main__` block also works: `python main.py`. Production deployments use the uvicorn command directly.

---

## VALIDATION OUTPUT REFERENCE

- Item to check:
  `cd "/Users/natalie/Documents/Agentic AI/Newsletter Digest Agent" && python -c "from api.health import router; print('health OK')"`
  Expected output or result:
  health OK

- Item to check:
  `cd "/Users/natalie/Documents/Agentic AI/Newsletter Digest Agent" && python -c "from api.digests import router; print('digests OK')"`
  Expected output or result:
  digests OK

- Item to check:
  `cd "/Users/natalie/Documents/Agentic AI/Newsletter Digest Agent" && python -c "from main import app; print('app OK')"`
  Expected output or result:
  app OK

- Item to check:
  `cd "/Users/natalie/Documents/Agentic AI/Newsletter Digest Agent" && python -m pytest tests/test_api.py -v`
  Expected output or result:
  ```
  ============================= test session starts ==============================
  platform darwin -- Python 3.12.x, pytest-9.x.x, pluggy-x.x.x
  ...
  tests/test_api.py::test_health_returns_ok PASSED
  tests/test_api.py::test_generate_missing_folder_returns_422 PASSED
  tests/test_api.py::test_generate_date_order_invalid_returns_422 PASSED
  tests/test_api.py::test_generate_empty_folder_returns_422 PASSED
  tests/test_api.py::test_generate_valid_request_returns_200 PASSED
  tests/test_api.py::test_generate_pipeline_error_returns_500 PASSED
  tests/test_api.py::test_latest_no_completed_digest_returns_404 PASSED
  tests/test_api.py::test_latest_returns_stored_output_json PASSED

  ============================== 8 passed in X.XXs ==============================
  ```

- Item to check:
  `cd "/Users/natalie/Documents/Agentic AI/Newsletter Digest Agent" && python -m pytest tests/ -v`
  Expected output or result:
  Final line: `122 passed` with no failures, no errors.

- Item to check:
  `cd "/Users/natalie/Documents/Agentic AI/Newsletter Digest Agent" && python -c "from main import app; from fastapi.testclient import TestClient; c = TestClient(app); r = c.get('/api/health'); assert r.status_code == 200; print('server smoke test OK')"`
  Expected output or result:
  server smoke test OK

- Item to check:
  `api/__init__.py` exists
  Expected output or result:
  File exists at `api/__init__.py` in project root.

- Item to check:
  `static/index.html` exists
  Expected output or result:
  File exists at `static/index.html` in project root.

- Item to check:
  `StaticFiles` mount is last in `main.py` after all `include_router` calls
  Expected output or result:
  Reading `main.py` shows `app.mount("/", StaticFiles(...), name="static")` appears after both `app.include_router(health_router, ...)` and `app.include_router(digests_router, ...)` lines.
