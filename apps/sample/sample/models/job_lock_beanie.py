from beanie import Document, Indexed
from datetime import datetime
from typing import Annotated


class JobLock(Document):
    job_id: str
    expire_at: Annotated[datetime, Indexed(expireAfterSeconds=0)]
