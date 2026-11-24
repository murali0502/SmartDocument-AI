from fastapi import APIRouter, Depends, Request, Response

from smartdoc.api.ingestion import require_local
from smartdoc.retrieval.contracts import SearchQuery, SearchResponse
from smartdoc.retrieval.service import RetrievalService

router = APIRouter(
    prefix="/api/v1/workspaces/local",
    tags=["retrieval"],
    dependencies=[Depends(require_local)],
)


@router.post("/search")
def search(query: SearchQuery, request: Request, response: Response) -> SearchResponse:
    response.headers["Cache-Control"] = "no-store"
    service: RetrievalService = request.app.state.retrieval
    return service.search(query)
