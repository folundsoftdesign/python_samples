from collections.abc import AsyncIterator
from enum import StrEnum
from typing import Any, Generic, TypeVar

from pydantic import BaseModel, Field, model_serializer

T = TypeVar("T", bound=BaseModel)


class Pagination(BaseModel):
    total_items: int
    current_page: int
    total_pages: int
    page_size: int


class PaginatedResponse(BaseModel, Generic[T]):
    pagination: Pagination
    data: list[T]


class SuccessResponse(BaseModel, Generic[T]):
    success: bool = True
    data: T | list[T] | None = None
    pagination: Pagination | None = None

    # Using the model_serializer to transform the response
    # Remove the pagination property if it is None from the response
    @model_serializer(mode="wrap")
    def ser_model(self, handler) -> dict[str, Any]:
        result = handler(self)
        if "pagination" in result and result["pagination"] is None:
            del result["pagination"]
        return result


class FormatEnum(StrEnum):
    json = "json"
    jsonl = "jsonl"


class FormatParam(BaseModel):
    format: FormatEnum = Field(FormatEnum.json, description="Output format")


async def generate_response(output_format: FormatEnum, iterator: AsyncIterator[T]) -> tuple[AsyncIterator[str], str]:
    if output_format == FormatEnum.json:

        async def json_generator(iterator: AsyncIterator[T]) -> AsyncIterator[str]:
            yield '{ "success": true, "data": ['
            items = [item.model_dump_json() async for item in iterator]
            yield ",".join(items)
            yield "]}"

        generator = json_generator(iterator)
        media_type = "application/json"
        return generator, media_type

    if output_format == FormatEnum.jsonl:

        async def jsonl_generator(iterator: AsyncIterator[T]) -> AsyncIterator[str]:
            async for item in iterator:
                yield item.model_dump_json() + "\n"

        generator = jsonl_generator(iterator)
        media_type = "application/x-ndjson"
        return generator, media_type

    raise ValueError(f"Unsupported output format: {output_format}")
