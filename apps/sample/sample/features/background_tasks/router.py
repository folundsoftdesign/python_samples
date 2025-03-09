import time
from http import HTTPStatus
from typing import Dict
from uuid import UUID

import anyio
from fastapi import APIRouter, BackgroundTasks
from pydantic import BaseModel

from sample.core import logger


class Job(BaseModel):
    uid: UUID
    status: str = "in_progress"


router = APIRouter(prefix="/background_tasks")

jobs: Dict[UUID, Job] = {}


async def process_gpu_task(task_id: int):
    try:
        print(f"GPU task {task_id} started")
        await anyio.sleep(5)  # Simulate GPU processing
        print(f"GPU task {task_id} completed")
    except Exception as e:
        print(f"Error processing GPU task {task_id}: {e}")
        # Add any exception handling logic here (e.g., logging)
    finally:
        # The lock is released when the 'async with' block exits, not explicitly in the finally block.
        pass  # this finally is now redundant, but kept for clarity.


def mock_function(id_job) -> str:
    jobs[id_job].status = "in_progress"
    time.sleep(5)
    return "done"


def process_request(job_id):
    response = mock_function(job_id)
    logger.info(f"Job {job_id} completed and returned {response}")
    jobs[job_id].status = "complete"


@router.get("/status")
async def status_handler():
    return jobs


@router.post("/request/{uid}", status_code=HTTPStatus.ACCEPTED)
async def request_API(uid: UUID, background_tasks: BackgroundTasks):
    new_task = Job(uid=uid)
    new_task.status = "in_queue"
    jobs[new_task.uid] = new_task
    background_tasks.add_task(process_request, new_task.uid)

    return new_task
