"""Saved, grounded inputs for deterministic stages; no review/approval actions or transport."""

import io
import json
import re
from datetime import datetime
from pathlib import Path
from typing import Literal, Self

from pydantic import Field, model_validator
from pypdf import PdfReader
from pypdf.errors import PyPdfError

from .extraction.facts_models import FactKey, StudyFactsV2
from .extraction.models import PageText
from .extraction.pdf import parse_page
from .schemas import Digest, Model, Text
from .serialization import canonical_json, sha256
from .standards.profile import safe_path

SourceType = Literal["protocol", "study_data", "sponsor", "external"]


def digest(model: Model) -> str:
    return sha256(canonical_json(model.model_dump(mode="json")).encode())


class HumanReview(Model):
    reviewer_id: Text
    reviewed_at: datetime
    action: Literal["approve", "correct", "reject"]
    rationale: Text

    @model_validator(mode="after")
    def aware(self) -> Self:
        if self.reviewed_at.tzinfo is None:
            raise ValueError("review timestamp requires a timezone")
        return self


class Citation(Model):
    source_id: Text
    source_sha256: Digest
    pdf_page_index: int = Field(ge=0, strict=True)
    printed_page: Text | None = None
    start: int = Field(ge=0, strict=True)
    end: int = Field(gt=0, strict=True)
    quote: Text
    locator: Text

    @model_validator(mode="after")
    def span(self) -> Self:
        if self.end <= self.start:
            raise ValueError("citation range must be nonempty")
        return self


class SourceInput(Model):
    source_id: Text
    path: Text
    sha256: Digest
    version: Text
    source_type: SourceType
    format: Literal["pdf", "text", "json"]


class SourceSnapshot(Model):
    source_id: Text
    sha256: Digest
    version: Text
    source_type: SourceType
    format: Literal["pdf", "text", "json"]
    parser: Text
    pages: tuple[PageText, ...] = Field(min_length=1)

    @model_validator(mode="after")
    def pages_order(self) -> Self:
        if [p.pdf_page_index for p in self.pages] != list(range(len(self.pages))):
            raise ValueError("source pages must be contiguous and zero-based")
        if self.format in {"text", "json"} and (
            len(self.pages) != 1 or sha256(self.pages[0].text.encode()) != self.sha256
        ):
            raise ValueError("text/JSON snapshot hash does not match its source bytes")
        return self


class ExternalCoding(Model):
    source_id: Text
    record_pointer: Text


class DictionaryTerm(Model):
    code: Text
    value: Text
    reference: Text
    version: Text


class ContextFact(Model):
    fact_id: Text
    fact_key: FactKey
    cardinality_key: dict[FactKey, Text] = Field(default_factory=dict)
    source_type: SourceType
    raw_value: Text | None
    proposed_value: Text | None
    reviewed_value: Text | None = None
    unit: Text | None = None
    null_flavor: Text | None = None
    status: Literal["needs_review", "reviewed", "conflict", "rejected"]
    review: HumanReview | None = None
    evidence: tuple[Citation, ...] = ()
    coding: ExternalCoding | None = None
    proposal_id: Text | None = None
    proposal_sha256: Digest | None = None

    @model_validator(mode="after")
    def review_boundary(self) -> Self:
        if self.raw_value is not None and not self.evidence:
            raise ValueError("raw observations require evidence")
        if (self.proposal_id is None) != (self.proposal_sha256 is None):
            raise ValueError("proposal references require both ID and hash")
        if self.reviewed_value is not None and self.null_flavor is not None:
            raise ValueError("reviewed value and null flavor are mutually exclusive")
        if self.status == "reviewed":
            if self.review is None or self.review.action == "reject" or not self.evidence:
                raise ValueError("reviewed values require human review and source evidence")
            if self.reviewed_value is None and self.null_flavor is None:
                raise ValueError("reviewed facts require a value or explicit null-flavor proposal")
            if self.review.action == "approve" and (
                self.reviewed_value != self.proposed_value or self.null_flavor is not None
            ):
                raise ValueError("use correct for changed values or explicit null flavors")
        elif self.reviewed_value is not None or self.null_flavor is not None or self.coding:
            raise ValueError("unreviewed/rejected facts cannot carry usable values or codes")
        if self.status == "rejected" and (self.review is None or self.review.action != "reject"):
            raise ValueError("rejection requires an explicit human decision")
        if self.status in {"needs_review", "conflict"} and self.review is not None:
            raise ValueError("pending facts cannot contain a completed human decision")
        return self


