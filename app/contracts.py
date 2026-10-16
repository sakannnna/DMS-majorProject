"""Public response boundary. Never expose newly added storage fields implicitly."""
from typing import Annotated, Literal

from pydantic import BaseModel, ConfigDict, Field

from .models import Option, Question


class Output(BaseModel):
    model_config = ConfigDict(extra="ignore")


class MessageOut(Output):
    message: str


class UserOut(Output):
    id: str
    username: str


class SessionOut(Output):
    user: UserOut | None
    csrf: str


class LoginOut(Output):
    username: str


class SurveySummaryOut(Output):
    id: str
    ownerId: str
    token: str
    title: str
    description: str
    deadline: str | None
    allowAnonymous: bool
    allowMultiple: bool
    status: Literal["draft", "published", "closed"]
    editRevision: int
    definitionVersion: int
    schemaVersion: int
    createdAt: str
    updatedAt: str


class SurveyOut(SurveySummaryOut):
    questions: list[Question]


class PreviewSurveyOut(Output):
    title: str
    description: str
    questions: list[Question]
    allowAnonymous: bool
    allowMultiple: bool


class FillOut(PreviewSurveyOut):
    deadline: str | None
    definitionVersion: int


class WalkOut(Output):
    path: list[str]
    nextQuestionId: str | None
    ready: bool


class PreviewOut(Output):
    survey: PreviewSurveyOut
    walk: WalkOut


class SubmitOut(MessageOut):
    responseId: str
    replayed: bool


class OptionCountOut(Option):
    count: int


class StatsBase(Output):
    questionId: str
    title: str
    answered: int


class ChoiceStatsOut(StatsBase):
    kind: Literal["single", "multiple"]
    options: list[OptionCountOut]


class ContentOut(Output):
    value: str
    author: str
    submittedAt: str


class TextStatsOut(StatsBase):
    kind: Literal["text"]
    contents: list[ContentOut]
    skip: int
    limit: int
    hasMore: bool


class NumberStatsOut(TextStatsOut):
    kind: Literal["number"]
    average: str | None


QuestionStatsOut = Annotated[ChoiceStatsOut | TextStatsOut | NumberStatsOut, Field(discriminator="kind")]


class StatsOut(Output):
    total: int
    questions: list[QuestionStatsOut]


class ValidationIssueOut(Output):
    loc: list[str | int]
    msg: str


class ErrorOut(Output):
    detail: str | list[ValidationIssueOut]
