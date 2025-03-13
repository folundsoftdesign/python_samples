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

import logging
import traceback
import uuid
from contextlib import asynccontextmanager
from enum import StrEnum
from pathlib import Path
from typing import Tuple

import anyio
import sqlalchemy
from anyio.streams.memory import MemoryObjectReceiveStream, MemoryObjectSendStream
from fastapi import APIRouter, Depends, FastAPI, HTTPException
from pydantic import BaseModel
from sqlmodel import Field, Session, SQLModel, create_engine, select

# Setup logging
logging.basicConfig(level=logging.DEBUG)
logger = logging.getLogger(__name__)


router = APIRouter(prefix="/worker")

# Router-specific state
send_receive_streams: Tuple[MemoryObjectSendStream[uuid.UUID], MemoryObjectReceiveStream[uuid.UUID]] = (
    anyio.create_memory_object_stream()
)
send_stream, receive_stream = send_receive_streams
task_lock = anyio.Lock()
task_semaphore = anyio.Semaphore(1)  # create the semaphore


sqlite_file = Path(__file__).parent / "../data" / "playground.db"
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


class TaskCreate(BaseModel):
    data: str


class TaskPayload(SQLModel, table=True):
    id: uuid.UUID = Field(default_factory=uuid.uuid4, primary_key=True)
    data: str
    status: TaskStatus = Field(default=TaskStatus.IN_QUEUE)
    error_message: str = Field(default=None, nullable=True)


SQLModel.metadata.create_all(engine)


def get_session():
    with Session(engine) as session:
        yield session


def get_task_from_db(session: Session, task_id: uuid.UUID) -> TaskPayload | None:
    return session.get(TaskPayload, task_id)


def update_task_status(session: Session, task_payload: TaskPayload, status: TaskStatus, error_message: str | None = None) -> None:
    task_payload.status = status
    if error_message:
        task_payload.error_message = error_message
    session.add(task_payload)
    session.commit()


async def do_something(task_id: uuid.UUID):
    logger.debug("Processing task %s", task_id)

    with Session(engine) as session:
        task_payload = get_task_from_db(session, task_id)
        if task_payload:
            logger.debug("Task %s data: %s", task_id, task_payload.data)

    for i in range(5):
        await anyio.sleep(1)
        logger.debug(f"Task {task_id} progress: {i + 1}/5")

    logger.debug("Task %s completed", task_id)


async def handle_database_error(
    session: Session, task_id: uuid.UUID, db_error: Exception, retries: int, max_retries: int, retry_delay: int
) -> None:
    logger.error(f"Database error (retry {retries + 1}/{max_retries}) for task {task_id}: {db_error}")
    if retries < max_retries:
        await anyio.sleep(retry_delay)
    else:
        logger.error(f"Max retries exceeded for task {task_id}")
        task_payload = get_task_from_db(session, task_id)
        if task_payload:
            update_task_status(session, task_payload, TaskStatus.FAILED, str(db_error))


async def handle_unexpected_error(
    session: Session, task_id: uuid.UUID, error: Exception, retries: int, max_retries: int, retry_delay: int
) -> None:
    error_message = f"{error}\n{traceback.format_exc()}"

    logger.error(f"Unexpected error (retry {retries + 1}/{max_retries}) for task {task_id}: {error_message}")
    if retries < max_retries:
        await anyio.sleep(retry_delay)
    else:
        logger.error(f"Max retries exceeded for task {task_id}")
        task_payload = get_task_from_db(session, task_id)
        if task_payload:
            update_task_status(session, task_payload, TaskStatus.FAILED, str(error))


async def process_task(task_id: uuid.UUID, session: Session, max_retries=3, retry_delay=5):
    retries = 0
    while retries < max_retries:
        async with task_semaphore:
            try:
                task_payload = get_task_from_db(session, task_id)

                if not task_payload:
                    logger.error("Task %s not found", task_id)
                    return

                update_task_status(session, task_payload, TaskStatus.IN_PROGRESS)

                await do_something(task_id)

                update_task_status(session, task_payload, TaskStatus.SUCCESS)
                return

            except sqlalchemy.exc.SQLAlchemyError as db_error:
                await handle_database_error(session, task_id, db_error, retries, max_retries, retry_delay)

            except anyio.get_cancelled_exc_class():
                task_payload = get_task_from_db(session, task_id)
                if task_payload:
                    update_task_status(session, task_payload, TaskStatus.FAILED, "Task cancelled")
                    session.commit()
                raise

            except Exception as e:
                await handle_unexpected_error(session, task_id, e, retries, max_retries, retry_delay)

            finally:
                if retries > 0:
                    logger.debug(f"Task {task_id} retried {retries} times.")

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
            await send_stream.send(task.id)
            logger.info("Recovered task %s", task.id)


async def worker():
    """
    Background worker that continuously retrieves task IDs from the queue and processes them.

    This function creates a task group to manage concurrent task processing. It listens for
    task IDs from the `receive_stream` and starts a `process_task` coroutine for each ID.
    """
    async with anyio.create_task_group() as task_group:  # create a task group
        async for task_id in receive_stream:
            with Session(engine) as session:
                task_group.start_soon(process_task, task_id, session)  # start the task in the task group.


@router.post("")
async def enqueue_gpu_task(task_create: TaskCreate, session: Session = Depends(get_session)):
    """
    Enqueues a GPU task by adding it to the database and sending its ID to the worker queue.

    Args:
        task: The TaskPayload object containing task data.

    Returns:
        A dictionary with a message indicating the task was enqueued.
    """
    task = TaskPayload(data=task_create.data)
    session.add(task)
    session.commit()
    task_id = task.id
    await send_stream.send(task_id)
    return {"message": f"GPU task {task_id} enqueued"}


@router.get("")
async def get_tasks(session: Session = Depends(get_session)):
    """
    Retrieves all tasks from the database.

    Returns:
        A list of TaskPayload objects.
    """
    tasks = session.exec(select(TaskPayload)).all()
    return tasks


@router.get("/{task_id}")
async def get_task(task_id: uuid.UUID, session: Session = Depends(get_session)):
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
        task_group.start_soon(worker)
        yield
        logger.info("Application shutdown started")
        task_group.cancel_scope.cancel()
        logger.info("Application shutdown complete")


app = FastAPI(lifespan=lifespan)
app.include_router(router)
