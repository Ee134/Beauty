"""FastAPI application factory."""

from __future__ import annotations

import contextlib
import logging
import uuid
from contextlib import asynccontextmanager
from pathlib import Path
from typing import Any

from fastapi import FastAPI, Request
from fastapi.exceptions import RequestValidationError
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse, JSONResponse
from fastapi.staticfiles import StaticFiles

from .api import (
    routes_admin,
    routes_cabinet,
    routes_chat,
    routes_environment,
    routes_identity,
    routes_ingredients,
    routes_memory,
    routes_notifications,
    routes_routine,
    routes_service,
)
from .config import REPO_ROOT, Settings, get_settings
from .db import session_scope
from .scheduler.loop import get_loop
from .services.errors import AppError

logger = logging.getLogger("beautycare")
logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s %(message)s")

FRONTEND_DIST = REPO_ROOT / "frontend" / "dist"


@asynccontextmanager
async def lifespan(app: FastAPI):
    settings: Settings = app.state.settings
    loop = None
    if settings.scheduler_enabled:
        loop = get_loop()
        loop.start()
        logger.info("scheduler enabled (interval=%ss)", settings.scheduler_interval_seconds)
    yield
    if loop is not None:
        await loop.stop()


def create_app(settings: Settings | None = None) -> FastAPI:
    settings = settings or get_settings()
    app = FastAPI(
        title=settings.app_name,
        version="1.2.0",
        description=(
            "BeautyCare MVP：已购产品 + 使用记忆 + 实时环境驱动的主动美妆服务。"
            "演示环境；mock 模式明示，真实接入点见 README。"
        ),
        lifespan=lifespan,
        docs_url="/docs",
        openapi_url="/openapi.json",
    )
    app.state.settings = settings
    app.add_middleware(
        CORSMiddleware,
        allow_origins=settings.cors_origin_list,
        allow_credentials=True,
        allow_methods=["*"],
        allow_headers=["*"],
        expose_headers=["X-Run-Id"],
    )

    @app.middleware("http")
    async def run_id_middleware(request: Request, call_next):  # type: ignore[no-untyped-def]
        run_id = request.headers.get("X-Run-Id") or str(uuid.uuid4())
        request.state.run_id = run_id
        response = await call_next(request)
        response.headers["X-Run-Id"] = run_id
        response.headers["X-BeautyCare-Mode"] = (
            f"model={settings.model_mode};weather={settings.weather_mode};"
            f"notification={settings.notification_mode};env={settings.app_env}"
        )
        return response

    @app.exception_handler(AppError)
    async def app_error_handler(request: Request, exc: AppError) -> JSONResponse:
        return JSONResponse(
            status_code=exc.status_code,
            content=exc.to_body(getattr(request.state, "run_id", None)),
        )

    @app.exception_handler(RequestValidationError)
    async def validation_handler(request: Request, exc: RequestValidationError) -> JSONResponse:
        return JSONResponse(
            status_code=422,
            content={
                "code": "VALIDATION_ERROR",
                "message": "请求参数不合法",
                "retryable": False,
                "details": {"errors": exc.errors()[:5]},
                "run_id": getattr(request.state, "run_id", None),
            },
        )

    @app.exception_handler(Exception)
    async def unhandled_handler(request: Request, exc: Exception) -> JSONResponse:
        logger.exception("unhandled error: %s", type(exc).__name__)
        return JSONResponse(
            status_code=500,
            content={
                "code": "INTERNAL_ERROR",
                "message": "服务端内部错误，未写入任何未确认的业务变更。",
                "retryable": True,
                "details": {"error": type(exc).__name__},
                "run_id": getattr(request.state, "run_id", None),
            },
        )

    for router in (
        routes_identity.router,
        routes_cabinet.router,
        routes_routine.router,
        routes_chat.router,
        routes_memory.router,
        routes_ingredients.router,
        routes_service.router,
        routes_environment.router,
        routes_notifications.router,
        routes_admin.router,
    ):
        app.include_router(router, prefix=settings.api_prefix)

    _mount_frontend(app)
    return app


def _mount_frontend(app: FastAPI) -> None:
    """Serve the built PWA when it exists (single origin, no second server needed)."""
    if not FRONTEND_DIST.exists():
        @app.get("/")
        def placeholder() -> dict[str, Any]:
            return {
                "app": "BeautyCare MVP",
                "frontend_built": False,
                "message": "前端尚未构建。请在 frontend/ 运行 pnpm install && pnpm build，或使用 pnpm dev 开发服务器。",
                "api_prefix": "/api/v1",
                "docs": "/docs",
            }

        return

    assets = FRONTEND_DIST / "assets"
    if assets.exists():
        app.mount("/assets", StaticFiles(directory=assets), name="assets")

    @app.get("/manifest.webmanifest")
    def manifest() -> FileResponse:
        return FileResponse(FRONTEND_DIST / "manifest.webmanifest")

    @app.get("/sw.js")
    def service_worker() -> FileResponse:
        return FileResponse(FRONTEND_DIST / "sw.js", media_type="application/javascript")

    @app.get("/icons/{name}")
    def icons(name: str) -> FileResponse:
        safe = Path(name).name
        return FileResponse(FRONTEND_DIST / "icons" / safe)

    @app.get("/")
    def index() -> FileResponse:
        return FileResponse(FRONTEND_DIST / "index.html")

    @app.get("/{full_path:path}")
    def spa(full_path: str) -> FileResponse:
        candidate = FRONTEND_DIST / full_path
        if candidate.is_file():
            return FileResponse(candidate)
        return FileResponse(FRONTEND_DIST / "index.html")


app = create_app()


def main() -> None:
    import uvicorn

    settings = get_settings()
    uvicorn.run(
        "app.main:app",
        host="127.0.0.1",
        port=8000,
        reload=False,
        log_level="info",
    )


if __name__ == "__main__":
    main()
