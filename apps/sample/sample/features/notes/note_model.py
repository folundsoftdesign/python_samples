import pymongo
from beanie import Document
from sample.mixins.timestamp_model_mixin import TimestampMixin

from .note_types import NoteBase


class NoteModel(TimestampMixin, NoteBase, Document):
    class Settings:
        name = "notes"
        indexes = [["title", pymongo.TEXT]]
