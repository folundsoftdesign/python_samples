import uuid
from datetime import UTC, datetime
from typing import Literal

from pydantic import Field
from sqlmodel import SQLModel


def current_utc_timestamp():
    return datetime.now(UTC)


class BackgroundJob(SQLModel):
    uid: uuid.UUID

    status: Literal["in_queue", "in_progress", "completed", "failed"]
    created_at: datetime = Field(default_factory=current_utc_timestamp)
    updated_at: datetime | None = None
