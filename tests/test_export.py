from __future__ import annotations

import json
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from io import BytesIO
from unittest.mock import AsyncMock, MagicMock, patch

from fastapi.testclient import TestClient

from api.export import _render_pdf
from main import app

client = TestClient(app)

_STORED = {
    "id": "test-uuid",
    "generated_at": "2026-04-08T00:00:00Z",
    "folder": "AI Newsletters",
    "date_start": "2026-04-01",
    "date_end": "2026-04-07",
    "story_count": 1,
    "stories": [
        {
            "title": "Test Story",
            "body": "body text",
            "link": "https://example.com",
            "newsletter": "TLDR",
            "date": "2026-04-01",
        }
    ],
}


def _make_mock_session(row):
    """Build the async_session context-manager mock returning the given row."""
    mock_result = MagicMock()
    mock_result.first.return_value = row
    mock_session = AsyncMock()
    mock_session.execute.return_value = mock_result
    mock_cm = MagicMock()
    mock_cm.__aenter__ = AsyncMock(return_value=mock_session)
    mock_cm.__aexit__ = AsyncMock(return_value=False)
    return mock_cm


def test_pdf_returns_200_weasyprint():
    """GET /api/digests/{id}/pdf returns 200 PDF when rendering succeeds."""
    mock_row = MagicMock()
    mock_row.output_json = json.dumps(_STORED)
    mock_cm = _make_mock_session(mock_row)

    with patch("api.export.async_session", return_value=mock_cm), \
         patch("api.export._render_pdf", return_value=b"%PDF-fake"):
        response = client.get("/api/digests/test-uuid/pdf")

    assert response.status_code == 200
    assert response.headers["content-type"] == "application/pdf"
    assert "digest-" in response.headers["content-disposition"]
    assert "attachment" in response.headers["content-disposition"]


def test_pdf_fallback_reportlab():
    """Route still returns 200 when _render_pdf uses the reportlab fallback."""
    mock_row = MagicMock()
    mock_row.output_json = json.dumps(_STORED)
    mock_cm = _make_mock_session(mock_row)

    with patch("api.export.async_session", return_value=mock_cm), \
         patch("api.export._render_pdf", return_value=b"%PDF-reportlab"):
        response = client.get("/api/digests/test-uuid/pdf")

    assert response.status_code == 200
    assert response.headers["content-type"] == "application/pdf"


def test_pdf_no_row_returns_404():
    """GET with unknown digest ID returns 404 {\"error\": ...}."""
    mock_cm = _make_mock_session(None)

    with patch("api.export.async_session", return_value=mock_cm):
        response = client.get("/api/digests/nonexistent/pdf")

    assert response.status_code == 404
    assert "error" in response.json()


def test_pdf_no_output_json_returns_404():
    """GET when output_json is None returns 404 {\"error\": ...}."""
    mock_row = MagicMock()
    mock_row.output_json = None
    mock_cm = _make_mock_session(mock_row)

    with patch("api.export.async_session", return_value=mock_cm):
        response = client.get("/api/digests/test-uuid/pdf")

    assert response.status_code == 404
    assert "error" in response.json()


def test_pdf_render_error_returns_500():
    """GET returns 500 {\"error\": ...} when _render_pdf raises."""
    mock_row = MagicMock()
    mock_row.output_json = json.dumps(_STORED)
    mock_cm = _make_mock_session(mock_row)

    with patch("api.export.async_session", return_value=mock_cm), \
         patch("api.export._render_pdf", side_effect=RuntimeError("both renderers failed")):
        response = client.get("/api/digests/test-uuid/pdf")

    assert response.status_code == 500
    assert "error" in response.json()


def test_render_pdf_uses_weasyprint():
    """_render_pdf returns bytes from weasyprint.HTML().write_pdf()."""
    mock_html_instance = MagicMock()
    mock_html_instance.write_pdf.return_value = b"pdf-bytes"
    mock_weasyprint = MagicMock()
    mock_weasyprint.HTML.return_value = mock_html_instance

    # Inject a fake weasyprint module so the `from weasyprint import HTML`
    # inside _render_pdf doesn't trigger loading the real (system-dep) library.
    with patch.dict(sys.modules, {"weasyprint": mock_weasyprint}):
        result = _render_pdf(_STORED)

    assert result == b"pdf-bytes"
    mock_weasyprint.HTML.assert_called_once()


def test_render_pdf_falls_back_to_reportlab():
    """_render_pdf calls _render_reportlab when weasyprint raises."""
    mock_weasyprint = MagicMock()
    mock_weasyprint.HTML.side_effect = Exception("no weasyprint")

    with patch.dict(sys.modules, {"weasyprint": mock_weasyprint}), \
         patch("api.export._render_reportlab", return_value=b"%PDF-reportlab") as mock_rl:
        result = _render_pdf(_STORED)

    assert result == b"%PDF-reportlab"
    mock_rl.assert_called_once_with(_STORED)
