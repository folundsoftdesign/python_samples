import time
from http import HTTPStatus
from typing import Dict
from uuid import UUID

from fastapi import APIRouter, BackgroundTasks
from pydantic import BaseModel
from sample.core import logger


class Job(BaseModel):
    uid: UUID
    status: str = "in_progress"


background_tasks_router = APIRouter(prefix="/background_tasks")

jobs: Dict[UUID, Job] = {}


def mock_function(id_job) -> str:
    jobs[id_job].status = "in_progress"
    time.sleep(5)
    return "done"


def process_request(job_id):
    response = mock_function(job_id)
    logger.info(f"Job {job_id} completed and returned {response}")
    jobs[job_id].status = "complete"


@background_tasks_router.get("/status")
async def status_handler():
    return jobs


@background_tasks_router.post("/request/{uid}", status_code=HTTPStatus.ACCEPTED)
async def request_API(uid: UUID, background_tasks: BackgroundTasks):
    new_task = Job(uid=uid)
    new_task.status = "in_queue"
    jobs[new_task.uid] = new_task
    background_tasks.add_task(process_request, new_task.uid)

    return new_task
