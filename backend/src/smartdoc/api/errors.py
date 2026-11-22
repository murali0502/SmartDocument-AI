from http import HTTPStatus

from fastapi import Request
from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse
from starlette.exceptions import HTTPException


def problem(
    request: Request,
    status: int,
    code: str,
    detail: str,
    headers: dict[str, str] | None = None,
) -> JSONResponse:
    title = HTTPStatus(status).phrase if status in HTTPStatus else "Request failed"
    return JSONResponse(
        status_code=status,
        media_type="application/problem+json",
        headers=headers,
        content={
            "type": "about:blank",
            "title": title,
            "status": status,
            "code": code,
            "detail": detail,
            "request_id": request.state.request_id,
        },
    )


async def http_error(request: Request, error: HTTPException) -> JSONResponse:
    return problem(
        request,
        error.status_code,
        f"http_{error.status_code}",
        "The request could not be completed.",
        error.headers,
    )


async def validation_error(request: Request, _error: RequestValidationError) -> JSONResponse:
    return problem(request, 422, "invalid_request", "The request failed validation.")
