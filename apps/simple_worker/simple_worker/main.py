# playground.sequential_processor.main

"""
Asynchronous GPU Task Queue with FastAPI and SQLModel.

This module implements a basic GPU task queue using FastAPI, SQLModel, and anyio.
It provides an API for enqueuing tasks, retrieving task status, and managing a
background worker that processes tasks asynchronously.

Key components:

-   `TaskPayload`: SQLModel for storing task data in a SQLite database.
-   `process_task`: Asynchronous function simulating GPU processing.
-   `worker`: Background task that continuously processes tasks from a queue.
-   `enqueue_gpu_task`: FastAPI endpoint for enqueuing tasks.
-   `get_tasks`: FastAPI endpoint for retrieving all tasks.
-   `get_task`: FastAPI endpoint for retrieving a specific task.
-   `lifespan`: FastAPI lifespan context manager for starting and stopping the worker.

The system uses `anyio` for asynchronous operations and `anyio.Semaphore` for
concurrency control. Tasks are enqueued through a memory object stream and
processed by a background worker. Task status is tracked in the database.

Example usage:

1.  Start the FastAPI application.
2.  Send a POST request to `/worker` to enqueue a task.
3.  Send a GET request to `/worker` or `/worker/{task_id}` to retrieve task status.
"""

import datetime
import logging
import traceback
import uuid
from contextlib import asynccontextmanager
from dataclasses import dataclass
from enum import StrEnum
from pathlib import Path
from typing import Annotated

import anyio
import sqlalchemy
from anyio.streams.memory import MemoryObjectReceiveStream, MemoryObjectSendStream
from apscheduler.schedulers.asyncio import AsyncIOScheduler
from fastapi import APIRouter, Depends, FastAPI, HTTPException
from pydantic import BaseModel
from sqlmodel import JSON, Column, Field, Index, Session, SQLModel, create_engine, select

# Setup logging
logging.basicConfig(level=logging.DEBUG)
logger = logging.getLogger(__name__)


# Utilities
def current_utc_timestamp():
    return datetime.datetime.now(datetime.UTC)


# Constants
CLEAN_UP_INTERVAL = 60 * 60  # 1 hour


# Dataclasses
@dataclass
class RetryConfig:
    max_retries: int = 3
    retry_delay: int = 5


# Exceptions
class TaskNotFoundError(ValueError):
    """Exception raised when a task is not found."""


router = APIRouter(prefix="/worker")

# Task handling streams, locks and semaphore
task_send_receive_streams: tuple[MemoryObjectSendStream[uuid.UUID], MemoryObjectReceiveStream[uuid.UUID]] = (
    anyio.create_memory_object_stream()
)
task_send_stream, task_receive_stream = task_send_receive_streams
task_lock = anyio.Lock()
task_semaphore = anyio.Semaphore(1)  # Limit the number of concurrent tasks to 1

# Callback handling streams, locks and semaphore
callback_send_receive_streams: tuple[MemoryObjectSendStream[uuid.UUID], MemoryObjectReceiveStream[uuid.UUID]] = (
    anyio.create_memory_object_stream()
)
callback_send_stream, callback_receive_stream = callback_send_receive_streams
callback_lock = anyio.Lock()
callback_semaphore = anyio.Semaphore(1)  # Limit the number of concurrent callbacks to 1

sqlite_file = Path(__file__).parent / "../data" / "database.db"
sqlite_url = f"sqlite:///{sqlite_file}"

engine = create_engine(
    sqlite_url,
    pool_size=5,
    max_overflow=10,
    pool_timeout=30,
    pool_recycle=3600,
)


class TaskStatus(StrEnum):
    IN_QUEUE = "in_queue"
    IN_PROGRESS = "in_progress"
    SUCCESS = "success"
    FAILED = "failed"
    CANCELLED = "cancelled"


class CallbackStatus(StrEnum):
    IN_QUEUE = "in_queue"
    IN_PROGRESS = "in_progress"
    SUCCESS = "success"
    FAILED = "failed"
    CANCELLED = "cancelled"


class TaskCreate(BaseModel):
    tenant: str | None = Field(default=None, description="An optional tenand")
    data: dict
    callback: str | None = Field(default=None, description="The callback URL or identifier for the task.")


