from beanie import Document


class JobLock(Document):
    job_id: str
    expireAt: float
