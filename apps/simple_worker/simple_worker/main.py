"""
Entry point for the asynchronous GPU task queue application.

This module defines the FastAPI application with its lifespan context manager,
which starts and stops the background workers for task processing.
"""

from contextlib import asynccontextmanager

import anyio
from apscheduler.schedulers.asyncio import AsyncIOScheduler
from fastapi import FastAPI

from simple_worker.api.routes import router
from simple_worker.constants import CLEAN_UP_INTERVAL
from simple_worker.db.database import initialize_db
from simple_worker.logger import logger
from simple_worker.models.task import TaskStatus
from simple_worker.services.task_service import run_cleanup
from simple_worker.workers.task_worker import callback_worker, process_callback, process_task, recover_tasks, task_worker


@asynccontextmanager
async def lifespan(app: FastAPI):
    """
    FastAPI lifespan context manager.

    This function is called when the FastAPI application starts and stops.
    It starts the background workers when the application starts and cancels them when it stops.

    Args:
        app: The FastAPI application
    """
    task_group = anyio.create_task_group()
    async with task_group:
        app.extra["task_group"] = task_group
        app.extra["process_task"] = process_task
        app.extra["process_callback"] = process_callback

        task_group.start_soon(recover_tasks)
        task_group.start_soon(task_worker)
        task_group.start_soon(callback_worker)

        scheduler = AsyncIOScheduler()
        scheduler.add_job(run_cleanup, "cron", hour=3, args=[CLEAN_UP_INTERVAL, TaskStatus.SUCCESS])
        scheduler.add_job(run_cleanup, "cron", hour=3, args=[CLEAN_UP_INTERVAL, TaskStatus.FAILED])
        scheduler.start()

        yield
        logger.info("Application shutdown started")
        task_group.cancel_scope.cancel()
        scheduler.shutdown()
        logger.info("Application shutdown complete")


def create_app() -> FastAPI:
    """
    Create and configure the FastAPI application.

    Returns:
        The configured FastAPI application
    """
    # Initialize the database
    initialize_db()

    # Create and configure the FastAPI application
    app = FastAPI(
        title="Asynchronous GPU Task Queue",
        description="A FastAPI application for asynchronous GPU task processing",
        version="1.0.0",
        lifespan=lifespan,
    )

    # Include the API router
    app.include_router(router)

    return app


app = create_app()
