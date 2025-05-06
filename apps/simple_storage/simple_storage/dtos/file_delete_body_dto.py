from typing import Annotated

from fastapi import Body
from pydantic import BaseModel


class FilesDeleteBody(BaseModel):
    bucket_name: Annotated[str, Body(..., min_length=1, max_length=255, regex="^[a-zA-Z0-9_-]+$")]
    filename: Annotated[str, Body(..., min_length=1, max_length=255)]
