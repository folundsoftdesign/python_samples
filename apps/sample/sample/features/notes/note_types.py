from pydantic import BaseModel, Field
from sample.mixins import BaseIdMixin, OptionalMixin


class NoteKeys(BaseIdMixin):
    pass


class NoteBase(BaseModel):
    title: str = Field(..., description="The title of the note.")
    description: str | None = Field(
        None, description="A brief description of the note."
    )


class NoteCreate(NoteBase):
    pass


class NoteUpdate(NoteBase, OptionalMixin):
    pass


class Note(NoteKeys, NoteBase):
    pass
