from datetime import UTC, datetime

from beanie import Insert, Replace, Save, SaveChanges, Update, before_event
from pydantic import BaseModel, Field


def get_time_utc():
    return datetime.now(UTC)


class TimestampMixin(BaseModel):
    created_at: datetime = Field(default_factory=get_time_utc)
    updated_at: datetime | None = None
    delete_at: datetime | None = None

    @before_event(Insert)
    def set_created_at(self):
        self.created_at = get_time_utc()

    @before_event(Update, SaveChanges, Save, Replace)
    def set_updated_at(self):
        self.updated_at = get_time_utc()
