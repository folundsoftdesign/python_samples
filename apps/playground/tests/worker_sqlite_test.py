# test_worker_sqllite.py

import asyncio
import uuid
from typing import Generator
from unittest.mock import (
    MagicMock,
    patch,  # Correct import here
)

import pytest
from fastapi.testclient import TestClient
from playground.worker_sqlite import (
    TaskPayload,
    TaskStatus,
    app,
    get_task_from_db,
    lifespan,
    update_task_status,
)
from sqlalchemy import create_engine
from sqlalchemy.orm import Session

engine = create_engine("sqlite:///:memory:")
TaskPayload.metadata.create_all(engine)


@pytest.fixture
def db() -> Generator:
    with Session(engine) as session:
        yield session


@pytest.fixture
def client() -> Generator:
    with TestClient(app) as test_client:
        yield test_client


def create_task(db: Session, data: str, status: TaskStatus = TaskStatus.IN_QUEUE, cancelled: bool = False) -> TaskPayload:
    task = TaskPayload(data=data, status=status, cancelled=cancelled)
    db.add(task)
    db.commit()
    db.refresh(task)
    return task


@pytest.mark.asyncio
async def test_enqueue_gpu_task(client: TestClient, db: Session):
    response = client.post("/worker", json={"data": "test_data"})
    assert response.status_code == 200
    assert response.json()["message"].startswith("GPU task")
    tasks = db.query(TaskPayload).all()
    assert len(tasks) == 1
    assert tasks[0].data == "test_data"
    assert tasks[0].status == TaskStatus.IN_QUEUE


@pytest.mark.asyncio
async def test_get_tasks(client: TestClient, db: Session):
    create_task(db, "task1")
    create_task(db, "task2")
    response = client.get("/worker")
    assert response.status_code == 200
    tasks = response.json()
    assert len(tasks) == 2
    assert tasks[0]["data"] == "task1"
    assert tasks[1]["data"] == "task2"


@pytest.mark.asyncio
async def test_get_task(client: TestClient, db: Session):
    task = create_task(db, "test_task")
    response = client.get(f"/worker/{task.id}")
    assert response.status_code == 200
    assert response.json()["data"] == "test_task"


@pytest.mark.asyncio
async def test_get_task_not_found(client: TestClient):
    response = client.get(f"/worker/{uuid.uuid4()}")
    assert response.status_code == 404


@pytest.mark.asyncio
async def test_cancel_task(client: TestClient, db: Session):
    task = create_task(db, "cancel_task")
    response = client.post(f"/worker/{task.id}/cancel")
    assert response.status_code == 200
    updated_task = db.get(TaskPayload, task.id)
    assert updated_task is not None
    assert updated_task.cancelled is True


@pytest.mark.asyncio
async def test_cancel_task_not_found(client: TestClient):
    response = client.post(f"/worker/{uuid.uuid4()}/cancel")
    assert response.status_code == 404


@pytest.mark.asyncio
async def test_cancel_task_invalid_status(client: TestClient, db: Session):
    task = create_task(db, "invalid_cancel", status=TaskStatus.SUCCESS)
    response = client.post(f"/worker/{task.id}/cancel")
    assert response.status_code == 400


@pytest.mark.asyncio
async def test_get_task_from_db(db: Session):
    task = create_task(db, "db_task")
    retrieved_task = get_task_from_db(db, task.id)
    assert retrieved_task == task


@pytest.mark.asyncio
async def test_update_task_status(db: Session):
    task = create_task(db, "status_task")
    update_task_status(db, task, TaskStatus.IN_PROGRESS)
    updated_task = db.get(TaskPayload, task.id)
    assert updated_task is not None
    assert updated_task.status == TaskStatus.IN_PROGRESS


@pytest.mark.asyncio
async def test_update_task_status_with_error(db: Session):
    task = create_task(db, "error_task")
    update_task_status(db, task, TaskStatus.FAILED, "test error")
    updated_task = db.get(TaskPayload, task.id)
    assert updated_task is not None
    assert updated_task.status == TaskStatus.FAILED
    assert updated_task.error_message == "test error"


@pytest.mark.asyncio
async def test_process_task_success(db: Session):
    task = create_task(db, "process_success")
    with patch("main.do_something", new_callable=MagicMock) as mock_do_something:  # change here
        mock_do_something.return_value = asyncio.Future()
        mock_do_something.return_value.set_result(None)
        await app.extra["task_group"].start(app.extra["process_task"], task.id)
        await asyncio.sleep(0.1)
        updated_task = db.get(TaskPayload, task.id)
        assert updated_task is not None
        assert updated_task.status == TaskStatus.SUCCESS


@pytest.mark.asyncio
async def test_process_task_cancelled(db: Session):
    task = create_task(db, "process_cancelled", cancelled=True)
    await app.extra["task_group"].start(app.extra["process_task"], task.id)
    await asyncio.sleep(0.1)
    updated_task = db.get(TaskPayload, task.id)
    assert updated_task is not None
    assert updated_task.status == TaskStatus.CANCELLED


@pytest.mark.asyncio
async def test_process_task_db_error(db: Session):
    task = create_task(db, "process_db_error")
    with patch("playground.worker_sqlite.Session.commit", side_effect=Exception("DB Error")):
        await app.extra["task_group"].start(app.extra["process_task"], task.id)
        await asyncio.sleep(0.1)
        updated_task = db.get(TaskPayload, task.id)
        assert updated_task is not None
        assert updated_task.status == TaskStatus.FAILED


@pytest.mark.asyncio
async def test_process_task_unexpected_error(db: Session):
    task = create_task(db, "process_unexpected_error")
    with patch("playground.worker_sqlite.do_something", side_effect=Exception("Unexpected Error")):
        async with lifespan(app):  # start the lifespan
            await app.extra["task_group"].start(app.extra["process_task"], task.id)
            await asyncio.sleep(0.1)
            updated_task = db.get(TaskPayload, task.id)
            assert updated_task is not None
            assert updated_task.status == TaskStatus.FAILED
