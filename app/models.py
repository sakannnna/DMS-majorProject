from decimal import Decimal
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field


class InputModel(BaseModel):
    model_config = ConfigDict(extra="forbid")


class Credentials(InputModel):
    username: str = Field(min_length=2, max_length=40)
    password: str = Field(min_length=8, max_length=128)


class Option(InputModel):
    id: str = Field(pattern=r"^[a-zA-Z0-9_-]{1,64}$")
    label: str = Field(min_length=1, max_length=200)


class Validation(InputModel):
    minChoices: int | None = Field(default=None, ge=0, le=50)
    maxChoices: int | None = Field(default=None, ge=0, le=50)
    minLength: int | None = Field(default=None, ge=0, le=5000)
    maxLength: int | None = Field(default=None, ge=0, le=5000)
    minimum: Decimal | None = None
    maximum: Decimal | None = None
    integer: bool = False


class Condition(InputModel):
    op: Literal["eq", "ne", "gt", "gte", "lt", "lte", "any", "all"]
    value: str | list[str]


class Rule(InputModel):
    conditions: list[Condition] = Field(min_length=1, max_length=8)
    target: str = Field(min_length=1, max_length=64)


class Question(InputModel):
    id: str = Field(pattern=r"^[a-zA-Z0-9_-]{1,64}$")
    kind: Literal["single", "multiple", "text", "number"]
    title: str = Field(min_length=1, max_length=500)
    required: bool = True
    options: list[Option] = Field(default_factory=list, max_length=50)
    validation: Validation = Field(default_factory=Validation)
    jumpRules: list[Rule] = Field(default_factory=list, max_length=50)


class ManagedQuestion(Question):
    sourceQuestionId: str | None = None
    sourceVersionId: str | None = None


class SurveyInput(InputModel):
    title: str = Field(min_length=1, max_length=200)
    description: str = Field(default="", max_length=5000)
    allowAnonymous: bool = True
    allowMultiple: bool = False
    deadline: str | None = None
    questions: list[ManagedQuestion] = Field(default_factory=list, max_length=100)
    operationKey: str | None = Field(default=None, pattern=r"^[a-zA-Z0-9_-]{8,80}$")


class SurveyUpdate(SurveyInput):
    editRevision: int = Field(ge=1)


class MetadataUpdate(InputModel):
    editRevision: int = Field(ge=1)
    title: str = Field(min_length=1, max_length=200)
    description: str = Field(default="", max_length=5000)
    deadline: str | None = None


class Revision(InputModel):
    editRevision: int = Field(ge=1)


class Answer(InputModel):
    questionId: str
    value: str | list[str] | None


class WalkInput(InputModel):
    answers: list[Answer] = Field(default_factory=list, max_length=100)


class Submission(WalkInput):
    submissionKey: str = Field(pattern=r"^[a-zA-Z0-9_-]{8,80}$")
    anonymous: bool = True


class QuestionContent(InputModel):
    kind: Literal["single", "multiple", "text", "number"]
    title: str = Field(min_length=1, max_length=500)
    options: list[Option] = Field(default_factory=list, max_length=50)
    validation: Validation = Field(default_factory=Validation)


class QuestionDraft(InputModel):
    baseVersionId: str | None = None
    content: QuestionContent


class ReusableCreate(InputModel):
    name: str = Field(min_length=1, max_length=200)
    creationKey: str = Field(pattern=r"^[a-zA-Z0-9_-]{8,80}$")
    content: QuestionContent | None = None
    saveVersion: bool = True


class ReusableUpdate(Revision):
    name: str | None = Field(default=None, min_length=1, max_length=200)
    archived: bool | None = None
    draft: QuestionDraft | None = None


class VersionSave(QuestionDraft, Revision):
    creationKey: str = Field(pattern=r"^[a-zA-Z0-9_-]{8,80}$")


class RestoreVersion(Revision):
    versionId: str
    creationKey: str = Field(pattern=r"^[a-zA-Z0-9_-]{8,80}$")


class RecoverSave(Revision):
    operationId: str


class ExportQuestion(InputModel):
    operationKey: str = Field(pattern=r"^[a-zA-Z0-9_-]{8,80}$")
    name: str = Field(min_length=1, max_length=200)


class InstanceAdd(Revision):
    operationKey: str = Field(pattern=r"^[a-zA-Z0-9_-]{8,80}$")
    versionId: str
    required: bool = True


class InstanceUpgrade(Revision):
    operationKey: str = Field(pattern=r"^[a-zA-Z0-9_-]{8,80}$")
    versionId: str


class InstanceDelete(Revision):
    operationKey: str = Field(pattern=r"^[a-zA-Z0-9_-]{8,80}$")
    ruleUpdates: dict[str, list[Rule]] = Field(default_factory=dict, max_length=100)
