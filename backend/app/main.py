from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from app.api.v1.router import api_router
from app.core.config import get_settings
from app.core.logging import configure_logging, get_logger
from app.db.base import Base
from app.db.session import engine


configure_logging()
settings = get_settings()
logger = get_logger(__name__)

app = FastAPI(title=settings.app_name, debug=settings.app_debug)

app.add_middleware(
    CORSMiddleware,
    allow_origins=settings.cors_origins,
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

app.include_router(api_router, prefix=settings.api_v1_prefix)
app.include_router(api_router, prefix=settings.api_legacy_prefix)


@app.on_event("startup")
def on_startup() -> None:
    Base.metadata.create_all(bind=engine)
    logger.info("PulseRoute API started.")