class TaskPayload(SQLModel, table=True):
    task_id: uuid.UUID = Field(default_factory=uuid.uuid4, primary_key=True)
    tenant: str = Field(default="*SYSTEM")
    data: dict = Field(sa_column=Column(JSON))
    result: dict = Field(default=None, sa_column=Column(JSON))

    callback: str | None = Field(default=None)

    status: TaskStatus = Field(default=TaskStatus.IN_QUEUE, index=True)
    created_at: datetime.datetime = Field(default_factory=current_utc_timestamp)
    completed_at: datetime.datetime = Field(default=None, nullable=True)
    error_message: str = Field(default=None, nullable=True)

    __table_args__ = (Index("task_status", "status"),)


class CallbackPayload(SQLModel, table=True):
    task_id: uuid.UUID = Field(primary_key=True)
    callback: str | None

    status: CallbackStatus = Field(default=CallbackStatus.IN_QUEUE, index=True)
    created_at: datetime.datetime = Field(default_factory=current_utc_timestamp)
    completed_at: datetime.datetime = Field(default=None, nullable=True)
    error_message: str = Field(default=None, nullable=True)

    __table_args__ = (Index("calback_status", "status"),)


SQLModel.metadata.create_all(engine)


def get_session():
    with Session(engine) as session:
        yield session


def get_task_from_db(session: Session, task_id: uuid.UUID) -> TaskPayload | None:
    return session.get(TaskPayload, task_id)


def update_task_status(
    session: Session, task_payload: TaskPayload, status: TaskStatus, error_message: str | None = None, result: dict | None = None
) -> None:
    task_payload.status = status
    if error_message:
        task_payload.error_message = error_message
    if result:
        task_payload.result = result
    if status in [TaskStatus.SUCCESS, TaskStatus.FAILED]:
        task_payload.completed_at = current_utc_timestamp()
    session.add(task_payload)
    session.commit()


def get_callback(session: Session, task_id: uuid.UUID) -> CallbackPayload | None:
    return session.get(CallbackPayload, task_id)


def add_callback(session: Session, task_id: uuid.UUID, callback: str) -> CallbackPayload:
    callback_payload = CallbackPayload(task_id=task_id, callback=callback)

    session.add(callback_payload)
    session.commit()

    return callback_payload


def update_callback_status(
    session: Session, callback_payload: CallbackPayload, status: CallbackStatus, status_message: str | None = None
) -> None:
    callback_payload.status = status
    if status_message:
        callback_payload.status_message = status_message
    if status in [CallbackStatus.SUCCESS, CallbackStatus.FAILED]:
        callback_payload.completed_at = current_utc_timestamp()
    session.add(callback_payload)
    session.commit()


async def do_something(task_id: uuid.UUID, *, session: Session) -> dict:
    logger.debug("Processing task %s", task_id)

    task_payload = get_task_from_db(session, task_id)
    if not task_payload:
        msg = f"Task {task_id} not found"
        logger.error(msg)
        raise TaskNotFoundError(msg)

    logger.debug("Task %s data: %s", task_id, task_payload.data)

    data = task_payload.data

    for i in range(5):
        await anyio.sleep(1)
        logger.debug(f"Task {task_id} progress: {i + 1}/5")

    result_dict = {
        "task_id": str(task_id),
        "status": "completed",
        "data": data,
        "processed_at": str(anyio.current_time()),
    }

    logger.debug("Task %s completed", task_id)

    return result_dict


async def handle_database_error(
    session: Session, task_id: uuid.UUID, db_error: Exception, retries: int, retry_config: RetryConfig = RetryConfig()
) -> None:
    max_retries = retry_config.max_retries
    retry_delay = retry_config.retry_delay

    logger.error(f"Database error (retry {retries + 1}/{max_retries}) for task {task_id}: {db_error}")
    if retries < max_retries:
        await anyio.sleep(retry_delay)
    else:
        logger.error(f"Max retries exceeded for task {task_id}")
        task_payload = get_task_from_db(session, task_id)
        if task_payload:
            update_task_status(session, task_payload, TaskStatus.FAILED, str(db_error))


async def handle_unexpected_error(
    session: Session, task_id: uuid.UUID, error: Exception, retries: int, retry_config: RetryConfig = RetryConfig()
) -> None:
    max_retries = retry_config.max_retries
    retry_delay = retry_config.retry_delay

    error_message = f"{error}\n{traceback.format_exc()}"

    logger.error(f"Unexpected error (retry {retries + 1}/{max_retries}) for task {task_id}: {error_message}")
    if retries < max_retries:
        await anyio.sleep(retry_delay)
    else:
        logger.error(f"Max retries exceeded for task {task_id}")
        task_payload = get_task_from_db(session, task_id)
        if task_payload:
            update_task_status(session, task_payload, TaskStatus.FAILED, str(error))


