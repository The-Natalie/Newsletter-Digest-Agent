from __future__ import annotations

import logging
import logging.handlers
import os

import uvicorn
from alembic.config import Config as AlembicConfig
from alembic import command as alembic_command
from fastapi import FastAPI
from fastapi.staticfiles import StaticFiles

from api.digests import router as digests_router
from api.export import router as export_router
from api.health import router as health_router
from config import settings

os.makedirs("data", exist_ok=True)

# Run database migrations on startup so the volume is already mounted
_alembic_cfg = AlembicConfig("alembic.ini")
alembic_command.upgrade(_alembic_cfg, "head")
_fmt = logging.Formatter(
    "%(asctime)s %(levelname)-8s %(name)s — %(message)s",
    datefmt="%Y-%m-%d %H:%M:%S",
)
_file_handler = logging.handlers.RotatingFileHandler(
    "data/pipeline.log", maxBytes=5 * 1024 * 1024, backupCount=3, encoding="utf-8"
)
_file_handler.setFormatter(_fmt)
_console_handler = logging.StreamHandler()
_console_handler.setFormatter(
    logging.Formatter("%(asctime)s %(levelname)-8s %(name)s — %(message)s", datefmt="%H:%M:%S")
)
logging.basicConfig(level=logging.INFO, handlers=[_console_handler, _file_handler])

app = FastAPI(title="Newsletter Digest Agent")

# API routers — registered before static mount
app.include_router(health_router, prefix="/api")
app.include_router(digests_router, prefix="/api/digests")
app.include_router(export_router, prefix="/api/digests")

# Static files — MUST be last; catches all remaining paths
app.mount("/", StaticFiles(directory="static", html=True), name="static")


if __name__ == "__main__":
    uvicorn.run("main:app", host=settings.host, port=settings.port, reload=True)
