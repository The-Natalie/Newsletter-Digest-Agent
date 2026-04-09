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
