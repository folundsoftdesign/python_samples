from collections.abc import AsyncIterator

from fastapi_pagination import Params
from fastapi_pagination.ext.beanie import paginate

from .note_model import NoteModel
from .note_types import Note, NoteCreate, NoteUpdate
from .notes_utils import PaginatedResponse, Pagination


class InstanceNotFoundError(Exception):
    pass


async def create_note(note: NoteCreate) -> Note:
    document = NoteModel(**note.model_dump())
    await document.insert()
    return Note(**document.model_dump())


async def get_note_by_id(id: str) -> Note:
    document = await NoteModel.get(id)
    if document is None:
        raise InstanceNotFoundError(f"Note with id {id} not found")
    return Note(**document.model_dump())


async def get_notes_paginated(params: Params) -> PaginatedResponse[Note]:
    paged_documents = await paginate(NoteModel.find(), params)
    notes = [Note(**document.model_dump()) for document in paged_documents.items]
    return PaginatedResponse(
        data=notes,
        pagination=Pagination(
            total_items=paged_documents.total,
            current_page=paged_documents.page,
            total_pages=paged_documents.pages,
            page_size=paged_documents.size,
        ),
    )


async def get_notes_iter() -> AsyncIterator[Note]:
    async for document in NoteModel.find():
        yield Note(**document.model_dump())


async def update_note_by_id(id: str, note_update: NoteUpdate) -> None:
    document = await NoteModel.get(id)
    if document is None:
        raise InstanceNotFoundError(f"Note with id {id} not found")
    updates = note_update.model_dump(exclude_none=True)
    for key, value in updates.items():
        setattr(document, key, value)
    await document.save()


async def delete_note_by_id(id: str) -> None:
    document = await NoteModel.get(id)
    if document is not None:
        await document.delete()
