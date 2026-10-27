"""Step 0 boundary contracts. Source declarations are not proof of authority."""

from datetime import date, datetime
from typing import Annotated, Literal, Self

from pydantic import Field, model_validator

from ..schemas import Digest, Model, Text

SourceRole = Literal[
    "sdtm",
    "sdtmig",
    "errata",
    "conformance",
    "ct",
    "ct_relationships",
    "regulator_catalog",
    "regulator_guide",
    "sponsor_rules",
]
Outcome = Literal["include", "exclude", "manual_assessment", "needs_external_source"]


class Source(Model):
    source_id: Text
    title: Text
    publisher: Text
    version: Text
    url: Text | None
    publication_date: date | None
    retrieval_date: date | None
    local_filename: Text
    sha256: Digest
    license_note: Text
    normative_level: int = Field(ge=1, le=5)
    provenance: Literal["cdisc", "regulatory", "sponsor", "study", "historical", "synthetic"]


class SourceRef(Model):
    source_id: Text
    locator: Text


class StandardSelection(Model):
    status: Literal["pinned", "missing", "not_applicable"]
    version: Text | None
    source_id: Text | None
    reason: Text

    @model_validator(mode="after")
    def pinned_source(self) -> Self:
        if self.status == "pinned" and (self.version is None or self.source_id is None):
            raise ValueError("pinned selections require a version and source")
        if self.status != "pinned" and self.source_id is not None:
            raise ValueError("only pinned selections may reference a source")
        return self


class Signoff(Model):
    reviewer_id: Text
    reviewed_at: datetime
    rationale: Text
    content_sha256: Digest
    review_content_sha256: Digest | None = None

    @model_validator(mode="after")
    def aware(self) -> Self:
        if self.reviewed_at.tzinfo is None:
            raise ValueError("review timestamp must include a timezone")
        return self


class ProfileManifest(Model):
    schema_version: Literal["2"]
    profile_id: Text
    profile_version: Text
    created_at: datetime
    status: Literal["draft", "approved_for_mvp"]
    scope: Literal["clinical", "legacy", "synthetic"]
    submission_context: Text
    standards: dict[SourceRole, StandardSelection]
    build_tool_version: Text
    output_hashes: dict[str, Digest]
    signoff: Signoff | None

    @model_validator(mode="after")
    def metadata(self) -> Self:
        required = {
            "sdtm",
            "sdtmig",
            "errata",
            "conformance",
            "ct",
            "ct_relationships",
            "regulator_catalog",
            "regulator_guide",
            "sponsor_rules",
        }
        if set(self.standards) != required:
            raise ValueError("all standards roles require an explicit selection")
        if self.created_at.tzinfo is None:
            raise ValueError("created_at must include a timezone")
        if self.status == "approved_for_mvp":
            if self.scope != "clinical" or self.signoff is None:
                raise ValueError("approval requires clinical scope and explicit human signoff")
            if any(s.status == "missing" for s in self.standards.values()):
                raise ValueError("approved profiles cannot have missing standards")
        for role, selection in self.standards.items():
            if role in {"sdtm", "sdtmig", "errata", "conformance", "ct", "ct_relationships"}:
                if selection.status == "not_applicable":
                    raise ValueError(f"{role} cannot be declared not applicable")
        return self


class Predicate(Model):
    op: Literal[
        "all",
        "any",
        "not",
        "fact_present",
        "fact_equals",
        "fact_in",
        "fact_count",
        "fact_status",
        "rule_ref",
    ]
    children: tuple["Predicate", ...] = ()
    fact_key: Text | None = None
    value: str | int | None = None
    values: tuple[Text, ...] = ()
    rule_id: Text | None = None

    @model_validator(mode="after")
    def shape(self) -> Self:
        if self.op in {"all", "any", "not"}:
            if not self.children or (self.op == "not" and len(self.children) != 1):
                raise ValueError("boolean predicates need children; not requires exactly one")
            if self.fact_key or self.value is not None or self.values or self.rule_id:
                raise ValueError("boolean predicate contains unused operands")
        elif self.op == "rule_ref":
            if not self.rule_id or self.children or self.fact_key or self.values:
                raise ValueError("rule_ref requires only rule_id")
            if self.value is not None:
                raise ValueError("rule_ref cannot contain a value")
        else:
            if not self.fact_key or self.children or self.rule_id:
                raise ValueError("fact predicate requires only fact operands")
            if self.op == "fact_in":
                if not self.values or self.value is not None:
                    raise ValueError("fact_in requires a nonempty values list")
            elif self.op == "fact_present":
                if self.value is not None or self.values:
                    raise ValueError("fact_present cannot contain values")
            elif self.values or self.value is None:
                raise ValueError("comparison requires exactly one value")
            elif self.op == "fact_count":
                if type(self.value) is not int or self.value < 0:
                    raise ValueError("fact_count requires a nonnegative integer")
            elif not isinstance(self.value, str) or not self.value.strip():
                raise ValueError("comparison requires a nonempty string")
        return self


