from beanie import Document, init_beanie
from fastapi import Request
from motor.motor_asyncio import AsyncIOMotorClient, AsyncIOMotorDatabase

from .logger import logger
from .settings import settings


async def initialize_database(beanie_models: list[type[Document]]) -> AsyncIOMotorDatabase:
    """Initializes the database connection and Beanie models."""
    client: AsyncIOMotorClient = AsyncIOMotorClient(settings.mongo_dsn)
    db: str = settings.mongo_db

    database = client[db]

    await init_beanie(database=database, document_models=beanie_models)

    logger.debug("Beanie initialized")

    return database


async def close_database(database: AsyncIOMotorDatabase) -> None:
    """Closes the database connection."""

    logger.debug("Closing Beanie connection")

    client = database.client

    client.close()

    logger.debug("Beanie connection closed")


def get_database(request: Request) -> AsyncIOMotorDatabase:
    """Dependency to get the database client from app state."""
    return request.app.state.database
