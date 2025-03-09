from fastapi import APIRouter, HTTPException

from .services import health_service
from .types import Health

router = APIRouter(prefix="/health")


@router.get("")
def health() -> Health:
    health_response = health_service()
    if not health_response.success:
        raise HTTPException(status_code=500, detail="Health check failed")

    return health_response
