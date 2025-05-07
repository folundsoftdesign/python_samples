# test_worker_sqllite.py

import uuid
from collections.abc import Generator

import pytest
from fastapi.testclient import TestClient
from simple_worker.app import (
    TaskPayload,
    TaskStatus,
    app,
    get_task_from_db,
    update_task_status,
)
from sqlmodel import Session, create_engine, select

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
    create_task(db, "test_data")
    response = client.post("/worker", json={"data": {"say_hello": "Hello, World!"}})
    assert response.status_code == 200
    assert response.json()["message"].startswith("Task")
    tasks = db.exec(select(TaskPayload)).all()
    assert len(tasks) == 1
    assert tasks[0].data == "test_data"
    assert tasks[0].status == TaskStatus.IN_QUEUE


@pytest.mark.asyncio
async def test_get_task_not_found(client: TestClient):
    response = client.get(f"/worker/{uuid.uuid4()}")
    assert response.status_code == 404


@pytest.mark.asyncio
async def test_cancel_task_not_found(client: TestClient):
    response = client.post(f"/worker/{uuid.uuid4()}/cancel")
    assert response.status_code == 404


@pytest.mark.asyncio
async def test_get_task_from_db(db: Session):
    task = create_task(db, "db_task")
    retrieved_task = get_task_from_db(db, task.task_id)
    assert retrieved_task == task


@pytest.mark.asyncio
async def test_update_task_status(db: Session):
    task = create_task(db, "status_task")
    update_task_status(db, task, TaskStatus.IN_PROGRESS)
    updated_task = db.get(TaskPayload, task.task_id)
    assert updated_task is not None
    assert updated_task.status == TaskStatus.IN_PROGRESS


@pytest.mark.asyncio
async def test_update_task_status_with_error(db: Session):
    task = create_task(db, "error_task")
    update_task_status(db, task, TaskStatus.FAILED, "test error")
    updated_task = db.get(TaskPayload, task.task_id)
    assert updated_task is not None
    assert updated_task.status == TaskStatus.FAILED
    assert updated_task.error_message == "test error"
