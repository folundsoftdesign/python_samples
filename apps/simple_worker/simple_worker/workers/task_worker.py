"""
Worker module for processing tasks asynchronously.

This module contains background workers that process tasks and callbacks.
"""

import uuid

import anyio
import sqlalchemy
from sqlmodel import Session, select

from simple_worker.db.database import engine
from simple_worker.exceptions.task_not_found_error import TaskNotFoundError
from simple_worker.logger import logger
from simple_worker.models.task import CallbackStatus, TaskPayload, TaskStatus
from simple_worker.services.task_service import (
    RetryConfig,
    do_something,
    get_callback,
    get_task_from_db,
    handle_callback_database_error,
    handle_callback_unexpected_error,
    handle_database_error,
    handle_unexpected_error,
    update_callback_status,
    update_task_status,
)

# Task handling streams, locks and semaphore
task_send_receive_streams: tuple[
    anyio.streams.memory.MemoryObjectSendStream[uuid.UUID], anyio.streams.memory.MemoryObjectReceiveStream[uuid.UUID]
] = anyio.create_memory_object_stream()
task_send_stream, task_receive_stream = task_send_receive_streams
task_lock = anyio.Lock()
task_semaphore = anyio.Semaphore(1)  # Limit the number of concurrent tasks to 1

# Callback handling streams, locks and semaphore
callback_send_receive_streams: tuple[
    anyio.streams.memory.MemoryObjectSendStream[uuid.UUID], anyio.streams.memory.MemoryObjectReceiveStream[uuid.UUID]
] = anyio.create_memory_object_stream()
callback_send_stream, callback_receive_stream = callback_send_receive_streams
callback_lock = anyio.Lock()
callback_semaphore = anyio.Semaphore(1)  # Limit the number of concurrent callbacks to 1


async def process_task(task_id: uuid.UUID, session: Session, retry_config: RetryConfig = RetryConfig()):
    """
    Process a task with retry logic.

    Args:
        task_id: UUID of the task to process
        session: SQLModel database session
        retry_config: Configuration for retry behavior
    """
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


async def process_callback(task_id: uuid.UUID, session: Session, retry_config: RetryConfig = RetryConfig()):
    """
    Process a callback with retry logic.

    Args:
        task_id: UUID of the task associated with the callback
        session: SQLModel database session
        retry_config: Configuration for retry behavior
    """
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
    Recover tasks that were in_queue or in_progress when the application last stopped.

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
    """
    Background worker that continuously retrieves callback IDs from the queue and processes them.

    This function creates a task group to manage concurrent callback processing. It listens for
    callback IDs from the callback_receive_stream and starts a process_callback coroutine for each ID.
    """
    async with anyio.create_task_group() as task_group:
        async for task_id in callback_receive_stream:
            with Session(engine) as session:
                task_group.start_soon(process_callback, task_id, session)


async def task_worker():
    """
    Background worker that continuously retrieves task IDs from the queue and processes them.

    This function creates a task group to manage concurrent task processing. It listens for
    task IDs from the task_receive_stream and starts a process_task coroutine for each ID.
    """
    async with anyio.create_task_group() as task_group:
        async for task_id in task_receive_stream:
            with Session(engine) as session:
                task_group.start_soon(process_task, task_id, session)
