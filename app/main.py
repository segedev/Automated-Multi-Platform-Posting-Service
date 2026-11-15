"""FastAPI application entrypoint exposing POST /posting on port 4000."""

from contextlib import asynccontextmanager
import logging
from typing import AsyncIterator

from fastapi import Depends, FastAPI, Request, status
from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse
import httpx

from app.config import Settings, get_settings
from app.platforms import build_platform_registry
from app.schemas import PostingRequest, PostingResponse
from app.services.posting_service import PostingService

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s | %(levelname)-8s | %(name)s | %(message)s",
)
logger = logging.getLogger(__name__)


@asynccontextmanager
async def lifespan(app: FastAPI) -> AsyncIterator[None]:
    """Create and cleanly close a shared httpx.AsyncClient across application lifecycle."""
    settings = get_settings()
    limits = httpx.Limits(max_keepalive_connections=20, max_connections=50)
    async with httpx.AsyncClient(
        limits=limits,
        headers={"User-Agent": "AutomatedMultiPlatformPoster/1.0"},
    ) as client:
        app.state.http_client = client
        logger.info(
            "Startup complete. Initialized shared AsyncClient with %d platform adapters.",
            len(build_platform_registry(settings)),
        )
        yield
        logger.info("Shutting down shared AsyncClient.")


app = FastAPI(
    title="Automated Multi-Platform Posting API",
    description=(
        "Publishes a short announcement message (<= 200 chars) containing exactly one "
        "valid HTTP/HTTPS CTA link to 7 third-party platforms concurrently."
    ),
    version="1.0.0",
    lifespan=lifespan,
)


@app.exception_handler(RequestValidationError)
async def validation_exception_handler(
    request: Request,
    exc: RequestValidationError,
) -> JSONResponse:
    """Return a clean, consistent 422 JSON error payload when validation fails."""
    messages: list[str] = []
    for err in exc.errors():
        msg = err.get("msg", "Invalid input")
        if msg.startswith("Value error, "):
            msg = msg[len("Value error, ") :]
        messages.append(msg)

    return JSONResponse(
        status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
        content={
            "success": False,
            "error": "Validation error",
            "details": messages,
        },
    )


def get_posting_service(
    settings: Settings = Depends(get_settings),
) -> PostingService:
    """Dependency provider constructing PostingService with all registered adapters."""
    adapters = build_platform_registry(settings)
    return PostingService(adapters=adapters, settings=settings)


@app.post(
    "/posting",
    response_model=PostingResponse,
    status_code=status.HTTP_200_OK,
    summary="Publish a short message with one CTA link to all configured platforms",
)
async def create_posting(
    payload: PostingRequest,
    request: Request,
    service: PostingService = Depends(get_posting_service),
) -> PostingResponse:
    """Validate input message and publish concurrently across all 7 platforms."""
    http_client: httpx.AsyncClient = request.app.state.http_client
    return await service.publish_all(
        client=http_client,
        message=payload.message,
        link=payload.link,
    )


@app.get(
    "/health",
    status_code=status.HTTP_200_OK,
    summary="Health check endpoint",
)
async def health_check() -> dict[str, str]:
    """Return service health status."""
    return {"status": "ok"}