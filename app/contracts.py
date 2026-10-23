"""Public response boundary. Never expose newly added storage fields implicitly."""
from typing import Annotated, Literal

from pydantic import BaseModel, ConfigDict, Field

from .models import Option, Question, ManagedQuestion, QuestionContent


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
    questions: list[ManagedQuestion]
    idMap: dict[str, str] = Field(default_factory=dict)


class PublicQuestion(Question):
    model_config = ConfigDict(extra="ignore")


class PreviewSurveyOut(Output):
    title: str
    description: str
    questions: list[PublicQuestion]
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
    respondentCount: int


class StatsBase(Output):
    questionId: str
    title: str
    answered: int
    respondentCount: int


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
    respondentCount: int
    questions: list[QuestionStatsOut]


class ValidationIssueOut(Output):
    loc: list[str | int]
    msg: str


class ErrorOut(Output):
    detail: str | list[ValidationIssueOut]


class VersionOut(Output):
    id: str
    questionId: str
    versionNo: int
    parentVersionId: str | None
    content: QuestionContent
    createdAt: str


class DraftOut(Output):
    baseVersionId: str | None
    content: QuestionContent


class PendingOut(Output):
    operationId: str | None
    versionId: str | None
    versionNo: int | None
    content: QuestionContent | None
    needsRepair: bool


class ReusableOut(Output):
    id: str
    name: str
    archived: bool
    editRevision: int
    draft: DraftOut | None
    pendingSave: PendingOut | None
    latestVersion: VersionOut | None
    createdAt: str
    updatedAt: str


class HistoryNode(Output):
    versionId: str
    accessible: bool
    version: VersionOut | None = None


class HistoryOut(Output):
    nodes: list[HistoryNode]
    hasMore: bool
    nextVersionId: str | None
