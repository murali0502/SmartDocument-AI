"""Serve the browser app and a password-protected shared workspace over HTTPS."""

import os
from base64 import b64encode
from collections.abc import Awaitable, Callable
from pathlib import Path
from secrets import compare_digest
from urllib.parse import urlsplit

import uvicorn
from alembic import command
from alembic.config import Config
from fastapi import FastAPI, Request, Response
from fastapi.middleware.cors import CORSMiddleware
from fastapi.openapi.docs import get_swagger_ui_html
from fastapi.staticfiles import StaticFiles

from smartdoc.app import create_app
from smartdoc.config import MIGRATIONS_DIR, Settings
from smartdoc.logging import logging_config


def create_hosted_app(
    settings: Settings,
    frontend_dir: Path,
    password: str,
    public_domain: str | None,
    *,
    frontend_origin: str | None = None,
) -> FastAPI:
    if len(password) < 24 or not password.isascii():
        raise ValueError("SMARTDOC_HOSTED_PASSWORD requires at least 24 ASCII characters.")
    if frontend_origin:
        address = urlsplit(frontend_origin)
        if (
            address.scheme != "https"
            or not address.hostname
            or address.username is not None
            or address.path
            or address.query
            or address.fragment
        ):
            raise ValueError("SMARTDOC_FRONTEND_ORIGIN must be an HTTPS origin.")
    credentials = b64encode(f"smartdoc:{password}".encode("ascii"))
    app = create_app(settings, docs_url=None)

    @app.get("/api/v1/docs", include_in_schema=False)
    def api_workspace() -> Response:
        return get_swagger_ui_html(
            openapi_url="/api/v1/openapi.json",
            title="SmartDoc AI API workspace",
            swagger_js_url="/swagger/swagger-ui-bundle.js",
            swagger_css_url="/swagger/swagger-ui.css",
            swagger_favicon_url="/swagger/favicon-32x32.png",
        )

    app.mount("/", StaticFiles(directory=frontend_dir, html=True), name="frontend")

    @app.middleware("http")
    async def protect_workspace(
        request: Request, call_next: Callable[[Request], Awaitable[Response]]
    ) -> Response:
        if request.method == "GET" and request.url.path == "/api/v1/health/ready":
            return await call_next(request)

        scheme, _, token = request.headers.get("authorization", "").partition(" ")
        if scheme.lower() != "basic" or not compare_digest(token.encode("utf-8"), credentials):
            return Response(
                status_code=401,
                headers={
                    "WWW-Authenticate": 'Basic realm="SmartDoc AI", charset="UTF-8"',
                    "Cache-Control": "no-store",
                },
            )

        if request.method not in {"GET", "HEAD", "OPTIONS"}:
            origin = request.headers.get("origin")
            expected_origin = (
                f"https://{public_domain}"
                if public_domain
                else f"{request.url.scheme}://{request.url.netloc}"
            )
            approved_frontend = frontend_origin is not None and origin == frontend_origin
            if not approved_frontend and (
                (origin is not None and origin != expected_origin)
                or request.headers.get("sec-fetch-site", "none") not in {"same-origin", "none"}
            ):
                return Response(status_code=403, headers={"Cache-Control": "no-store"})

        request.state.hosted_workspace_authenticated = True
        response = await call_next(request)
        response.headers["Cache-Control"] = "private, no-store"
        return response

    @app.middleware("http")
    async def add_workspace_headers(
        request: Request, call_next: Callable[[Request], Awaitable[Response]]
    ) -> Response:
        response = await call_next(request)
        response.headers["X-Content-Type-Options"] = "nosniff"
        response.headers["Referrer-Policy"] = "no-referrer"
        response.headers["X-Frame-Options"] = "DENY"
        response.headers["Content-Security-Policy"] = (
            "frame-ancestors 'none'; object-src 'none'; base-uri 'self'"
        )
        return response

    if frontend_origin:
        app.add_middleware(
            CORSMiddleware,
            allow_origins=[frontend_origin],
            allow_methods=["GET", "POST", "HEAD"],
            allow_headers=[
                "Authorization",
                "Content-Type",
                "X-SmartDoc-Upload",
                "X-SmartDoc-Local",
            ],
            expose_headers=["Content-Disposition", "X-Request-ID"],
        )
    return app


def main() -> None:
    settings = Settings(port=int(os.environ.get("PORT", "8000")))
    public_domain = os.environ.get("RAILWAY_PUBLIC_DOMAIN")
    if os.environ.get("RAILWAY_ENVIRONMENT_ID"):
        mounts = Path("/proc/self/mountinfo").read_text().splitlines()
        if not any(line.split()[4] == "/data" for line in mounts):
            raise RuntimeError("The Railway persistent volume must be mounted at /data.")
    app = create_hosted_app(
        settings,
        Path(os.environ["SMARTDOC_FRONTEND_DIR"]),
        os.environ["SMARTDOC_HOSTED_PASSWORD"],
        public_domain,
        frontend_origin=os.environ.get("SMARTDOC_FRONTEND_ORIGIN"),
    )
    migrations = Config()
    migrations.set_main_option("script_location", str(MIGRATIONS_DIR))
    command.upgrade(migrations, "head")
    uvicorn.run(
        app,
        host=settings.host,
        port=settings.port,
        log_config=logging_config(settings.log_level),
        access_log=False,
        proxy_headers=False,
    )


if __name__ == "__main__":
    main()
