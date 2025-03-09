from collections.abc import AsyncIterator
from contextlib import asynccontextmanager

from anyio import CapacityLimiter
from anyio.lowlevel import RunVar
from asgi_correlation_id import CorrelationIdMiddleware
from fastapi import FastAPI
from fastapi_pagination import add_pagination
from fastapi_problem import handler as fastapi_problem_handler

from sample.constants import (
    API_VERSION,
    APP_PREFIX,
    HEADER_NAME_CPU_TIME_USED,
    HEADER_NAME_GPU_UTILIZATION,
    HEADER_NAME_PROCESS_TIME,
    HEADER_REQUEST_ID,
)
from sample.core import (
    close_database,
    configure_logger,
    initialize_database,
    logger,
    settings,
)
from sample.features.routers import api_router
from sample.middlewares.timing_metrics import TimingMetricsMiddleware
from sample.models import __beanie_models__

configure_logger(settings=settings)


@asynccontextmanager
async def lifespan(app: FastAPI) -> AsyncIterator[None]:
    """Manages the application's lifespan, including database connection."""
    logger.debug("FastAPI app startup - lifespan")
    await initialize_database(app, __beanie_models__)
    RunVar[CapacityLimiter]("_default_thread_limiter").set(CapacityLimiter(1))
    try:
        yield
    finally:
        await close_database(app)


def app_factory() -> FastAPI:
    logger.info("Creating FastAPI app")

    app = FastAPI(lifespan=lifespan, root_path=APP_PREFIX, version=API_VERSION)

    fastapi_problem_handler.add_exception_handler(app, logger=logger, documentation_uri_template="{type}")

    # Add middleware to include correlation id in logs and responses
    app.add_middleware(
        CorrelationIdMiddleware,
        header_name=HEADER_REQUEST_ID,
        update_request_header=True,
    )

    app.add_middleware(
        TimingMetricsMiddleware,
        header_name_process_time=HEADER_NAME_PROCESS_TIME,
        header_name_gpu_utilization=HEADER_NAME_GPU_UTILIZATION,
        header_name_cpu_time_used=HEADER_NAME_CPU_TIME_USED,
    )

    app.include_router(api_router)

    add_pagination(app)

    return app


app = app_factory()
