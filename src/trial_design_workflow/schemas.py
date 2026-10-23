"""Validated boundary contracts; review metadata never enters the TS record."""

from datetime import datetime
from typing import Annotated, Literal, Self

from pydantic import BaseModel, ConfigDict, Field, model_validator

Text = Annotated[str, Field(min_length=1, pattern=r"\S")]
Digest = Annotated[str, Field(pattern=r"^[0-9a-f]{64}$")]
State = Literal["include", "exclude", "needs_review", "needs_external_source", "unsupported"]


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


class Rule(Model):
    rule_id: Text
    artifact_id: Text
    section: Text
    provenance: Literal["synthetic", "cdisc", "regulatory", "sponsor", "study"]
    description: Text


class Parameter(Model):
    code: Annotated[str, Field(pattern=r"^[A-Z][A-Z0-9_]{0,7}$")]
    label: Text
    fact_id: Text
    rule_id: Text
    automation: Literal["approved_fact", "manual", "external", "unsupported"]
    applicability: Literal["review", "exclude"]
    derivation: Literal["copy_approved_fact"]
    source_requirement: Literal["protocol", "external"]
    response_codelist: Text | None


class Registry(Model):
    artifact: Artifact
    scope: Literal["synthetic_test_only"]
    completeness: Literal["synthetic_subset_not_authoritative"]
    parameters: tuple[Parameter, ...] = Field(min_length=1)
    rules: tuple[Rule, ...] = Field(min_length=1)
    rule_artifacts: tuple[Artifact, ...] = Field(min_length=1)
    # Engineering limits supplied by the caller, not claimed CDISC limits.
    field_limits: dict[str, Annotated[int, Field(gt=0)]]
    long_text_policy: Literal["block_for_review"]

    @model_validator(mode="after")
    def references(self) -> Self:
        codes = [parameter.code for parameter in self.parameters]
        rule_ids = [rule.rule_id for rule in self.rules]
        artifact_ids = [artifact.artifact_id for artifact in self.rule_artifacts]
        for ids in (codes, rule_ids, artifact_ids):
            if len(ids) != len(set(ids)):
                raise ValueError("registry identifiers must be unique")
        if any(p.rule_id not in rule_ids for p in self.parameters):
            raise ValueError("parameter references an unknown rule")
        if any(r.artifact_id not in artifact_ids for r in self.rules):
            raise ValueError("rule references an unknown source artifact")
        if any(r.provenance != "synthetic" for r in self.rules):
            raise ValueError("Milestone 1 accepts synthetic rules only")
        if set(self.field_limits) != {"STUDYID", "TSPARMCD", "TSPARM", "TSVAL"}:
            raise ValueError("explicit limits required for every supported TS text field")
        return self


class Term(Model):
    codelist: Text
    code: Text
    value: Text


class Terminology(Model):
    artifact: Artifact
    synthetic: Literal[True]
    terms: tuple[Term, ...]

    @model_validator(mode="after")
    def unique_terms(self) -> Self:
        keys = [(t.codelist, t.value) for t in self.terms]
        codes = [(t.codelist, t.code) for t in self.terms]
        if len(set(keys)) != len(keys) or len(set(codes)) != len(codes):
            raise ValueError("terminology mappings must be unambiguous")
        return self


class Decision(Model):
    parameter_code: Text
    state: State
    rationale: Text
    rule_id: Text
    fact_id: Text
    value: Text | None
    term: Term | None = None
    terminology_artifact_id: Text | None = None

    @model_validator(mode="after")
    def included_value(self) -> Self:
        if self.state == "include" and self.value is None:
            raise ValueError("included decisions require a value")
        return self


class DecisionReview(Model):
    parameter_code: Text
    proposal_sha256: Digest
    reviewer: Text
    reviewed_at: datetime
    action: Literal["approve", "reject"]
    rationale: Text

    @model_validator(mode="after")
    def timezone_required(self) -> Self:
        if self.reviewed_at.tzinfo is None:
            raise ValueError("review timestamps must include a timezone")
        return self


class RunInput(Model):
    study_id: Text
    documents: tuple[SourceDocument, ...]
    facts: tuple[StudyFact, ...]
    registry: Registry
    terminology: Terminology
    decision_reviews: tuple[DecisionReview, ...] = ()

    @model_validator(mode="after")
    def references(self) -> Self:
        artifacts = (
            *(d.artifact for d in self.documents),
            self.registry.artifact,
            *self.registry.rule_artifacts,
            self.terminology.artifact,
        )
        artifact_ids = [a.artifact_id for a in artifacts]
        if len(artifact_ids) != len(set(artifact_ids)):
            raise ValueError("material artifact identifiers must be globally unique")
        if (
            self.registry.artifact.kind != "registry"
            or self.terminology.artifact.kind != "terminology"
            or any(a.kind != "rule" for a in self.registry.rule_artifacts)
        ):
            raise ValueError("material artifact kinds must match their selected roles")
        doc_ids = [d.artifact.artifact_id for d in self.documents]
        fact_ids = [f.fact_id for f in self.facts]
        if len(doc_ids) != len(set(doc_ids)) or len(fact_ids) != len(set(fact_ids)):
            raise ValueError("document and fact identifiers must be unique")
        if any(not d.synthetic for d in self.documents):
            raise ValueError("Milestone 1 accepts synthetic documents only")
        if any(e.document_id not in doc_ids for f in self.facts for e in f.evidence):
            raise ValueError("evidence references an unknown document")
        codes = {p.code for p in self.registry.parameters}
        if any(r.parameter_code not in codes for r in self.decision_reviews):
            raise ValueError("review references an unknown parameter")
        times = [r.reviewed_at for r in self.decision_reviews]
        if times != sorted(times):
            raise ValueError("decision reviews must be in chronological order")
        return self


class TSRecord(Model):
    STUDYID: Text
    DOMAIN: Literal["TS"] = "TS"
    TSSEQ: Annotated[int, Field(gt=0, strict=True)]
    TSPARMCD: Text
    TSPARM: Text
    TSVAL: Text


class Trace(Model):
    sequence: Annotated[int, Field(gt=0)]
    parameter_code: Text
    proposal_sha256: Digest
    fact_id: Text
    evidence: tuple[Evidence, ...] = Field(min_length=1)
    fact_review: FactReview
    decision_review: DecisionReview
    rule: Rule
    term: Term | None
    terminology_artifact_id: Text | None


class Finding(Model):
    code: Text
    severity: Literal["error", "warning", "info"]
    status: Literal["open", "resolved"] = "open"
    parameter_code: Text | None = None
    message: Text


class RunOutput(Model):
    proposals: tuple[Decision, ...]
    records: tuple[TSRecord, ...]
    traceability: tuple[Trace, ...]
    findings: tuple[Finding, ...]


class Manifest(Model):
    software_version: Text
    generated_at: datetime
    mode: Literal["synthetic_test_only"]
    standards_status: Literal["not_loaded"]
    inputs: tuple[Artifact, ...]
    outputs: tuple[Artifact, ...]
    logical_records_sha256: Digest
