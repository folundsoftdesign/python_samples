import uuid
from contextlib import asynccontextmanager
from typing import Tuple

import anyio
from anyio.streams.memory import MemoryObjectReceiveStream, MemoryObjectSendStream
from fastapi import APIRouter, FastAPI

router = APIRouter()

# Router-specific state
send_receive_streams: Tuple[MemoryObjectSendStream[uuid.UUID], MemoryObjectReceiveStream[uuid.UUID]] = (
    anyio.create_memory_object_stream()
)
send_stream, receive_stream = send_receive_streams
task_lock = anyio.Lock()


async def process_gpu_task(task_id: uuid.UUID):
    try:
        print(f"GPU task {task_id} started")
        await anyio.sleep(5)  # Simulate GPU processing
        print(f"GPU task {task_id} completed")
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


@router.post("/gpu_task/{task_id}")
async def enqueue_gpu_task(task_id: uuid.UUID):
    await send_stream.send(task_id)
    return {"message": f"GPU task {task_id} enqueued"}


@asynccontextmanager
async def lifespan(app: FastAPI):
    task_group = anyio.create_task_group()
    async with task_group:
        task_group.start_soon(worker)
        yield
        task_group.cancel_scope.cancel()


app = FastAPI(lifespan=lifespan)
app.include_router(router)
