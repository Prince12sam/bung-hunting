import logging

from fastapi import FastAPI

from api.routes.scan import router as scan_router
from api.routes.tasks import router as tasks_router
from memory.db import init_db

logger = logging.getLogger("es.api")

app = FastAPI(title="Scorpion Agent Core", version="2.0.0")
app.include_router(tasks_router)
app.include_router(scan_router)


@app.on_event("startup")
def _startup() -> None:
    try:
        init_db()
    except Exception as exc:  # noqa: BLE001
        logger.warning("Memory (Postgres) unavailable at startup: %s", exc)


@app.get("/healthz")
def healthz() -> dict:
    return {"status": "ok"}
