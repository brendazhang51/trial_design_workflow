"""Study Facts v2: untrusted proposals, independently grounded observations, no approvals."""

from datetime import datetime
from typing import Annotated, Literal, Self

from pydantic import Field, model_validator

from ..schemas import Digest, Model, Text
from .models import Index, PageText

FactKey = Annotated[str, Field(pattern=r"^[a-z][a-z0-9_.]*$")]
FactStatus = Literal["proposed", "not_found", "ambiguous", "conflict", "unsupported"]


class FactDefinition(Model):
    fact_key: FactKey
    description: Text
    source_requirement: Literal["protocol", "study_data", "sponsor", "external"]
    repeat_keys: tuple[FactKey, ...] = ()
    normalizer: Literal["preserve", "collapse_whitespace", "integer"] = "preserve"
    value_type: Literal["text", "integer"] = "text"

    @model_validator(mode="after")
    def consistent_type(self) -> Self:
        if (self.value_type == "integer") != (self.normalizer == "integer"):
            raise ValueError("integer facts require the integer normalizer")
        if len(set(self.repeat_keys)) != len(self.repeat_keys):
            raise ValueError("duplicate repeat keys")
        return self


class FactCatalog(Model):
    schema_version: Literal["2"]
    version: Text
    purpose: Literal["fact_extraction_only"]
    definitions: tuple[FactDefinition, ...] = Field(min_length=1)

    @model_validator(mode="after")
    def unique_keys(self) -> Self:
        keys = [d.fact_key for d in self.definitions]
        if len(keys) != len(set(keys)):
            raise ValueError("fact catalog contains duplicate keys")
        return self


class FactEvidence(Model):
    document_id: Text
    document_sha256: Digest
    pdf_page_index: Index
    printed_page: Text | None = None
    start: Index
    end: Index
    quote: Text
    section: Text | None = None
    table: Text | None = None

    @model_validator(mode="after")
    def nonempty_span(self) -> Self:
        if self.end <= self.start:
            raise ValueError("evidence span must be nonempty")
        return self


class FactProposal(Model):
    fact_key: FactKey
    cardinality_key: dict[FactKey, Text] = Field(default_factory=dict)
    status: FactStatus
    raw_value: Text | None = None
    unit: Text | None = None
    evidence: tuple[FactEvidence, ...] = ()
    explanation: Text

    @model_validator(mode="after")
    def consistent_status(self) -> Self:
        if self.status == "proposed" and (self.raw_value is None or not self.evidence):
            raise ValueError("a proposed value requires exact evidence")
        if self.raw_value is not None and not self.evidence:
            raise ValueError("every non-null value requires evidence")
        if self.status in {"not_found", "unsupported"} and self.raw_value is not None:
            raise ValueError("unavailable facts cannot carry proposed values")
        if self.unit is not None and self.raw_value is None:
            raise ValueError("a unit requires a value")
        return self


class ProviderResponse(Model):
    schema_version: Literal["2"]
    request_sha256: Digest
    proposals: tuple[FactProposal, ...]

    @model_validator(mode="after")
    def distinct_proposals(self) -> Self:
        from ..serialization import canonical_json

        values = [canonical_json(p.model_dump(mode="json")) for p in self.proposals]
        if len(values) != len(set(values)):
            raise ValueError("duplicate provider proposals")
        return self


class RequestChunk(Model):
    chunk_id: Text
    pages: tuple[PageText, ...] = Field(min_length=1)


class ExtractionRequest(Model):
    schema_version: Literal["2"]
    document_id: Text
    document_sha256: Digest
    catalog_sha256: Digest
    prompt_version: Text
    prompt_sha256: Digest
    definitions: tuple[FactDefinition, ...]
    chunks: tuple[RequestChunk, ...] = Field(min_length=1)


class ProviderProvenance(Model):
    name: Text
    version: Text
    model_id: Text | None = None
    method: Literal["saved_response", "regex"]
    acquisition: Literal["user_staged_not_verified", "local_deterministic"]
    response_sha256: Digest
    prompt_version: Text
    prompt_sha256: Digest
    # Deliberately no arbitrary settings dictionary that might capture credentials.
    temperature: Annotated[float, Field(ge=0, le=2)] | None = None
    seed: Annotated[int, Field(strict=True)] | None = None

    @model_validator(mode="after")
    def consistent_method(self) -> Self:
        if (self.method == "regex") != (self.acquisition == "local_deterministic"):
            raise ValueError("provider method and acquisition metadata disagree")
        if self.method == "regex" and any(
            v is not None for v in (self.model_id, self.temperature, self.seed)
        ):
            raise ValueError("regex provenance cannot claim model settings")
        return self