class CollectionReview(Model):
    fact_key: FactKey
    review: HumanReview
    evidence: tuple[Citation, ...] = Field(min_length=1)

    @model_validator(mode="after")
    def complete(self) -> Self:
        if self.review.action == "reject":
            raise ValueError("collection completeness must be affirmatively reviewed")
        return self


class IdentityReview(Model):
    review: HumanReview
    evidence: tuple[Citation, ...] = Field(min_length=1)

    @model_validator(mode="after")
    def accepted(self) -> Self:
        if self.review.action == "reject":
            raise ValueError("study identity must be affirmatively reviewed")
        return self


class CuratedInputs(Model):
    schema_version: Literal["1"]
    purpose: Literal["human_curated_study_inputs"]
    study_id: Text
    identity_review: IdentityReview | None = None
    sources: tuple[SourceInput, ...]
    facts: tuple[ContextFact, ...]
    complete_collections: tuple[CollectionReview, ...] = ()
    source_proposals: StudyFactsV2 | None = None


class StudyContext(Model):
    schema_version: Literal["1"]
    purpose: Literal["validated_study_context"]
    study_id: Text
    identity_review: IdentityReview | None
    sources: tuple[SourceSnapshot, ...]
    facts: tuple[ContextFact, ...]
    complete_collections: tuple[CollectionReview, ...]
    source_proposals: StudyFactsV2 | None = None

    @model_validator(mode="after")
    def grounding(self) -> Self:
        for identifiers in (
            [s.source_id for s in self.sources],
            [f.fact_id for f in self.facts],
            [c.fact_key for c in self.complete_collections],
        ):
            if len(identifiers) != len(set(identifiers)):
                raise ValueError("duplicate context source, fact or collection identifiers")
        sources = {s.source_id: s for s in self.sources}

        def check(citation: Citation) -> SourceSnapshot:
            source = sources.get(citation.source_id)
            if source is None or source.sha256 != citation.source_sha256:
                raise ValueError("citation source/hash mismatch")
            if citation.pdf_page_index >= len(source.pages):
                raise ValueError("unknown citation page")
            page = source.pages[citation.pdf_page_index]
            if (
                citation.end > len(page.text)
                or page.text[citation.start : citation.end] != citation.quote
                or page.printed_page != citation.printed_page
            ):
                raise ValueError("citation is not grounded in the saved source")
            return source

        proposals = (
            {f.fact_id: f for f in self.source_proposals.facts} if self.source_proposals else {}
        )
        for fact in self.facts:
            for citation in fact.evidence:
                if check(citation).source_type != fact.source_type:
                    raise ValueError("fact/source types disagree")
            for literal in (fact.raw_value, fact.unit, *fact.cardinality_key.values()):
                if literal is not None and not any(literal in c.quote for c in fact.evidence):
                    raise ValueError("raw value, unit or association is not in the cited source")
            if fact.proposal_id is not None:
                proposal = proposals.get(fact.proposal_id)
                if proposal is None or (
                    proposal.proposal_sha256 != fact.proposal_sha256
                    or proposal.fact_key != fact.fact_key
                    or proposal.cardinality_key != fact.cardinality_key
                    or proposal.raw_value != fact.raw_value
                    or proposal.normalized_proposal != fact.proposed_value
                ):
                    raise ValueError("original proposal must be preserved unchanged")
        for review in (
            *self.complete_collections,
            *((self.identity_review,) if self.identity_review else ()),
        ):
            for citation in review.evidence:
                check(citation)
        if self.identity_review and not any(
            self.study_id in c.quote for c in self.identity_review.evidence
        ):
            raise ValueError("study identifier must be supported by its reviewed source")
        return self


def normalize_context(context: StudyContext) -> StudyContext:
    payload = context.model_dump(mode="json")
    for key, field in (
        ("sources", "source_id"),
        ("facts", "fact_id"),
        ("complete_collections", "fact_key"),
    ):
        payload[key].sort(key=lambda item: item[field])
    if payload["source_proposals"]:
        payload["source_proposals"]["facts"].sort(key=lambda f: f["fact_id"])
    return StudyContext.model_validate(payload)


