from typing import Annotated

from pydantic import BaseModel, StringConstraints


class TokenRequest(BaseModel):
    tenant_id: Annotated[str, StringConstraints(min_length=1, max_length=255, pattern="^[a-zA-Z0-9_-]+$")]
