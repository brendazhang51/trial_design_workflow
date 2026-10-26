"""Extraction contracts preserve evidence-bearing facts without granting approval."""

import re
from datetime import datetime
from typing import Annotated, Literal, Self, TypedDict

from pydantic import Field, model_validator

from ..schemas import Artifact, Digest, Model, SourceDocument, StudyFact, Text

Index = Annotated[int, Field(ge=0, strict=True)]


class ExtractionFinding(Model):
    code: Text
    severity: Literal["error", "warning", "info"]
    status: Literal["open", "resolved"] = "open"
    field_key: Text | None = None
    pdf_page_index: Index | None = None
    message: Text


class PrintedPageMarker(Model):
    page: Annotated[int, Field(gt=0, strict=True)]
    total: Annotated[int, Field(gt=0, strict=True)]
    start: Index
    end: Index
    quote: Text

    @model_validator(mode="after")
    def limits(self) -> Self:
        if self.page > self.total or self.end <= self.start:
            raise ValueError("invalid printed-page marker range")
        return self


class PageText(Model):
    pdf_page_index: Index
    text: str
    printed_page: Text | None
    page_number_status: Literal["proposed", "needs_review", "ambiguous"]
    printed_markers: tuple[PrintedPageMarker, ...]

    @model_validator(mode="after")
    def grounded_marker(self) -> Self:
        for marker in self.printed_markers:
            if marker.end > len(self.text) or self.text[marker.start : marker.end] != marker.quote:
                raise ValueError("printed marker is not grounded in page text")
        labels = {(m.page, m.total) for m in self.printed_markers}
        if self.page_number_status == "proposed":
            if len(labels) != 1 or self.printed_page != str(next(iter(labels))[0]):
                raise ValueError("proposed printed page requires one unambiguous marker")
        elif self.printed_page is not None:
            raise ValueError("unresolved printed page must not contain an inferred label")
        elif self.page_number_status == "ambiguous" and len(labels) < 2:
            raise ValueError("ambiguous page requires conflicting markers")
        elif self.page_number_status == "needs_review" and labels:
            raise ValueError("unresolved page must not discard an available marker")
        return self


class ParsedDocument(Model):
    source: SourceDocument
    parser_name: Literal["pypdf"]
    parser_version: Text
    extraction_mode: Literal["plain"]
    pages: tuple[PageText, ...] = Field(min_length=1)
    findings: tuple[ExtractionFinding, ...]

    @model_validator(mode="after")
    def contiguous_pages(self) -> Self:
        if [p.pdf_page_index for p in self.pages] != list(range(len(self.pages))):
            raise ValueError("document pages must be contiguous and zero-based")
        return self


class ExtractionRule(Model):
    rule_id: Text
    field_key: Annotated[str, Field(pattern=r"^[a-z][a-z0-9_]*$")]
    description: Text
    patterns: tuple[Text, ...] = Field(min_length=1)
    normalization: Literal["collapse_whitespace", "integer"]

    @model_validator(mode="after")
    def valid_regex(self) -> Self:
        for pattern in self.patterns:
            try:
                compiled = re.compile(pattern)
            except re.error as exc:
                raise ValueError("invalid extraction regex") from exc
            if "value" not in compiled.groupindex:
                raise ValueError("extraction pattern requires a named value group")
        return self


class ExtractionRules(Model):
    schema_version: Literal["1"]
    version: Text
    purpose: Literal["engineering_extraction_not_standard_mapping"]
    cross_page_policy: Literal["review_without_joining"]
    rules: tuple[ExtractionRule, ...] = Field(min_length=1)

    @model_validator(mode="after")
    def unique_fields(self) -> Self:
        for values in ([r.rule_id for r in self.rules], [r.field_key for r in self.rules]):
            if len(values) != len(set(values)):
                raise ValueError("extraction field and rule identifiers must be unique")
        return self


class EvidenceSpan(Model):
    pdf_page_index: Index
    start: Index
    end: Index

    @model_validator(mode="after")
    def nonempty(self) -> Self:
        if self.end <= self.start:
            raise ValueError("evidence span must be nonempty")
        return self


