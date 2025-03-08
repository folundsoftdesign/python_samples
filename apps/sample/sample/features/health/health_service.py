from sample.core import settings

from .health_type import Health


def health_service() -> Health:
    python_env: str = settings.python_env

    success: bool = True

    return Health(success=success, python_env=python_env, log_level=settings.log_level)
