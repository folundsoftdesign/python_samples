"""
Asynchronous GPU Task Queue with FastAPI and SQLModel.

This module implements a basic GPU task queue using FastAPI, SQLModel, and anyio.
It provides an API for enqueuing tasks, retrieving task status, and managing a
background worker that processes tasks asynchronously.

Key components:

-   `TaskPayload`: SQLModel for storing task data in a SQLite database.
-   `process_gpu_task`: Asynchronous function simulating GPU processing.
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
import uuid
from contextlib import asynccontextmanager
from enum import StrEnum
from pathlib import Path
from typing import Tuple

import anyio
from anyio.streams.memory import MemoryObjectReceiveStream, MemoryObjectSendStream
from fastapi import APIRouter, FastAPI
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

engine = create_engine(sqlite_url)


class TaskStatus(StrEnum):
    IN_QUEUE = "in_queue"
    IN_PROGRESS = "in_progress"
    SUCCESS = "success"
    FAILED = "failed"


class TaskPayload(SQLModel, table=True):
    """
    Represents a task payload stored in the database.

    Attributes:
        id: The unique identifier of the task.
        data: The data associated with the task.
        status: The current status of the task (e.g., in_queue, in_progress, success, failed).
    """

    id: uuid.UUID = Field(default_factory=uuid.uuid4, primary_key=True)
    data: str
    status: TaskStatus = Field(default=TaskStatus.IN_QUEUE)


SQLModel.metadata.create_all(engine)


async def process_gpu_task(task_id: uuid.UUID):
    """
    Simulates GPU processing for a given task ID.

    This function acquires a semaphore to limit concurrent GPU tasks, retrieves the task
    from the database, updates its status to "in_progress", simulates GPU processing
    with a sleep, updates the status to "success" or "failed" based on the result,
    and commits the changes to the database.

    Args:
        task_id: The UUID of the task to process.
    """
    async with task_semaphore:  # acquire the semaphore
        try:
            with Session(engine) as session:
                task_payload = session.get(TaskPayload, task_id)
                if task_payload:
                    task_payload.status = TaskStatus.IN_PROGRESS
                    session.add(task_payload)
                    session.commit()
                    logger.debug("GPU task %s started", task_id)
                    await anyio.sleep(5)  # Simulate GPU processing
                    logger.debug("GPU task %s completed", task_id)
                    task_payload.status = TaskStatus.SUCCESS
                    session.add(task_payload)
                    session.commit()
                else:
                    logger.error("Task %s not found", task_id)
        except Exception as e:
            logger.error("Error processing GPU task %s: %s", task_id, e)
            # Add any exception handling logic here (e.g., logging)
        finally:
            # The lock will be released even if an exception occurs
            pass


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
    task IDs from the `receive_stream` and starts a `process_gpu_task` coroutine for each ID.
    """
    async with anyio.create_task_group() as task_group:  # create a task group
        async for task_id in receive_stream:
            task_group.start_soon(process_gpu_task, task_id)  # start the task in the task group.


@router.post("")
async def enqueue_gpu_task(task: TaskPayload):
    """
    Enqueues a GPU task by adding it to the database and sending its ID to the worker queue.

    Args:
        task: The TaskPayload object containing task data.

    Returns:
        A dictionary with a message indicating the task was enqueued.
    """
    with Session(engine) as session:
        session.add(task)
        session.commit()
        task_id = task.id
    await send_stream.send(task_id)
    return {"message": f"GPU task {task_id} enqueued"}


@router.get("")
async def get_tasks():
    """
    Retrieves all tasks from the database.

    Returns:
        A list of TaskPayload objects.
    """
    with Session(engine) as session:
        tasks = session.exec(select(TaskPayload)).all()
    return tasks


@router.get("/{task_id}")
async def get_task(task_id: uuid.UUID):
    """
    Retrieves a specific task from the database by its ID.

    Args:
        task_id: The UUID of the task to retrieve.

    Returns:
        The TaskPayload object if found, otherwise None.
    """
    with Session(engine) as session:
        task = session.get(TaskPayload, task_id)
    return task


@asynccontextmanager
async def lifespan(app: FastAPI):
    """
    Lifespan context manager for the FastAPI application.

    Starts the worker and task recovery tasks concurrently when the application starts,
    and cancels them when the application stops.

    Args:
        app: The FastAPI application instance.
    """
    task_group = anyio.create_task_group()
    async with task_group:
        task_group.start_soon(recover_tasks)
        task_group.start_soon(worker)
        yield
        task_group.cancel_scope.cancel()


app = FastAPI(lifespan=lifespan)
app.include_router(router)
