

from asgi_correlation_id import CorrelationIdMiddleware
from beanie import init_beanie
from fastapi import FastAPI
from fastapi_pagination import add_pagination
from fastapi_problem import handler as fastapi_problem_handler
from motor.motor_asyncio import AsyncIOMotorClient

from sample.constants import (
    API_VERSION,
    APP_PREFIX,
    HEADER_NAME_CPU_TIME_USED,
    HEADER_NAME_GPU_UTILIZATION,
    HEADER_NAME_PROCESS_TIME,
    HEADER_REQUEST_ID,
)
from sample.core import logger, settings
from sample.features.notes import notes_router
from sample.features.routers import health_router
from sample.middlewares.timing_metrics import TimingMetricsMiddleware
from sample.models import __beanie_models__


async def setup_beanie() -> None:
    logger.debug("Setting up Beanie")

    # Create the Motor client for beanie
    client: AsyncIOMotorClient = AsyncIOMotorClient(settings.mongo_dsn)

    db: str = settings.mongo_db

    # Initialize beanie adding all the models
    await init_beanie(client[db], document_models=__beanie_models__)

    logger.debug("Beanie setup completed")


def app_factory() -> FastAPI:
    logger.info("Creating FastAPI app")
    app = FastAPI(on_startup=[setup_beanie],
                  root_path=APP_PREFIX, version=API_VERSION)

    fastapi_problem_handler.add_exception_handler(
        app, logger=logger, documentation_uri_template="https://link-to/my/errors/{type}")

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

    # Add routes
    app.include_router(health_router)
    app.include_router(notes_router)

    add_pagination(app)

    return app