class ApplicabilityRule(Model):
    rule_id: Text
    version: Text
    priority: int
    predicate: Predicate | None
    on_true: Outcome
    on_false: Outcome
    on_unknown: Literal["manual_assessment", "needs_external_source"]
    explanation: Text
    authority_refs: tuple[SourceRef, ...] = Field(min_length=1)

    @model_validator(mode="after")
    def unconditional(self) -> Self:
        if self.predicate is None and (self.on_true != self.on_false):
            raise ValueError("unconditional rules must have identical true/false outcomes")
        return self


class ValueProfile(Model):
    value_profile_id: Text
    value_type: Literal[
        "text", "integer", "decimal", "date", "duration", "controlled", "external", "manual"
    ]
    response_terminology: Text | None
    response_codelist: Text | None
    allow_tsvalnf: bool
    allowed_null_flavors: tuple[Text, ...]
    external_source_required: bool
    target_fields: tuple[Literal["TSVAL", "TSVALNF", "TSVALCD", "TSVCDREF", "TSVCDVER"], ...]
    long_text_policy: Literal["block_for_review"]
    authority_refs: tuple[SourceRef, ...] = Field(min_length=1)

    @model_validator(mode="after")
    def value_contract(self) -> Self:
        if self.allow_tsvalnf != bool(self.allowed_null_flavors):
            raise ValueError("null flavor permission requires an explicit nonempty policy")
        if self.allow_tsvalnf and "TSVALNF" not in self.target_fields:
            raise ValueError("null flavor profile must target TSVALNF")
        if not self.target_fields or len(set(self.target_fields)) != len(self.target_fields):
            raise ValueError("target fields must be nonempty and unique")
        if self.value_type == "controlled" and not self.response_codelist:
            raise ValueError("controlled values require a response codelist")
        if self.value_type == "external" and not self.external_source_required:
            raise ValueError("external values require documented external sources")
        return self


class DerivationRule(Model):
    derivation_id: Text
    version: Text
    fact_keys: tuple[Text, ...]
    transform: Literal[
        "manual",
        "copy_text",
        "format_integer",
        "format_decimal",
        "preserve_iso8601_precision",
        "preserve_iso8601_duration",
        "ratio_from_counts",
        "map_exact_ct",
    ]
    source_requirement: Literal["protocol", "study_data", "sponsor", "external", "manual"]
    authority_refs: tuple[SourceRef, ...] = Field(min_length=1)

    @model_validator(mode="after")
    def inputs(self) -> Self:
        if self.transform != "manual" and not self.fact_keys:
            raise ValueError("deterministic derivations require input fact keys")
        return self


class GroupingRule(Model):
    rule_id: Text
    fact_keys: tuple[Text, ...] = Field(min_length=1)
    authority_refs: tuple[SourceRef, ...] = Field(min_length=1)


class ParameterDefinition(Model):
    tsparmcd: Annotated[str, Field(min_length=1, max_length=8)]
    tsparm: Text
    concept_code: Text
    ct_release: Text
    parameter_status: Literal["active", "deprecated", "not_in_selected_release"]
    applicability_rule_id: Text
    base_disposition: Literal[
        "always",
        "conditional",
        "if_applicable",
        "manual_assessment",
        "out_of_scope",
    ]
    authority_scope: Literal["cdisc", "regulatory", "sponsor", "study", "historical", "synthetic"]
    authority_refs: tuple[SourceRef, ...] = Field(min_length=1)
    min_records: int = Field(ge=0)
    max_records: int | None = Field(ge=1)
    repeat_key: tuple[Text, ...]
    tsgrpid_rule_id: Text | None
    sort_key: Text
    value_profile_id: Text
    fact_key: Text | None
    derivation_id: Text
    value_map_id: Text | None
    automation_level: Literal["deterministic", "propose_only", "manual", "unsupported"]
    evidence_requirements: Text
    review_reason: Text
    notes: str

    @model_validator(mode="after")
    def cardinality(self) -> Self:
        if self.max_records is not None and self.max_records < self.min_records:
            raise ValueError("max_records must be at least min_records")
        return self


class TerminologyTerm(Model):
    release: Text
    codelist: Text
    code: Text
    value: Text
    status: Literal["active", "deprecated"]
    source_id: Text


class ValueMap(Model):
    value_map_id: Text
    input_value: Text
    codelist: Text
    term_code: Text
    submission_value: Text
    release: Text
    authority_refs: tuple[SourceRef, ...] = Field(min_length=1)


class StandardsProfile(Model):
    manifest: ProfileManifest
    sources: tuple[Source, ...] = Field(min_length=1)
    fact_keys: tuple[Text, ...]
    parameters: tuple[ParameterDefinition, ...] = Field(min_length=1)
    applicability_rules: tuple[ApplicabilityRule, ...] = Field(min_length=1)
    value_profiles: tuple[ValueProfile, ...] = Field(min_length=1)
    derivations: tuple[DerivationRule, ...] = Field(min_length=1)
    grouping_rules: tuple[GroupingRule, ...]
    terminology: tuple[TerminologyTerm, ...] = Field(min_length=1)
    value_maps: tuple[ValueMap, ...]


class ProfileFinding(Model):
    code: Text
    severity: Literal["error", "warning"]
    blocking: bool
    location: Text
    message: Text


class ValidationReport(Model):
    profile_id: Text | None
    findings: tuple[ProfileFinding, ...]

    @property
    def valid(self) -> bool:
        return not any(f.severity == "error" for f in self.findings)
