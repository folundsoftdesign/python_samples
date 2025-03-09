from pydantic import BaseModel


class Health(BaseModel):
    success: bool
    python_env: str
    log_level: str
