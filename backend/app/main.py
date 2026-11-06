import logging
import time
import uuid
from pathlib import Path

from fastapi import FastAPI, Request
from fastapi.exceptions import RequestValidationError
from fastapi.responses import FileResponse, JSONResponse
from fastapi.staticfiles import StaticFiles
from sqlalchemy.exc import DataError, StatementError
from starlette.exceptions import HTTPException as StarletteHTTPException

from app.analytics.router import router as summary_router
from app.areas.router import router as areas_router
from app.assistant.router import router as assistant_router
from app.auth.router import router as account_router
from app.captures.router import router as captures_router
from app.config import get_settings
from app.db import all_models  # noqa: F401  (registers models before first query)
from app.errors import AppError
from app.events.router import router as events_router
from app.goals.router import router as goals_router
from app.habits.router import router as habits_router
from app.knowledge.router import router as knowledge_router
from app.logging_setup import configure_logging, request_id_var
from app.projects.router import router as projects_router
from app.tasks.router import router as tasks_router

logger = logging.getLogger("app")
FRONTEND_DIST = Path(__file__).resolve().parents[2] / "frontend" / "dist"


def _error(status: int, code: str, message: str, details: object = None) -> JSONResponse:
    body: dict = {"error": {"code": code, "message": message}}
    if details is not None:
        body["error"]["details"] = details
    return JSONResponse(status_code=status, content=body)


def create_app() -> FastAPI:
    settings = get_settings()
    configure_logging(settings.log_level)
    hide_docs = settings.is_production
    app = FastAPI(
        title="Personal OS",
        version="0.1.0",
        description="Tell the system what happened; it structures, connects and measures it.",
        # A public deployment shouldn't advertise its whole API surface.
        docs_url=None if hide_docs else "/docs",
        redoc_url=None if hide_docs else "/redoc",
        openapi_url=None if hide_docs else "/openapi.json",
    )

    @app.middleware("http")
    async def request_context(request: Request, call_next):
        request_id = request.headers.get("x-request-id") or uuid.uuid4().hex[:12]
        token = request_id_var.set(request_id)
        started = time.perf_counter()
        try:
            response = await call_next(request)
        finally:
            request_id_var.reset(token)
        response.headers["x-request-id"] = request_id
        if request.url.path.startswith("/v1"):
            logger.info(
                "%s %s -> %s (%.0f ms) [%s]",
                request.method,
                request.url.path,
                response.status_code,
                (time.perf_counter() - started) * 1000,
                request_id,
            )
        return response

    @app.exception_handler(AppError)
    async def app_error(_: Request, exc: AppError) -> JSONResponse:
        return _error(exc.status_code, exc.code, exc.message, exc.details)

    @app.exception_handler(RequestValidationError)
    async def validation_error(_: Request, exc: RequestValidationError) -> JSONResponse:
        details = [
            {"field": ".".join(str(part) for part in err["loc"][1:]), "message": err["msg"]}
            for err in exc.errors()
        ]
        return _error(422, "VALIDATION_FAILED", "Some fields are invalid.", details)

    @app.exception_handler(StarletteHTTPException)
    async def http_error(_: Request, exc: StarletteHTTPException) -> JSONResponse:
        code = {404: "NOT_FOUND", 405: "METHOD_NOT_ALLOWED"}.get(exc.status_code, "HTTP_ERROR")
        return _error(exc.status_code, code, str(exc.detail))

    @app.exception_handler(DataError)
    async def bad_data(_: Request, exc: DataError) -> JSONResponse:
        # Values PostgreSQL refuses to store (a number out of range, say) are the client's error.
        logger.info("Rejected data: %s", type(exc.orig).__name__)
        return _error(422, "VALIDATION_FAILED", "Some values are out of range or invalid.")

    @app.exception_handler(StatementError)
    async def bad_statement(request: Request, exc: StatementError) -> JSONResponse:
        if isinstance(exc.orig, ValueError) and "NUL" in str(exc.orig):
            return _error(422, "VALIDATION_FAILED", "Text can't contain NUL characters.")
        return await unexpected(request, exc)

    @app.exception_handler(Exception)
    async def unexpected(_: Request, exc: Exception) -> JSONResponse:
        logger.exception("Unhandled error", exc_info=exc)
        return _error(500, "INTERNAL_ERROR", "Something went wrong on our side.")

    for router in (
        account_router,
        captures_router,
        events_router,
        projects_router,
        goals_router,
        tasks_router,
        habits_router,
        knowledge_router,
        areas_router,
        summary_router,
        assistant_router,
    ):
        app.include_router(router)

    @app.get("/health", tags=["system"])
    def health() -> dict:
        return {"status": "ok", "ai_provider": settings.ai_provider}

    if FRONTEND_DIST.is_dir():
        assets = FRONTEND_DIST / "assets"
        if assets.is_dir():
            app.mount("/assets", StaticFiles(directory=assets), name="assets")

        @app.get("/{path:path}", include_in_schema=False)
        def frontend(path: str) -> FileResponse:
            if path == "v1" or path.startswith("v1/"):
                # An unknown API path is a 404 the client can read, not the web app's page.
                raise StarletteHTTPException(status_code=404, detail="Not found.")
            candidate = (FRONTEND_DIST / path).resolve()
            if path and candidate.is_file() and FRONTEND_DIST in candidate.parents:
                return FileResponse(candidate)
            return FileResponse(FRONTEND_DIST / "index.html")

    return app


app = create_app()
