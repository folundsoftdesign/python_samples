from typing import ClassVar

from pydantic import BaseModel, model_validator


class BaseIdMixin(BaseModel):
    """
    A base model that includes an 'id' field and ensures the 'id' is always a string.

    Attributes:
        id (str): The unique identifier for the model.
    """

    id: str

    @model_validator(mode="before")
    def convert_id(self, values):
        if "id" in values:
            values["id"] = str(values["id"])
            return values

        return None

    class Settings:
        projection: ClassVar[dict[str, str]] = {"id": "$_id"}