class FactCandidate(Model):
    candidate_id: Text
    field_key: Text
    rule_id: Text
    fact: StudyFact
    spans: tuple[EvidenceSpan, ...] = Field(min_length=1)

    @model_validator(mode="after")
    def unreviewed(self) -> Self:
        if self.fact.reviews or any(e.extraction_status != "proposed" for e in self.fact.evidence):
            raise ValueError("extraction providers cannot create human approvals")
        if self.fact.proposed_value is None:
            raise ValueError(
                "candidate must have a proposed value; represent missing fields in review"
            )
        if self.candidate_id != self.fact.fact_id or len(self.spans) != len(self.fact.evidence):
            raise ValueError("candidate identity and evidence spans must match the fact")
        if self.fact.raw_statement != self.fact.evidence[0].quote:
            raise ValueError("raw statement must preserve the first exact evidence quote")
        return self


class CandidateBatch(Model):
    schema_version: Literal["1"] = "1"
    candidates: tuple[FactCandidate, ...]


class CandidateResponse(TypedDict):
    """Versioned wire shape retained for compatibility providers."""

    schema_version: Literal["1"]
    candidates: list[dict[str, object]]


class FieldReview(Model):
    field_key: Text
    state: Literal["needs_review"] = "needs_review"
    reason: Literal["missing", "single_candidate", "conflicting_candidates"]
    candidate_ids: tuple[Text, ...]
    rationale: Text


class ExtractionOutput(Model):
    schema_version: Literal["1"]
    document: ParsedDocument
    rules: ExtractionRules
    provider_name: Text
    provider_version: Text
    candidates: tuple[FactCandidate, ...]
    review_queue: tuple[FieldReview, ...]
    findings: tuple[ExtractionFinding, ...]

    @model_validator(mode="after")
    def complete_review(self) -> Self:
        fields = [r.field_key for r in self.rules.rules]
        if sorted(r.field_key for r in self.review_queue) != sorted(fields):
            raise ValueError("every extraction field must appear exactly once in review")
        ids = [c.candidate_id for c in self.candidates]
        if len(ids) != len(set(ids)):
            raise ValueError("candidate identifiers must be unique")
        values = [(c.field_key, c.fact.proposed_value) for c in self.candidates]
        if len(values) != len(set(values)):
            raise ValueError("repeated values must be grouped into one evidence-bearing candidate")
        rules = {r.field_key: r.rule_id for r in self.rules.rules}
        for candidate in self.candidates:
            if rules.get(candidate.field_key) != candidate.rule_id:
                raise ValueError("candidate references an unknown field or rule")
            for evidence, span in zip(candidate.fact.evidence, candidate.spans, strict=True):
                if span.pdf_page_index >= len(self.document.pages):
                    raise ValueError("evidence references an unknown page")
                page = self.document.pages[span.pdf_page_index]
                if (
                    evidence.document_id != self.document.source.artifact.artifact_id
                    or evidence.pdf_page_index != span.pdf_page_index
                    or evidence.printed_page != page.printed_page
                    or span.end > len(page.text)
                    or page.text[span.start : span.end] != evidence.quote
                ):
                    raise ValueError("candidate evidence is not grounded in the source page")
        for review in self.review_queue:
            candidates = [c for c in self.candidates if c.field_key == review.field_key]
            if review.candidate_ids != tuple(c.candidate_id for c in candidates):
                raise ValueError("review queue must retain every candidate for its field")
            expected = (
                "missing"
                if not candidates
                else "single_candidate"
                if len(candidates) == 1
                else "conflicting_candidates"
            )
            if review.reason != expected:
                raise ValueError("review reason disagrees with candidate count")
        return self


class ExtractionManifest(Model):
    schema_version: Literal["1"]
    software_version: Text
    generated_at: datetime
    purpose: Literal["fact_proposals_for_human_review"]
    standards_status: Literal["not_loaded"]
    parser_name: Text
    parser_version: Text
    parser_settings: dict[str, str]
    provider_name: Text
    provider_version: Text
    python_version: Text
    inputs: tuple[Artifact, ...]
    outputs: tuple[Artifact, ...]
    logical_extraction_sha256: Digest
