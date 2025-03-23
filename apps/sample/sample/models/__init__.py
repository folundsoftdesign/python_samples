from beanie import Document
from sqlmodel import SQLModel

from sample.features.notes.note_model import NoteModel

from .job_lock_beanie import JobLock

from .sql_models import BackgroundJob

__beanie_models__: list[type[Document]] = [NoteModel, JobLock]

__sql_models__: list[type[SQLModel]] = [BackgroundJob]
