import uuid
from contextlib import asynccontextmanager
from typing import Tuple

import anyio
from anyio.streams.memory import MemoryObjectReceiveStream, MemoryObjectSendStream
from fastapi import APIRouter, FastAPI
from sqlmodel import Field, Session, SQLModel, create_engine

router = APIRouter()

# Router-specific state
send_receive_streams: Tuple[MemoryObjectSendStream[uuid.UUID], MemoryObjectReceiveStream[uuid.UUID]] = (
    anyio.create_memory_object_stream()
)
send_stream, receive_stream = send_receive_streams
task_lock = anyio.Lock()


class TaskPayload(SQLModel, table=True):
    id: uuid.UUID = Field(default_factory=uuid.uuid4, primary_key=True)
    data: str
    status: str = Field(default="in_queue")  # in_queue, in_progress, success, failed


sqlite_file_name = "test.db"
sqlite_url = f"sqlite:///{sqlite_file_name}"


engine = create_engine(sqlite_url, echo=True)

SQLModel.metadata.create_all(engine)


async def process_gpu_task(task_id: uuid.UUID):
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
        async with task_lock:
            await process_gpu_task(task_id)


@router.post("/gpu_task")
async def enqueue_gpu_task(task: TaskPayload):
    with Session(engine) as session:
        session.add(task)
        session.commit()
    await send_stream.send(task.id)
    return {"message": f"GPU task {task.id} enqueued"}


@asynccontextmanager
async def lifespan(app: FastAPI):
    task_group = anyio.create_task_group()
    async with task_group:
        task_group.start_soon(worker)
        yield
        task_group.cancel_scope.cancel()


app = FastAPI(lifespan=lifespan)
app.include_router(router)
