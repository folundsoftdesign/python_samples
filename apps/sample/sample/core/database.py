from beanie import Document, init_beanie
from fastapi import FastAPI, Request
from motor.motor_asyncio import AsyncIOMotorClient

from .logger import logger
from .settings import settings


async def initialize_database(
    app: FastAPI, beanie_models: list[type[Document]]
) -> None:
    """Initializes the database connection and Beanie models."""
    app.state.client = AsyncIOMotorClient(settings.mongo_dsn)
    db: str = settings.mongo_db
    await init_beanie(app.state.client[db], document_models=beanie_models)
    logger.debug("Beanie initialized")


async def close_database(app: FastAPI) -> None:
    """Closes the database connection."""
    if hasattr(app.state, "client") and app.state.client:
        app.state.client.close()
        logger.debug("Closing Beanie connection")


def get_database(request: Request) -> AsyncIOMotorClient:
    """Dependency to get the database client from app state."""
    return request.app.state.client
