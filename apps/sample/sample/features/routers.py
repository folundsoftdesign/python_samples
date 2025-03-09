from fastapi import APIRouter

from sample.features import background_tasks, health, notes

api_router = APIRouter()
api_router.include_router(health.router)
api_router.include_router(notes.router)
api_router.include_router(background_tasks.router)
