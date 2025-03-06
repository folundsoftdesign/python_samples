from sample.core import settings
from sample.core.logger import logger

from .health_type import Health


def health_service() -> Health:
    python_env: str = settings.python_env

    success: bool = True

    logger.debug("Health check successful", extra={"python_env": python_env})

    return Health(success=success, python_env=python_env, log_level=settings.log_level)
