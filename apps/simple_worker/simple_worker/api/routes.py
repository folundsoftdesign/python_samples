"""
API routes for the worker service.

This module defines the FastAPI routes for the worker service.
"""

import uuid
from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException
from sqlmodel import Session, select

from simple_worker.db.database import get_session
from simple_worker.models.task import TaskCreate, TaskPayload
from simple_worker.workers.task_worker import task_send_stream

router = APIRouter(prefix="/worker")


@router.post("")
async def enqueue_gpu_task(task_create: TaskCreate, session: Annotated[Session, Depends(get_session)]):
    """
    Enqueues a GPU task by adding it to the database and sending its ID to the worker queue.

    Args:
        task_create: The TaskCreate object containing task data

    Returns:
        A dictionary with a message indicating the task was enqueued
    """
    task = TaskPayload(tenant=task_create.tenant, data=task_create.data, callback=task_create.callback)
    session.add(task)
    session.commit()
    task_id = task.task_id
    await task_send_stream.send(task_id)

    return {"success": True, "task_id": task_id, "enqueued_at": task.created_at, "message": "Task enqueued"}


@router.get("")
async def get_tasks(session: Annotated[Session, Depends(get_session)]):
    """
    Retrieves all tasks from the database.

    Returns:
        A list of TaskPayload objects
    """
    return session.exec(select(TaskPayload)).all()


@router.get("/{task_id}")
async def get_task(task_id: uuid.UUID, session: Annotated[Session, Depends(get_session)]):
    """
    Retrieves a specific task from the database by its ID.

    Args:
        task_id: The UUID of the task to retrieve

    Returns:
        The TaskPayload object if found

    Raises:
        HTTPException: If the task is not found
    """
    task = session.get(TaskPayload, task_id)
    if not task:
        raise HTTPException(status_code=404, detail="Task not found")
    return task
