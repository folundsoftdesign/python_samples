from fastapi import APIRouter, Depends, HTTPException
from fastapi.responses import StreamingResponse
from fastapi_pagination import Params
from pydantic import ValidationError

from .note_types import Note, NoteCreate, NoteUpdate
from .notes_service import (
    InstanceNotFoundError,
    create_note,
    delete_note_by_id,
    get_note_by_id,
    get_notes_iter,
    get_notes_paginated,
    update_note_by_id,
)
from .notes_utils import FormatParam, SuccessResponse, generate_response

router = APIRouter(prefix="/notes")


@router.post("")
async def create(note: NoteCreate) -> SuccessResponse[Note]:
    new_note = await create_note(note)
    return SuccessResponse(data=new_note)


@router.get("/iter")
async def route_get_notes_iter(params: FormatParam = Depends()) -> StreamingResponse:
    generator, media_type = await generate_response(params.format, get_notes_iter())
    return StreamingResponse(generator, media_type=media_type)


@router.get("/{id}", response_model_exclude_none=True)
async def get_by_id(id: str) -> SuccessResponse[Note]:
    try:
        note = await get_note_by_id(id)
        return SuccessResponse(data=note)
    except InstanceNotFoundError as exc:
        raise HTTPException(status_code=404, detail="Instance not found") from exc
    except ValidationError as exc:
        raise HTTPException(status_code=400, detail="Validation error") from exc


@router.get("")
async def route_get_notes(params: Params = Depends()) -> SuccessResponse[Note]:
    paginated_response = await get_notes_paginated(params)
    return SuccessResponse(data=paginated_response.data, pagination=paginated_response.pagination)


@router.put("/{id}", status_code=204)
async def update_by_id(id: str, note: NoteUpdate) -> None:
    try:
        await update_note_by_id(id, note)
    except InstanceNotFoundError as exc:
        raise HTTPException(status_code=404, detail="Instance not found") from exc
    except ValidationError as exc:
        raise HTTPException(status_code=400, detail="Validation error") from exc


@router.delete("/{id}", status_code=204)
async def delete_by_id(id: str) -> None:
    try:
        await delete_note_by_id(id)
    except ValidationError as exc:
        raise HTTPException(status_code=400, detail="Validation error") from exc