class FactObservation(Model):
    proposal: FactProposal
    normalized_proposal: Text | None
    normalizer: Text
    source_type: Literal["protocol"] = "protocol"
    source_locator: Text


class FactFinding(Model):
    finding_id: Digest
    code: Text
    severity: Literal["error", "warning", "info"]
    status: Literal["open"] = "open"
    fact_key: FactKey | None = None
    proposal_sha256: Digest | None = None
    location: tuple[str | int, ...] = ()
    message: Text
    remediation: Text


class RejectedProposal(Model):
    proposal: FactProposal
    codes: tuple[Text, ...] = Field(min_length=1)


class ProviderIssue(Model):
    location: tuple[str | int, ...]
    error_type: Text


class StudyFactV2(Model):
    fact_id: Text
    fact_key: FactKey
    source_requirement: Literal["protocol", "study_data", "sponsor", "external"]
    cardinality_key: dict[FactKey, Text]
    raw_value: Text | None
    normalized_proposal: Text | None
    value_type: Literal["text", "integer"]
    unit: Text | None
    status: FactStatus
    review_status: Literal["needs_review"] = "needs_review"
    observations: tuple[FactObservation, ...]
    alternatives: tuple[Text, ...]
    explanation: Text
    proposal_sha256: Digest

    @model_validator(mode="after")
    def unverified_and_content_addressed(self) -> Self:
        from ..serialization import canonical_json, sha256

        payload = self.model_dump(mode="json", exclude={"proposal_sha256", "fact_id"})
        digest = sha256(canonical_json(payload).encode())
        if self.proposal_sha256 != digest or self.fact_id != self.fact_key + ":" + digest[:20]:
            raise ValueError("fact fingerprint does not match proposal content")
        if self.status != "proposed" and self.normalized_proposal is not None:
            raise ValueError("unresolved facts cannot expose a resolved value")
        if self.status == "proposed":
            if self.source_requirement != "protocol":
                raise ValueError("protocol extraction cannot resolve other source requirements")
            if not self.observations or self.normalized_proposal is None or self.raw_value is None:
                raise ValueError("proposed facts require observations and values")
            if any(o.proposal.status not in {"proposed", "not_found"} for o in self.observations):
                raise ValueError("unresolved observations cannot become proposed facts")
        return self


class StudyFactsV2(Model):
    schema_version: Literal["2"]
    purpose: Literal["unapproved_study_fact_proposals"]
    document_id: Text
    document_sha256: Digest
    request_sha256: Digest
    catalog_sha256: Digest
    provider: ProviderProvenance
    reconciliation_policy: Literal["preserve_all_no_precedence_v1"]
    facts: tuple[StudyFactV2, ...]
    rejected_proposals: tuple[RejectedProposal, ...]
    findings: tuple[FactFinding, ...]

    @model_validator(mode="after")
    def unique_facts(self) -> Self:
        from ..serialization import canonical_json

        keys = [(f.fact_key, canonical_json(f.cardinality_key)) for f in self.facts]
        if len(keys) != len(set(keys)):
            raise ValueError("duplicate fact/cardinality identities")
        for fact in self.facts:
            for observation in fact.observations:
                for evidence in observation.proposal.evidence:
                    if (evidence.document_id, evidence.document_sha256) != (
                        self.document_id,
                        self.document_sha256,
                    ):
                        raise ValueError("observation references a different document")
        return self


class FactsManifest(Model):
    schema_version: Literal["2"]
    software_version: Text
    python_version: Text
    generated_at: datetime
    network_used: Literal[False] = False
    provider_execution: Literal["not_performed", "local_regex"]
    parser_name: Text
    parser_version: Text
    parser_settings: dict[str, str]
    document_sha256: Digest
    files: dict[Text, Digest]
    implementation_sha256: dict[Text, Digest]
    logical_study_facts_sha256: Digest


class PreparationManifest(Model):
    schema_version: Literal["2"]
    purpose: Literal["local_extraction_preparation"]
    document_sha256: Digest
    files: dict[Text, Digest]