async def process_task(task_id: uuid.UUID, session: Session, retry_config: RetryConfig = RetryConfig()):
    max_retries = retry_config.max_retries

    retries = 0
    while retries < max_retries:
        async with task_semaphore:
            try:
                task_payload = get_task_from_db(session, task_id)

                if not task_payload:
                    logger.error("Task %s not found", task_id)
                    return

                update_task_status(session, task_payload, TaskStatus.IN_PROGRESS)

                result = await do_something(task_id, session=session)

                update_task_status(session, task_payload, TaskStatus.SUCCESS, result=result)

                return  # noqa: TRY300

            except TaskNotFoundError:
                logger.exception(f"Task {task_id} not found. Not retrying.")
                return

            except sqlalchemy.exc.SQLAlchemyError as db_error:
                await handle_database_error(session, task_id, db_error, retries, retry_config)

            except anyio.get_cancelled_exc_class():
                task_payload = get_task_from_db(session, task_id)
                if task_payload:
                    update_task_status(session, task_payload, TaskStatus.CANCELLED, "Task cancelled")
                    session.commit()
                raise

            except Exception as e:
                await handle_unexpected_error(session, task_id, e, retries, retry_config)

            finally:
                if retries > 0:
                    logger.debug(f"Task {task_id} retried {retries} times.")

            retries += 1


async def handle_callback_database_error(
    session: Session, task_id: uuid.UUID, db_error: Exception, retries: int, retry_config: RetryConfig = RetryConfig()
) -> None:
    max_retries = retry_config.max_retries
    retry_delay = retry_config.retry_delay

    logger.error(f"Database error (retry {retries + 1}/{max_retries}) for callback {task_id}: {db_error}")
    if retries < max_retries:
        await anyio.sleep(retry_delay)
    else:
        logger.error(f"Max retries exceeded for callback {task_id}")
        callback_payload = get_callback(session, task_id)
        if callback_payload:
            update_callback_status(session, callback_payload, CallbackStatus.FAILED, str(db_error))


async def handle_callback_unexpected_error(
    session: Session, task_id: uuid.UUID, error: Exception, retries: int, retry_config: RetryConfig = RetryConfig()
) -> None:
    max_retries = retry_config.max_retries
    retry_delay = retry_config.retry_delay

    error_message = f"{error}\n{traceback.format_exc()}"

    logger.error(f"Unexpected error (retry {retries + 1}/{max_retries}) for callback {task_id}: {error_message}")
    if retries < max_retries:
        await anyio.sleep(retry_delay)
    else:
        logger.error(f"Max retries exceeded for callback {task_id}")
        callback_payload = get_callback(session, task_id)
        if callback_payload:
            update_callback_status(session, callback_payload, CallbackStatus.FAILED, str(error))


async def process_callback(task_id: uuid.UUID, session: Session, retry_config: RetryConfig = RetryConfig()):
    max_retries = retry_config.max_retries

    retries = 0
    while retries < max_retries:
        async with callback_semaphore:
            try:
                callback_payload = get_callback(session, task_id)
                task_payload = get_task_from_db(session, task_id)

                if not callback_payload or not task_payload:
                    logger.error("Failed to resolve information for callback %s", task_id)
                    return

                update_callback_status(session, callback_payload, CallbackStatus.IN_PROGRESS)

                # TODO: Implement the callback using httpx.  # noqa: FIX002
                # Example:
                # async with httpx.AsyncClient() as client:
                #     response = await client.post(callback_payload.callback, json=task_payload.result)
                #     response.raise_for_status()  # Raise HTTPError for bad responses (4xx or 5xx)
                #     logger.debug(f"Callback {task_id} response: {response.status_code} - {response.text}")

                update_callback_status(session, callback_payload, CallbackStatus.SUCCESS)

                return  # noqa: TRY300

            except sqlalchemy.exc.SQLAlchemyError as db_error:
                await handle_callback_database_error(session, task_id, db_error, retries, retry_config)

            except anyio.get_cancelled_exc_class():
                callback_payload = get_callback(session, task_id)
                if callback_payload:
                    update_callback_status(session, callback_payload, CallbackStatus.CANCELLED, "Callback cancelled")
                    session.commit()
                raise

            except Exception as error:
                await handle_callback_unexpected_error(session, task_id, error, retries, retry_config)

            finally:
                if retries > 0:
                    logger.debug(f"Callback {task_id} retried {retries} times.")

            retries += 1


