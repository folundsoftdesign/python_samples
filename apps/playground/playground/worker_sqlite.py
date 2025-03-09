import uuid
from contextlib import asynccontextmanager
from pathlib import Path
from typing import Tuple

import anyio
from anyio.streams.memory import MemoryObjectReceiveStream, MemoryObjectSendStream
from fastapi import APIRouter, FastAPI, HTTPException
from sqlmodel import Field, Session, SQLModel, create_engine

router = APIRouter(prefix="/worker")

# Router-specific state
send_receive_streams: Tuple[MemoryObjectSendStream[uuid.UUID], MemoryObjectReceiveStream[uuid.UUID]] = (
    anyio.create_memory_object_stream()
)
send_stream, receive_stream = send_receive_streams
task_lock = anyio.Lock()
task_semaphore = anyio.Semaphore(1)  # create the semaphore

sqlite_file = Path(__file__).parent / "../data" / "playground.db"
sqlite_url = f"sqlite:///{sqlite_file}"

engine = create_engine(sqlite_url, echo=True)


class TaskPayload(SQLModel, table=True):
    id: uuid.UUID = Field(default_factory=uuid.uuid4, primary_key=True)
    data: str
    status: str = Field(default="in_queue")  # in_queue, in_progress, success, failed


SQLModel.metadata.create_all(engine)


async def process_gpu_task(task_id: uuid.UUID):
    async with task_semaphore:  # acquire the semaphore
        try:
            with Session(engine) as session:
                task_payload = session.get(TaskPayload, task_id)
                if task_payload:
                    task_payload.status = "in_progress"
                    session.add(task_payload)
                    session.commit()
                    print(f"GPU task {task_id} started")
                    await anyio.sleep(5)  # Simulate GPU processing
                    print(f"GPU task {task_id} completed")
                    task_payload.status = "success"
                    session.add(task_payload)
                    session.commit()
                else:
                    print(f"Task {task_id} not found")
        except Exception as e:
            print(f"Error processing GPU task {task_id}: {e}")
            # Add any exception handling logic here (e.g., logging)
        finally:
            # The lock will be released even if an exception occurs
            pass


async def worker():
    async for task_id in receive_stream:
        await process_gpu_task(task_id)  # Remove task group, because we want serial processing.


@router.post("")
async def enqueue_gpu_task(task: TaskPayload):
    with Session(engine) as session:
        session.add(task)
        session.commit()
        task_id = task.id
    await send_stream.send(task_id)
    return {"message": f"GPU task {task_id} enqueued"}


@router.get("")
async def get_status():
    with Session(engine) as session:
        tasks = session.query(TaskPayload).all()
        return {"tasks": tasks}


@router.get("/{task_id}")
async def get_task(task_id: uuid.UUID):
    with Session(engine) as session:
        task = session.get(TaskPayload, task_id)

        if not task:
            raise HTTPException(status_code=404, detail="Task not found")

        return task.model_dump()


@asynccontextmanager
async def lifespan(app: FastAPI):
    task_group = anyio.create_task_group()
    async with task_group:
        task_group.start_soon(worker)
        yield
        task_group.cancel_scope.cancel()


app = FastAPI(lifespan=lifespan)
app.include_router(router)
