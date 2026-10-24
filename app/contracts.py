"""接口输出采用明确的响应模型，避免新增数据库字段被意外暴露。"""
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


class RemovalOut(Output):
    message: str


class ShareOut(Output):
    id: str
    versionId: str
    recipientId: str
    username: str
    active: bool
    editRevision: int
    createdAt: str
    revokedAt: str | None = None


class SharedVersionOut(Output):
    version: VersionOut
    owner: str


class BankOut(Output):
    id: str
    name: str
    archived: bool
    editRevision: int
    createdAt: str
    updatedAt: str


class BankItemOut(Output):
    id: str
    bankId: str
    questionId: str
    selectedVersionId: str
    editRevision: int
    accessible: bool
    selectable: bool
    version: VersionOut | None
    createdAt: str
    updatedAt: str


class UsageOut(Output):
    surveyId: str
    title: str
    status: str
    versionId: str
    questionIds: list[str]
    occurrenceCount: int


class UsagesOut(Output):
    scope: Literal["ownedSurveys"]
    items: list[UsageOut]
    skip: int
    limit: int
    hasMore: bool


class CrossCounts(Output):
    answerCount: int
    responseCount: int
    respondentCount: int


class CrossOptionOut(CrossCounts):
    id: str
    label: str


class CrossStatsOut(CrossCounts):
    versionId: str
    scope: Literal["ownedSurveys"]
    surveyIds: list[str]
    title: str
    kind: Literal["single", "multiple", "text", "number"]
    options: list[CrossOptionOut]
    average: str | None
    minimum: str | None
    maximum: str | None


class CrossContentOut(Output):
    entryId: str
    surveyId: str
    surveyTitle: str
    questionId: str
    value: str
    author: str
    submittedAt: str


class CrossContentsOut(Output):
    items: list[CrossContentOut]
    skip: int
    limit: int
    hasMore: bool


class DistributionRow(Output):
    value: str
    answerCount: int


class DistributionOut(Output):
    items: list[DistributionRow]
    skip: int
    limit: int
    hasMore: bool
