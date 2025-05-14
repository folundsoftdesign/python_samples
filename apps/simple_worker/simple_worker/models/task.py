"""
Models for task management.

This module defines SQLModel models for tasks and callbacks in the worker system.
"""

import datetime
import uuid
from enum import StrEnum

from pydantic import BaseModel
from simple_storage.utils.current_utc_timestamp import current_utc_timestamp
from sqlmodel import JSON, Column, Field, Index, SQLModel


class TaskStatus(StrEnum):
    """Enum representing possible task statuses."""

    IN_QUEUE = "in_queue"
    IN_PROGRESS = "in_progress"
    SUCCESS = "success"
    FAILED = "failed"
    CANCELLED = "cancelled"


class CallbackStatus(StrEnum):
    """Enum representing possible callback statuses."""

    IN_QUEUE = "in_queue"
    IN_PROGRESS = "in_progress"
    SUCCESS = "success"
    FAILED = "failed"
    CANCELLED = "cancelled"


class TaskCreate(BaseModel):
    """Model for creating a new task."""

    tenant: str | None = Field(default=None, description="An optional tenant")
    data: dict
    callback: str | None = Field(default=None, description="The callback URL or identifier for the task.")


class TaskPayload(SQLModel, table=True):
    """SQLModel for storing task data in the database."""

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
    """SQLModel for storing callback data in the database."""

    task_id: uuid.UUID = Field(primary_key=True)
    callback: str | None

    status: CallbackStatus = Field(default=CallbackStatus.IN_QUEUE, index=True)
    created_at: datetime.datetime = Field(default_factory=current_utc_timestamp)
    completed_at: datetime.datetime = Field(default=None, nullable=True)
    error_message: str = Field(default=None, nullable=True)

    __table_args__ = (Index("calback_status", "status"),)
