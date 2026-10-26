"""Shared boundary contracts for evidence-grounded extraction and profile validation."""

from datetime import datetime
from typing import Annotated, Literal, Self

from pydantic import BaseModel, ConfigDict, Field, model_validator

Text = Annotated[str, Field(min_length=1, pattern=r"\S")]
Digest = Annotated[str, Field(pattern=r"^[0-9a-f]{64}$")]


class Model(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)


class Artifact(Model):
    artifact_id: Text
    path: Text
    sha256: Digest
    version: Text
    kind: Literal["protocol", "rule", "registry", "terminology", "input", "output"]


class SourceDocument(Model):
    artifact: Artifact
    synthetic: bool

    @model_validator(mode="after")
    def source_kind(self) -> Self:
        if self.artifact.kind != "protocol":
            raise ValueError("source documents must identify protocol artifacts")
        return self


class Evidence(Model):
    document_id: Text
    pdf_page_index: Annotated[int, Field(ge=0)]
    printed_page: Text | None = None
    quote: Text
    extraction_status: Literal["proposed", "reviewed"]


class FactReview(Model):
    reviewer: Text
    reviewed_at: datetime
    action: Literal["approve", "correct", "reject"]
    approved_value: Text | None
    rationale: Text

    @model_validator(mode="after")
    def check_value(self) -> Self:
        if (self.action == "reject") != (self.approved_value is None):
            raise ValueError("approve/correct requires a value; reject requires no value")
        return self


class StudyFact(Model):
    fact_id: Text
    raw_statement: Text
    proposed_value: Text | None
    evidence: tuple[Evidence, ...] = Field(min_length=1)
    reviews: tuple[FactReview, ...] = ()

    @model_validator(mode="after")
    def review_history(self) -> Self:
        times = [review.reviewed_at for review in self.reviews]
        if any(t.tzinfo is None for t in times):
            raise ValueError("review timestamps must include a timezone")
        if times != sorted(times):
            raise ValueError("reviews must be in chronological order")
        for review in self.reviews:
            if review.action == "approve" and review.approved_value != self.proposed_value:
                raise ValueError("use correct to change a proposed fact value")
        return self

    @property
    def approved_value(self) -> str | None:
        return self.reviews[-1].approved_value if self.reviews else None