async def recover_tasks():
    """
    Recovers tasks that were in_queue or in_progress when the application last stopped.

    This function queries the database for tasks with statuses "in_queue" or "in_progress"
    and sends their IDs to the worker queue, effectively re-enqueuing them for processing.
    """
    with Session(engine) as session:
        logger.debug("Starting task recovery")
        tasks = session.exec(select(TaskPayload).where(TaskPayload.status.in_([TaskStatus.IN_QUEUE, TaskStatus.IN_PROGRESS]))).all()
        for task in tasks:
            await task_send_stream.send(task.task_id)
            logger.info("Recovered task %s", task.task_id)


async def callback_worker():
    async with anyio.create_task_group() as task_group:
        async for task_id in callback_receive_stream:
            with Session(engine) as session:
                task_group.start_soon(process_callback, task_id, session)


async def task_worker():
    """
    Background worker that continuously retrieves task IDs from the queue and processes them.

    This function creates a task group to manage concurrent task processing. It listens for
    task IDs from the `receive_stream` and starts a `process_task` coroutine for each ID.
    """
    async with anyio.create_task_group() as task_group:  # create a task group
        async for task_id in task_receive_stream:
            with Session(engine) as session:
                task_group.start_soon(process_task, task_id, session)  # start the task in the task group.


def cleanup_database(session: Session, retention_hours: int = 10, target_status: TaskStatus = TaskStatus.SUCCESS):
    """
    Cleans up the database by deleting SUCCESS tasks older than retention_hours.
    """
    cutoff_time = datetime.datetime.now(datetime.UTC) - datetime.timedelta(hours=retention_hours)

    tasks_to_delete = session.exec(
        select(TaskPayload).where(TaskPayload.status == target_status, TaskPayload.created_at < cutoff_time)
    ).all()

    for task in tasks_to_delete:
        session.delete(task)
        logging.info(f"Deleted task {task.task_id}")

    session.commit()


async def run_cleanup(retention_hours: int = 24, target_status: TaskStatus = TaskStatus.SUCCESS):
    """
    Runs the database cleanup periodically for SUCCESS tasks.
    """
    logging.info("Starting %s task cleanup", target_status)
    with Session(engine) as session:
        cleanup_database(session, retention_hours, target_status)
    logging.info("Cleanup completed for %s tasks", target_status)


@router.post("")
async def enqueue_gpu_task(task_create: TaskCreate, session: Annotated[Session, Depends(get_session)]):
    """
    Enqueues a GPU task by adding it to the database and sending its ID to the worker queue.

    Args:
        task: The TaskPayload object containing task data.

    Returns:
        A dictionary with a message indicating the task was enqueued.
    """
    task = TaskPayload(tenant=task_create.tenant, data=task_create.data, callback=task_create.callback)
    session.add(task)
    session.commit()
    task_id = task.task_id
    await task_send_stream.send(task_id)
    return {"message": f"Task {task_id} enqueued at {task.created_at}"}


@router.get("")
async def get_tasks(session: Annotated[Session, Depends(get_session)]):
    """
    Retrieves all tasks from the database.

    Returns:
        A list of TaskPayload objects.
    """
    return session.exec(select(TaskPayload)).all()


@router.get("/{task_id}")
async def get_task(task_id: uuid.UUID, session: Annotated[Session, Depends(get_session)]):
    """
    Retrieves a specific task from the database by its ID.

    Args:
        task_id: The UUID of the task to retrieve.

    Returns:
        The TaskPayload object if found, otherwise None.
    """
    task = session.get(TaskPayload, task_id)
    if not task:
        raise HTTPException(status_code=404, detail="Task not found")
    return task


@asynccontextmanager
async def lifespan(app: FastAPI):
    task_group = anyio.create_task_group()
    async with task_group:
        app.extra["task_group"] = task_group
        app.extra["process_task"] = process_task

        task_group.start_soon(recover_tasks)
        task_group.start_soon(task_worker)

        scheduler = AsyncIOScheduler()
        scheduler.add_job(run_cleanup, "cron", hour=3, args=[24, TaskStatus.SUCCESS])
        scheduler.add_job(run_cleanup, "cron", hour=3, args=[24, TaskStatus.FAILED])
        scheduler.start()

        yield
        logger.info("Application shutdown started")
        task_group.cancel_scope.cancel()
        scheduler.shutdown()
        logger.info("Application shutdown complete")


app = FastAPI(lifespan=lifespan)
app.include_router(router)
