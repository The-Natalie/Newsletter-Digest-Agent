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
