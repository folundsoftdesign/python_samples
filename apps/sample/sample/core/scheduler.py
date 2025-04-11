import uuid
from datetime import UTC, datetime, timedelta

from apscheduler.schedulers.asyncio import AsyncIOScheduler
from motor.motor_asyncio import AsyncIOMotorDatabase
from pymongo.errors import DuplicateKeyError

from sample.models.job_lock_beanie import JobLock

from .logger import logger


def setup_scheduler(*, database: AsyncIOMotorDatabase | None = None) -> AsyncIOScheduler:
    scheduler = AsyncIOScheduler(
        timezone="UTC",
    )

    scheduler.add_job(health_job, "interval", seconds=10, id="health_check", replace_existing=True)

    return scheduler


def start_scheduler(scheduler: AsyncIOScheduler) -> None:
    scheduler.start()


def stop_scheduler(scheduler: AsyncIOScheduler) -> None:
    scheduler.shutdown(wait=True)


async def health_job(job_id=None):
    """An example of a job using a lock to prevent multiple instances from running at the same time."""
    if job_id is None:
        job_id = str(uuid.uuid4())

    lock_ttl = 10  # 10 seconds lock

    expire_at = datetime.now(UTC) + timedelta(seconds=lock_ttl)

    try:
        lock = JobLock(job_id=job_id, expire_at=expire_at)
        await lock.insert()

        logger.info("Health check job is running")

    except DuplicateKeyError:
        logger.warning("Health check job is already running")

    except Exception as e:
        logger.error(f"Health check job failed: {e}")

    finally:
        try:
            await JobLock.find(job_id=job_id).delete()
        except Exception as e:
            logger.error(f"Failed to release lock: {e}")
