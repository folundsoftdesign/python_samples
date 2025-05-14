"""
Task service module.

This module provides functions for interacting with task and callback records in the database.
"""

import datetime
import traceback
import uuid
from dataclasses import dataclass

import anyio
from simple_storage.utils.current_utc_timestamp import current_utc_timestamp
from sqlmodel import Session, select

from simple_worker.db.database import engine
from simple_worker.exceptions.task_not_found_error import TaskNotFoundError
from simple_worker.logger import logger
from simple_worker.models.task import CallbackPayload, CallbackStatus, TaskPayload, TaskStatus


@dataclass
class RetryConfig:
    """Configuration for retry behavior."""

    max_retries: int = 3
    retry_delay: int = 5


def get_task_from_db(session: Session, task_id: uuid.UUID) -> TaskPayload | None:
    """
    Retrieve a task from the database by ID.

    Args:
        session: SQLModel database session
        task_id: UUID of the task to retrieve

    Returns:
        The task if found, None otherwise
    """
    return session.get(TaskPayload, task_id)


def update_task_status(
    session: Session, task_payload: TaskPayload, status: TaskStatus, error_message: str | None = None, result: dict | None = None
) -> None:
    """
    Update the status of a task in the database.

    Args:
        session: SQLModel database session
        task_payload: The task to update
        status: The new status to set
        error_message: Optional error message to store
        result: Optional result data to store
    """
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
    """
    Retrieve a callback from the database by task ID.

    Args:
        session: SQLModel database session
        task_id: UUID of the task associated with the callback

    Returns:
        The callback if found, None otherwise
    """
    return session.get(CallbackPayload, task_id)


def add_callback(session: Session, task_id: uuid.UUID, callback: str) -> CallbackPayload:
    """
    Add a new callback to the database.

    Args:
        session: SQLModel database session
        task_id: UUID of the task associated with the callback
        callback: The callback URL or identifier

    Returns:
        The created callback record
    """
    callback_payload = CallbackPayload(task_id=task_id, callback=callback)
    session.add(callback_payload)
    session.commit()
    return callback_payload


def update_callback_status(
    session: Session, callback_payload: CallbackPayload, status: CallbackStatus, error_message: str | None = None
) -> None:
    """
    Update the status of a callback in the database.

    Args:
        session: SQLModel database session
        callback_payload: The callback to update
        status: The new status to set
        error_message: Optional error message to store
    """
    callback_payload.status = status
    if error_message:
        callback_payload.error_message = error_message
    if status in [CallbackStatus.SUCCESS, CallbackStatus.FAILED]:
        callback_payload.completed_at = current_utc_timestamp()
    session.add(callback_payload)
    session.commit()


async def do_something(task_id: uuid.UUID, *, session: Session) -> dict:
    """
    Process a task by performing some simulated work.

    Args:
        task_id: UUID of the task to process
        session: SQLModel database session

    Returns:
        Dictionary containing the result of the task

    Raises:
        TaskNotFoundError: If the task is not found in the database
    """
    logger.debug("Processing task %s", task_id)

    task_payload = get_task_from_db(session, task_id)
    if not task_payload:
        msg = f"Task {task_id} not found"
        logger.error(msg)
        raise TaskNotFoundError(msg)

    logger.debug("Task %s data: %s", task_id, task_payload.data)

    data = task_payload.data

    # Simulate work with a delay
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
    """
    Handle database errors during task processing.

    Args:
        session: SQLModel database session
        task_id: UUID of the task that encountered an error
        db_error: The database error that occurred
        retries: Number of retries attempted so far
        retry_config: Configuration for retry behavior
    """
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
    """
    Handle unexpected errors during task processing.

    Args:
        session: SQLModel database session
        task_id: UUID of the task that encountered an error
        error: The unexpected error that occurred
        retries: Number of retries attempted so far
        retry_config: Configuration for retry behavior
    """
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


async def handle_callback_database_error(
    session: Session, task_id: uuid.UUID, db_error: Exception, retries: int, retry_config: RetryConfig = RetryConfig()
) -> None:
    """
    Handle database errors during callback processing.

    Args:
        session: SQLModel database session
        task_id: UUID of the task that encountered an error
        db_error: The database error that occurred
        retries: Number of retries attempted so far
        retry_config: Configuration for retry behavior
    """
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
    """
    Handle unexpected errors during callback processing.

    Args:
        session: SQLModel database session
        task_id: UUID of the task that encountered an error
        error: The unexpected error that occurred
        retries: Number of retries attempted so far
        retry_config: Configuration for retry behavior
    """
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


def cleanup_database(session: Session, retention_hours: int = 24, target_status: TaskStatus = TaskStatus.SUCCESS):
    """
    Clean up the database by deleting old tasks with the specified status.

    Args:
        session: SQLModel database session
        retention_hours: Number of hours to retain tasks
        target_status: Status of tasks to delete
    """
    cutoff_time = current_utc_timestamp() - datetime.timedelta(hours=retention_hours)

    tasks_to_delete = session.exec(
        select(TaskPayload).where(TaskPayload.status == target_status, TaskPayload.created_at < cutoff_time)
    ).all()

    for task in tasks_to_delete:
        session.delete(task)
        logger.info(f"Deleted task {task.task_id}")

    session.commit()


async def run_cleanup(retention_hours: int = 24, target_status: TaskStatus = TaskStatus.SUCCESS):
    """
    Run the database cleanup operation for tasks with the specified status.

    Args:
        retention_hours: Number of hours to retain tasks
        target_status: Status of tasks to delete
    """
    logger.info("Starting %s task cleanup", target_status)
    with Session(engine) as session:
        cleanup_database(session, retention_hours, target_status)
    logger.info("Cleanup completed for %s tasks", target_status)
