from beanie import Document

from sample.features.notes.note_model import NoteModel

__beanie_models__: list[type[Document]] = [NoteModel]
