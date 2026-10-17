"""Request models. Input is validated here, at the API boundary."""
from pydantic import BaseModel, Field


class AskRequest(BaseModel):
    question: str = Field(min_length=1, max_length=500)
    at: str | None = Field(default=None, max_length=10, description="YYYY-MM-DD or YYYY-MM for who_owns")


class BaselineRequest(BaseModel):
    question: str = Field(min_length=1, max_length=500)


class EventRequest(BaseModel):
    text: str | None = Field(default=None, max_length=2000)
    demo: bool = False
