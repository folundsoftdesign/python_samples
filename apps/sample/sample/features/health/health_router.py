from fastapi import APIRouter, HTTPException

from .health_service import health_service
from .health_type import Health

health_router = APIRouter(prefix="/health")


@health_router.get("")
def health() -> Health:
    health_response = health_service()
    if not health_response.success:
        raise HTTPException(status_code=500, detail="Health check failed")

    return health_response
