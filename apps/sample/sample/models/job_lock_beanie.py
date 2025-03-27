from datetime import datetime
from typing import Annotated

from beanie import Document, Indexed


class JobLock(Document):
    job_id: str
    expire_at: Annotated[datetime, Indexed(expireAfterSeconds=0)]