def context_digest(context: StudyContext) -> str:
    return digest(normalize_context(context))


def read_curated(inputs: CuratedInputs, source_root: Path) -> StudyContext:
    snapshots = []
    for source in inputs.sources:
        content = safe_path(source_root, source.path).read_bytes()
        if sha256(content) != source.sha256:
            raise ValueError("material source hash mismatch")
        if source.format == "pdf":
            import pypdf

            try:
                reader = PdfReader(io.BytesIO(content), strict=True)
                if reader.is_encrypted or not reader.pages:
                    raise ValueError("source PDF is encrypted or empty")
                texts = [p.extract_text(extraction_mode="plain") or "" for p in reader.pages]
            except (PyPdfError, KeyError) as exc:
                raise ValueError("PDF source parsing failed") from exc
            parser = "pypdf:" + pypdf.__version__
        else:
            text = content.decode("utf-8")
            if source.format == "json":
                json.loads(text)
            texts, parser = [text], "utf8-text-v1"
        snapshots.append(
            SourceSnapshot(
                **source.model_dump(exclude={"path"}),
                parser=parser,
                pages=tuple(parse_page(t, i)[0] for i, t in enumerate(texts)),
            )
        )
    return normalize_context(
        StudyContext(
            **inputs.model_dump(exclude={"purpose", "sources"}),
            purpose="validated_study_context",
            sources=tuple(snapshots),
        )
    )


def from_proposals(proposals: StudyFactsV2, document, study_id: str) -> StudyContext:
    if proposals.document_sha256 != document.source.artifact.sha256:
        raise ValueError("proposal document hash mismatch")
    source = SourceSnapshot(
        source_id=proposals.document_id,
        sha256=proposals.document_sha256,
        version=document.source.artifact.version,
        source_type="protocol",
        format="pdf",
        parser="pypdf:" + document.parser_version,
        pages=document.pages,
    )
    facts = []
    for fact in proposals.facts:
        evidence = {}
        for observation in fact.observations:
            for e in observation.proposal.evidence:
                citation = Citation(
                    source_id=e.document_id,
                    source_sha256=e.document_sha256,
                    pdf_page_index=e.pdf_page_index,
                    printed_page=e.printed_page,
                    start=e.start,
                    end=e.end,
                    quote=e.quote,
                    locator=observation.source_locator,
                )
                evidence[digest(citation)] = citation
        facts.append(
            ContextFact(
                fact_id=fact.fact_id,
                fact_key=fact.fact_key,
                cardinality_key=fact.cardinality_key,
                source_type="protocol",
                raw_value=fact.raw_value,
                proposed_value=fact.normalized_proposal,
                unit=fact.unit,
                status="conflict" if fact.status == "conflict" else "needs_review",
                evidence=tuple(evidence[k] for k in sorted(evidence)),
                proposal_id=fact.fact_id,
                proposal_sha256=fact.proposal_sha256,
            )
        )
    return normalize_context(
        StudyContext(
            schema_version="1",
            purpose="validated_study_context",
            study_id=study_id,
            identity_review=None,
            sources=(source,),
            facts=tuple(facts),
            complete_collections=(),
            source_proposals=proposals,
        )
    )


def dictionary_term(context: StudyContext, coding: ExternalCoding) -> DictionaryTerm:
    source = next((s for s in context.sources if s.source_id == coding.source_id), None)
    if source is None or source.source_type != "external" or source.format != "json":
        raise ValueError("coding requires a pinned external JSON snapshot")
    value = json.loads(source.pages[0].text)
    if not coding.record_pointer.startswith("/"):
        raise ValueError("dictionary term requires an explicit JSON pointer")
    for part in coding.record_pointer[1:].split("/"):
        if re.search(r"~(?![01])", part):
            raise ValueError("invalid JSON pointer escape")
        key = part.replace("~1", "/").replace("~0", "~")
        if isinstance(value, list) and not re.fullmatch(r"0|[1-9][0-9]*", key):
            raise ValueError("invalid JSON array pointer")
        value = value[int(key)] if isinstance(value, list) else value[key]
    term = DictionaryTerm.model_validate(value)
    if term.version != source.version:
        raise ValueError("dictionary version differs from the pinned source")
    return term
