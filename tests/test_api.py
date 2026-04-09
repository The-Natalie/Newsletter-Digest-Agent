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
