from contextlib import suppress
from typing import Any

from pydantic import BaseModel, PydanticUndefinedAnnotation


class OptionalMixin(BaseModel):
    """
    A Pydantic model mixin that sets all fields to be optional by default.

    This mixin modifies the Pydantic model initialization process to set the default value of all fields to None.
    It also attempts to rebuild the model if there are any undefined annotations.

    Methods
    -------
    __pydantic_init_subclass__(cls, **kwargs: Any) -> None
        Initializes the subclass by setting all fields' default values to None and rebuilding the model if necessary.
    """

    @classmethod
    def __pydantic_init_subclass__(cls, **kwargs: Any) -> None:
        super().__pydantic_init_subclass__(**kwargs)

        for field in cls.model_fields.values():
            field.default = None

        with suppress(PydanticUndefinedAnnotation):
            cls.model_rebuild(force=True)
