import asyncio
import logging
from collections.abc import AsyncIterator, Awaitable, Callable
from contextlib import asynccontextmanager
from importlib.metadata import version
from threading import Event
from time import perf_counter
from uuid import uuid4

from fastapi import FastAPI, Request, Response
from fastapi.exceptions import RequestValidationError
from starlette.exceptions import HTTPException

from smartdoc.api.errors import http_error, problem, validation_error
from smartdoc.api.health import router
from smartdoc.api.ingestion import ingestion_error
from smartdoc.api.ingestion import router as ingestion_router
from smartdoc.api.nlp import router as nlp_router
from smartdoc.api.structure import router as structure_router
from smartdoc.config import MIGRATIONS_DIR, Settings
from smartdoc.ingestion.contracts import ExtractionError
from smartdoc.ingestion.worker import IngestionWorker
from smartdoc.nlp.inference import LocalInference
from smartdoc.nlp.pipeline import LanguagePipeline
from smartdoc.persistence.database import create_database_engine
from smartdoc.persistence.ingestion_store import IngestionStore
from smartdoc.persistence.nlp_store import NlpStore
from smartdoc.persistence.readiness import DatabaseReadiness
from smartdoc.persistence.structure_store import StructureStore

logger = logging.getLogger(__name__)


def create_app(settings: Settings | None = None) -> FastAPI:
    settings = settings or Settings()
    path = settings.database_path.resolve()
    engine = create_database_engine(path, read_only=True)
    readiness = DatabaseReadiness(path, engine, MIGRATIONS_DIR)
    storage = settings.storage_path or path.parent / f"{path.name}.storage"
    writer = create_database_engine(path)
    store = IngestionStore(writer, storage.resolve())
    structures = StructureStore(writer)
    models = settings.nlp_model_dir.resolve()
    pipeline = LanguagePipeline(settings.nlp_profile, models, settings.nlp_terms)
    annotations = NlpStore(writer, pipeline)
    worker = IngestionWorker(
        store,
        readiness,
        settings.processing_timeout,
        structures=structures,
        annotations=annotations,
    )

    @asynccontextmanager
    async def lifespan(_app: FastAPI) -> AsyncIterator[None]:
        stop = Event()
        task = (
            asyncio.create_task(asyncio.to_thread(worker.run_until_stopped, stop))
            if settings.ingestion_worker
            else None
        )
        try:
            yield
        finally:
            stop.set()
            try:
                if task is not None:
                    await task
            finally:
                writer.dispose()
                engine.dispose()

    app = FastAPI(
        title="SmartDoc AI",
        version=version("smartdoc-ai"),
        docs_url="/api/v1/docs",
        openapi_url="/api/v1/openapi.json",
        redoc_url=None,
        lifespan=lifespan,
    )
    app.state.database_readiness = readiness
    app.state.ingestion_store = store
    app.state.structure_store = structures
    app.state.nlp_store = annotations
    app.state.local_inference = LocalInference(models)
    app.state.settings = settings
    app.add_exception_handler(ExtractionError, ingestion_error)
    app.add_exception_handler(HTTPException, http_error)
    app.add_exception_handler(RequestValidationError, validation_error)
    app.include_router(router)
    app.include_router(ingestion_router)
    app.include_router(structure_router)
    app.include_router(nlp_router)

    @app.middleware("http")
    async def correlate_request(
        request: Request, call_next: Callable[[Request], Awaitable[Response]]
    ) -> Response:
        request_id = str(uuid4())
        request.state.request_id = request_id
        started_at = perf_counter()
        error_type = None
        try:
            response = await call_next(request)
        except Exception as error:
            error_type = type(error).__name__
            response = problem(request, 500, "internal_error", "An unexpected error occurred.")

        response.headers["X-Request-ID"] = request_id
        status = response.status_code
        log_level = logging.INFO
        if error_type:
            log_level = logging.ERROR
        elif status >= 500:
            log_level = logging.WARNING
        logger.log(
            log_level,
            "request_completed",
            extra={
                "request_id": request_id,
                "method": request.method,
                "route": getattr(request.scope.get("route"), "path", None),
                "status": status,
                "duration_ms": round((perf_counter() - started_at) * 1000, 2),
                "error_type": error_type,
            },
        )
        return response

    return app
