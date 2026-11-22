from datetime import UTC, datetime
from typing import Literal

from fastapi import APIRouter, Request, Response
from pydantic import BaseModel

from smartdoc.persistence.readiness import DatabaseReadiness, DatabaseStatus

router = APIRouter(prefix="/api/v1/health", tags=["health"])


class Liveness(BaseModel):
    status: Literal["alive"] = "alive"


class Readiness(BaseModel):
    status: Literal["ready", "unavailable"]
    database: DatabaseStatus
    checked_at: datetime


@router.get("/live")
def live(response: Response) -> Liveness:
    response.headers["Cache-Control"] = "no-store"
    return Liveness()


@router.get(
    "/ready",
    responses={503: {"model": Readiness, "description": "A database readiness check failed."}},
)
def ready(request: Request, response: Response) -> Readiness:
    database: DatabaseReadiness = request.app.state.database_readiness
    database_status = database.check()
    is_ready = database_status == "ready"
    response.status_code = 200 if is_ready else 503
    response.headers["Cache-Control"] = "no-store"
    return Readiness(
        status="ready" if is_ready else "unavailable",
        database=database_status,
        checked_at=datetime.now(UTC),
    )
