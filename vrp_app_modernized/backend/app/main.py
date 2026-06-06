from fastapi import FastAPI, Request
from fastapi.exceptions import RequestValidationError
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse

from app.api.v1.router import api_router
from app.core.config import get_settings
from app.core.logging import configure_logging, get_logger
from app.db.base import Base
from app.db.migrations import ensure_sqlite_compat_columns
from app.db.session import engine


configure_logging()
settings = get_settings()
logger = get_logger(__name__)

app = FastAPI(title=settings.app_name, debug=settings.app_debug)

app.add_middleware(
    CORSMiddleware,
    allow_origins=settings.cors_origins,
    allow_origin_regex=settings.cors_origin_regex,
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

app.include_router(api_router, prefix=settings.api_v1_prefix)
app.include_router(api_router, prefix=settings.api_legacy_prefix)


@app.on_event("startup")
def on_startup() -> None:
    Base.metadata.create_all(bind=engine)
    ensure_sqlite_compat_columns(engine)
    logger.info("PulseRoute API started.")


@app.exception_handler(RequestValidationError)
async def handle_validation_error(request: Request, exc: RequestValidationError) -> JSONResponse:
    logger.warning("Request validation failed", extra={"path": str(request.url.path), "errors": exc.errors()})
    return JSONResponse(
        status_code=422,
        content={
            "detail": "Request validation failed.",
            "error_type": "validation_error",
            "path": str(request.url.path),
            "errors": exc.errors(),
        },
    )


@app.exception_handler(Exception)
async def handle_unexpected_error(request: Request, exc: Exception) -> JSONResponse:
    logger.exception("Unhandled backend error at %s", request.url.path, exc_info=exc)
    return JSONResponse(
        status_code=500,
        content={
            "detail": str(exc) or "Internal server error.",
            "error_type": "internal_server_error",
            "path": str(request.url.path),
        },
    )
