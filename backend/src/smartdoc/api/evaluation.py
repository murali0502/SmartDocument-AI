from pathlib import Path

from fastapi import APIRouter, Depends, Response
from pydantic import BaseModel

from smartdoc.api.ingestion import require_local

router = APIRouter(
    prefix="/api/v1/workspaces/local",
    tags=["evaluation"],
    dependencies=[Depends(require_local)],
)


class RetrievalMetrics(BaseModel):
    chunks: int
    mrr_at_5: float
    recall_at_5: float
    p50_ms: float
    p95_ms: float


class EvaluationReport(BaseModel):
    documents: int
    queries: int
    peak_rss_mib_linux: float
    variants: dict[str, RetrievalMetrics]


@router.get("/evaluation")
def report(response: Response) -> EvaluationReport:
    response.headers["Cache-Control"] = "no-store"
    path = Path(__file__).parents[1] / "evaluation" / "retrieval.json"
    return EvaluationReport.model_validate_json(path.read_bytes())
