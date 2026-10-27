"""Step 3: deterministic TS proposals and sidecar trace; never emits unresolved values."""

import json
import re
from typing import Annotated, Literal, Self

from pydantic import ConfigDict, Field, model_validator

from . import __version__
from .normalization import (
    MappingException,
    clean_text,
    decimal,
    integer,
    iso_date,
    iso_duration,
    ratio,
    split_tsval,
)
from .schemas import Digest, Model, Text
from .selection import (
    ParameterSelection,
    ProcessingFinding,
    RuntimeProfile,
    check_runtime,
    issue,
    reviewed_values,
    select_parameters,
)
from .serialization import canonical_json
from .standards.models import SourceRef
from .standards.review import VariableMetadata
from .study_context import (
    Citation,
    ExternalCoding,
    StudyContext,
    context_digest,
    dictionary_term,
    digest,
    normalize_context,
)

BASE_COLUMNS = (
    "STUDYID",
    "DOMAIN",
    "TSSEQ",
    "TSGRPID",
    "TSPARMCD",
    "TSPARM",
    "TSVAL",
    "TSVALNF",
    "TSVALCD",
    "TSVCDREF",
    "TSVCDVER",
)


class TSRecord(Model):
    model_config = ConfigDict(
        extra="allow",
        frozen=True,
        json_schema_extra={
            "additionalProperties": False,
            "patternProperties": {
                r"^TSVAL[1-9][0-9]{0,2}$": {
                    "type": "string",
                    "minLength": 1,
                    "maxLength": 200,
                    "pattern": r"\S",
                }
            },
        },
    )
    __pydantic_extra__: dict[str, str] = Field(init=False)
    STUDYID: Text
    DOMAIN: Literal["TS"] = "TS"
    TSSEQ: Annotated[int, Field(gt=0, strict=True)]
    TSGRPID: Text | None = None
    TSPARMCD: Annotated[str, Field(min_length=1, max_length=8)]
    TSPARM: Annotated[str, Field(min_length=1, max_length=40)]
    TSVAL: Annotated[Text, Field(max_length=200)] | None = None
    TSVALNF: Text | None = None
    TSVALCD: Text | None = None
    TSVCDREF: Text | None = None
    TSVCDVER: Text | None = None

    @model_validator(mode="after")
    def value_dependencies(self) -> Self:
        if (self.TSVAL is None) == (self.TSVALNF is None):
            raise ValueError("exactly one of TSVAL or TSVALNF is required for a normal record")
        if self.TSVALCD is not None and not all((self.TSVAL, self.TSVCDREF, self.TSVCDVER)):
            raise ValueError("a value code requires value, terminology reference and version")
        if self.TSVALCD is None and any((self.TSVCDREF, self.TSVCDVER)):
            raise ValueError("terminology reference/version cannot appear without a code")
        extras = self.__pydantic_extra__ or {}
        if any(not re.fullmatch(r"TSVAL[1-9][0-9]{0,2}", k) for k in extras):
            raise ValueError("only standard TSVAL continuation variables may extend the TS record")
        indices = sorted(int(k[5:]) for k in extras)
        if indices != list(range(1, len(indices) + 1)) or extras and self.TSVAL is None:
            raise ValueError(
                "continuation variables must be contiguous and follow a populated TSVAL"
            )
        for value in (self.TSVAL, *extras.values()):
            if value is not None:
                clean_text(value)
                if len(value) > 200:
                    raise ValueError(
                        "TS value exceeds the selected 200-character physical field policy"
                    )
        return self


class RecordTrace(Model):
    record_id: Digest
    tsseq: int
    tsparmcd: Text
    cardinality_key: dict[str, str]
    input_fact_ids: tuple[Text, ...] = Field(min_length=1)
    input_fact_hashes: tuple[Digest, ...] = Field(min_length=1)
    raw_values: tuple[Text | None, ...]
    reviewed_values: tuple[Text | None, ...]
    source_ids: tuple[Text, ...]
    evidence: tuple[Citation, ...] = Field(min_length=1)
    identity_evidence: tuple[Citation, ...] = Field(min_length=1)
    external_coding: tuple[ExternalCoding, ...]
    derivation_id: Text
    derivation_version: Text
    mapping_id: Text | None
    terminology_reference: Text | None
    terminology_version: Text | None
    authority_refs: tuple[SourceRef, ...]
    requires_literal_excel: bool


class ContinuationColumn(Model):
    name: Text
    base_variable: Literal["TSVAL"] = "TSVAL"
    label: Text
    data_type: Literal["Char"] = "Char"
    label_basis: Literal["project_inherits_TSVAL_label"] = "project_inherits_TSVAL_label"
    rule_id: Literal["sdtmig34_tsval_continuation"] = "sdtmig34_tsval_continuation"
    source_refs: tuple[SourceRef, ...] = Field(min_length=1)


class TSGeneration(Model):
    schema_version: Literal["1"]
    algorithm_version: Literal["deterministic-ts-v1"]
    software_version: Text
    profile_content_sha256: Digest
    study_context_sha256: Digest
    selection_sha256: Digest
    review_status: Literal["draft_for_programmer_review"] = "draft_for_programmer_review"
    columns: tuple[Text, ...]
    variable_metadata: tuple[VariableMetadata, ...]
    continuation_metadata: tuple[ContinuationColumn, ...]
    continuation_policy_refs: tuple[SourceRef, ...]
    records: tuple[TSRecord, ...]
    trace: tuple[RecordTrace, ...]
    findings: tuple[ProcessingFinding, ...]

    @model_validator(mode="after")
    def record_trace_integrity(self) -> Self:
        extras = {c for c in self.columns if c not in BASE_COLUMNS}
        if extras != {c.name for c in self.continuation_metadata}:
            raise ValueError("continuation columns require their derived metadata")
        sequences = [r.TSSEQ for r in self.records]
        if len(sequences) != len(set(sequences)) or sequences != list(range(1, len(sequences) + 1)):
            raise ValueError("project sequence order must be contiguous, unique and stable")
        if len(self.records) != len(self.trace):
            raise ValueError("every record requires a trace")
        for record, trace in zip(self.records, self.trace, strict=True):
            if (
                trace.record_id != digest(record)
                or trace.tsseq != record.TSSEQ
                or trace.tsparmcd != record.TSPARMCD
            ):
                raise ValueError("record trace does not match its TS record")
            if set(record.model_dump()) - set(self.columns):
                raise ValueError("record contains an undeclared dataset column")
        return self


def _continued(value, value_profile, runtime):
    if len(value) <= 200:
        return {"TSVAL": value}, ()
    if value_profile.long_text_policy != "sdtmig34_tsval_continuation":
        raise MappingException("LONG_TEXT_BLOCKED_BY_PROFILE")
    selected = runtime.profile.manifest.standards["sdtmig"]
    refs = tuple(
        r
        for r in value_profile.authority_refs
        if r.source_id == selected.source_id
        and ("4.5.3.2" in r.locator or "Assumption 4" in r.locator)
    )
    if selected.version is None or not selected.version.startswith("3.4") or not refs:
        raise MappingException("CONTINUATION_SOURCE_POLICY_REQUIRED")
    parts = split_tsval(value)
    if len(parts) > 1000:
        raise MappingException("CONTINUATION_VARIABLE_LIMIT")
    return {"TSVAL" if i == 0 else f"TSVAL{i}": part for i, part in enumerate(parts)}, refs


def generate_ts(
    context: StudyContext,
    selection: ParameterSelection,
    runtime: RuntimeProfile,
    *,
    allow_draft=False,
) -> TSGeneration:
    context = normalize_context(StudyContext.model_validate_json(context.model_dump_json()))
    runtime = check_runtime(runtime, allow_draft=allow_draft)
    selection = ParameterSelection.model_validate_json(selection.model_dump_json())
    expected = select_parameters(context, runtime, allow_draft=allow_draft)
    if digest(expected) != digest(selection):
        raise ValueError("Selection differs from deterministic replay of its pinned inputs")
    profile = runtime.profile
    findings = list(selection.findings)
    candidates = []
    continuation_refs = {}
    metadata = (
        tuple(sorted(runtime.content.variables, key=lambda v: v.order)) if runtime.content else ()
    )
    columns = [v.name for v in sorted(metadata, key=lambda v: v.order)]
    if (
        set(columns) != set(BASE_COLUMNS)
        or len(columns) != len(BASE_COLUMNS)
        or len({v.order for v in metadata}) != len(metadata)
        or any(v.data_type != ("Num" if v.name == "TSSEQ" else "Char") for v in metadata)
    ):
        findings.append(
            issue(
                "TS_STRUCTURE_METADATA_REQUIRED",
                None,
                "Source-backed metadata for all eleven TS variables is required.",
            )
        )
    elif context.identity_review is None:
        findings.append(
            issue(
                "STUDY_ID_REVIEW_REQUIRED",
                None,
                "The supplied study identifier requires documented review.",
            )
        )
    else:
        decisions = {d.tsparmcd: d for d in selection.decisions}
        values = {v.value_profile_id: v for v in profile.value_profiles}
        derivations = {d.derivation_id: d for d in profile.derivations}
        groups = {g.rule_id: g for g in profile.grouping_rules}
        for parameter in sorted(profile.parameters, key=lambda p: (p.sort_key, p.tsparmcd)):
            decision = decisions[parameter.tsparmcd]
            if decision.decision != "include":
                continue
            value_profile = values[parameter.value_profile_id]
            derivation = derivations[parameter.derivation_id]
            refs = (
                *parameter.authority_refs,
                *value_profile.authority_refs,
                *derivation.authority_refs,
            )
            inputs = [f for f in context.facts if f.fact_key in derivation.fact_keys]
            by_group = {}
            invalid = []
            for fact in inputs:
                if set(fact.cardinality_key) != set(parameter.repeat_key):
                    invalid.append(fact.fact_id)
                else:
                    by_group.setdefault(canonical_json(fact.cardinality_key), []).append(fact)
            if invalid:
                findings.append(
                    issue(
                        "REPEAT_ASSOCIATION_MISMATCH",
                        parameter.tsparmcd,
                        "Required repeat keys are absent or unexpected.",
                        fact_ids=invalid,
                        refs=refs,
                    )
                )
            produced = []
            for group_key, facts in sorted(by_group.items()):
                facts = sorted(facts, key=lambda f: f.fact_id)
                ids = tuple(f.fact_id for f in facts)
                try:
                    if parameter.automation_level in {"manual", "unsupported"}:
                        raise MappingException("MANUAL_MAPPING_REQUIRED")
                    raw = []
                    for key in derivation.fact_keys:
                        matching = [f for f in facts if f.fact_key == key]
                        value, reason = reviewed_values(matching, derivation.source_requirement)
                        if reason != "REVIEWED":
                            raise MappingException(reason)
                        raw.append(value)
                    nulls = {f.null_flavor for f in facts}
                    fields = {}
                    mapping_id = None
                    if raw and raw[0] is None:
                        if len(raw) != 1 or len(nulls) != 1 or None in nulls:
                            raise MappingException("NULL_FLAVOR_REVIEW_REQUIRED")
                        flavor = next(iter(nulls))
                        if (
                            not value_profile.allow_tsvalnf
                            or flavor not in value_profile.allowed_null_flavors
                        ):
                            raise MappingException("NULL_FLAVOR_FORBIDDEN")
                        fields["TSVALNF"] = flavor
                    else:
                        if not raw or any(v is None for v in raw):
                            raise MappingException("VALUE_SOURCE_MISSING")
                        for value in raw:
                            clean_text(value)
                        transform = derivation.transform
                        allowed = {
                            "text": {"copy_text"},
                            "integer": {"format_integer"},
                            "decimal": {"format_decimal", "ratio_from_counts"},
                            "date": {"preserve_iso8601_precision"},
                            "duration": {"preserve_iso8601_duration"},
                            "controlled": {"map_exact_ct"},
                            "external": {"manual"},
                            "manual": set(),
                        }
                        if transform not in allowed[value_profile.value_type]:
                            raise MappingException("VALUE_TRANSFORM_MISMATCH")
                        if value_profile.value_type == "external":
                            if len(facts) != 1 or facts[0].coding is None:
                                raise MappingException("EXTERNAL_DICTIONARY_REQUIRED")
                            try:
                                term = dictionary_term(context, facts[0].coding)
                            except (ValueError, KeyError, IndexError, TypeError):
                                raise MappingException("EXTERNAL_CODING_UNVERIFIED") from None
                            if term.value != raw[0]:
                                raise MappingException("EXTERNAL_CODE_VALUE_MISMATCH")
                            if (
                                value_profile.response_terminology is not None
                                and term.reference != value_profile.response_terminology
                            ):
                                raise MappingException("EXTERNAL_DICTIONARY_MISMATCH")
                            value = term.value
                            fields.update(
                                TSVALCD=term.code, TSVCDREF=term.reference, TSVCDVER=term.version
                            )
                        elif transform == "map_exact_ct":
                            mappings = [
                                m
                                for m in profile.value_maps
                                if m.value_map_id == parameter.value_map_id
                                and m.input_value == raw[0]
                            ]
                            if len(mappings) != 1:
                                raise MappingException("CONTROLLED_TERM_UNMAPPED")
                            mapping = mappings[0]
                            terms = [
                                t
                                for t in profile.terminology
                                if t.codelist == mapping.codelist
                                and t.code == mapping.term_code
                                and t.release == mapping.release
                                and t.value == mapping.submission_value
                                and t.status == "active"
                            ]
                            if (
                                len(terms) != 1
                                or mapping.codelist != value_profile.response_codelist
                                or mapping.release != parameter.ct_release
                            ):
                                raise MappingException("CONTROLLED_TERM_UNVERIFIED")
                            value = mapping.submission_value
                            mapping_id = mapping.value_map_id
                            fields.update(
                                TSVALCD=mapping.term_code,
                                TSVCDREF=value_profile.response_terminology,
                                TSVCDVER=mapping.release,
                            )
                        elif transform == "copy_text":
                            value = raw[0]
                        elif transform == "format_integer":
                            value = integer(raw[0])
                        elif transform == "format_decimal":
                            value = decimal(raw[0])
                        elif transform == "preserve_iso8601_precision":
                            value = iso_date(raw[0])
                            if not any(
                                f.raw_value is not None
                                and value == f.raw_value.strip()
                                or f.raw_value is None
                                and any(value in e.quote for e in f.evidence)
                                for f in facts
                            ):
                                raise MappingException("DATE_SOURCE_PRECISION_REQUIRES_REVIEW")
                        elif transform == "preserve_iso8601_duration":
                            value = iso_duration(raw[0])
                            if not any(
                                f.raw_value is not None
                                and value == f.raw_value.strip()
                                or f.raw_value is None
                                and any(value in e.quote for e in f.evidence)
                                for f in facts
                            ):
                                raise MappingException("DURATION_SOURCE_PRECISION_REQUIRES_REVIEW")
                        elif transform == "ratio_from_counts":
                            if len(raw) != 2:
                                raise MappingException("RATIO_INPUT_CONTRACT_INVALID")
                            if len({f.unit for f in facts if f.unit is not None}) > 1:
                                raise MappingException("RATIO_UNIT_MISMATCH")
                            value = ratio(*raw)
                        else:
                            raise MappingException("MANUAL_MAPPING_REQUIRED")
                        physical, used_refs = _continued(clean_text(value), value_profile, runtime)
                        fields.update(physical)
                        continuation_refs.update(
                            {canonical_json(r.model_dump()): r for r in used_refs}
                        )
                    if (
                        set(fields)
                        - set(value_profile.target_fields)
                        - {k for k in fields if re.fullmatch(r"TSVAL[1-9][0-9]{0,2}", k)}
                    ):
                        raise MappingException("VALUE_TARGET_FIELDS_MISMATCH")
                    group_token = None
                    if parameter.tsgrpid_rule_id:
                        group_rule = groups[parameter.tsgrpid_rule_id]
                        keys = facts[0].cardinality_key
                        if not set(group_rule.fact_keys) <= set(keys):
                            raise MappingException("GROUP_ASSOCIATION_MISSING")
                        group_token = canonical_json(
                            {
                                "rule": group_rule.rule_id,
                                "keys": {k: keys[k] for k in group_rule.fact_keys},
                            }
                        )
                    payload = dict(
                        STUDYID=context.study_id,
                        DOMAIN="TS",
                        TSSEQ=1,
                        TSPARMCD=parameter.tsparmcd,
                        TSPARM=parameter.tsparm,
                        **fields,
                    )
                    for variable in metadata:
                        if variable.name == "TSGRPID" and group_token is not None:
                            continue
                        if variable.core == "Req" and payload.get(variable.name) is None:
                            raise MappingException("REQUIRED_TS_VARIABLE_MISSING")
                    # Validate before adding a candidate. Group IDs/sequence are assigned later.
                    TSRecord.model_validate(payload)
                    produced.append(
                        (
                            payload,
                            group_key,
                            group_token,
                            facts,
                            derivation,
                            mapping_id,
                            refs,
                            parameter.sort_key,
                        )
                    )
                except MappingException as exc:
                    findings.append(
                        issue(
                            exc.code,
                            parameter.tsparmcd,
                            "The selected value cannot be generated under its pinned contract.",
                            fact_ids=ids,
                            refs=refs,
                        )
                    )
                except ValueError:
                    findings.append(
                        issue(
                            "TS_RECORD_CONTRACT_INVALID",
                            parameter.tsparmcd,
                            "The proposed TS structure or coded-value dependencies are invalid.",
                            fact_ids=ids,
                            refs=refs,
                        )
                    )
            if len(produced) < parameter.min_records:
                findings.append(
                    issue(
                        "PARAMETER_MIN_CARDINALITY",
                        parameter.tsparmcd,
                        "Fewer grounded records than the included parameter requires.",
                        refs=refs,
                    )
                )
            if parameter.max_records is not None and len(produced) > parameter.max_records:
                findings.append(
                    issue(
                        "PARAMETER_MAX_CARDINALITY",
                        parameter.tsparmcd,
                        "Too many records for this parameter; no records emitted.",
                        refs=refs,
                    )
                )
            else:
                candidates.extend(produced)
    group_ids = {
        token: str(i + 1)
        for i, token in enumerate(sorted({c[2] for c in candidates if c[2] is not None}))
    }
    candidates.sort(key=lambda c: (c[7], c[0]["TSPARMCD"], c[1], canonical_json(c[0])))
    records, traces = [], []
    for i, (payload, group_key, group_token, facts, derivation, mapping_id, refs, _) in enumerate(
        candidates, 1
    ):
        record = TSRecord.model_validate(
            {**payload, "TSSEQ": i, "TSGRPID": group_ids.get(group_token)}
        )
        formula = any(
            isinstance(v, str) and v.lstrip().startswith(("=", "+", "-", "@"))
            for v in record.model_dump().values()
        )
        if formula:
            findings.append(
                issue(
                    "EXCEL_LITERAL_REQUIRED",
                    record.TSPARMCD,
                    "The later workbook writer must preserve this value as literal text.",
                    severity="info",
                    blocking=False,
                )
            )
        records.append(record)
        evidence = tuple(c.model_dump(mode="json") for f in facts for c in f.evidence)
        traces.append(
            RecordTrace(
                record_id=digest(record),
                tsseq=i,
                tsparmcd=record.TSPARMCD,
                cardinality_key=json.loads(group_key),
                input_fact_ids=tuple(f.fact_id for f in facts),
                input_fact_hashes=tuple(digest(f) for f in facts),
                raw_values=tuple(f.raw_value for f in facts),
                reviewed_values=tuple(f.reviewed_value for f in facts),
                source_ids=tuple(
                    sorted(
                        {e.source_id for f in facts for e in f.evidence}
                        | {f.coding.source_id for f in facts if f.coding}
                    )
                ),
                evidence=evidence,
                identity_evidence=context.identity_review.evidence,
                external_coding=tuple(f.coding for f in facts if f.coding),
                derivation_id=derivation.derivation_id,
                derivation_version=derivation.version,
                mapping_id=mapping_id,
                terminology_reference=record.TSVCDREF,
                terminology_version=record.TSVCDVER,
                authority_refs=refs,
                requires_literal_excel=formula,
            )
        )
    extra = sorted(
        {k for r in records for k in r.model_dump() if k not in BASE_COLUMNS},
        key=lambda k: int(k[5:]),
    )
    if extra:
        at = columns.index("TSVAL") + 1
        columns[at:at] = extra
    return TSGeneration(
        schema_version="1",
        algorithm_version="deterministic-ts-v1",
        software_version=__version__,
        profile_content_sha256=selection.profile_content_sha256,
        study_context_sha256=context_digest(context),
        selection_sha256=digest(selection),
        columns=tuple(columns),
        variable_metadata=metadata,
        continuation_metadata=tuple(
            ContinuationColumn(
                name=name,
                label=next(v.label for v in metadata if v.name == "TSVAL"),
                source_refs=tuple(continuation_refs[k] for k in sorted(continuation_refs)),
            )
            for name in extra
        ),
        continuation_policy_refs=tuple(continuation_refs[k] for k in sorted(continuation_refs)),
        records=tuple(records),
        trace=tuple(traces),
        findings=tuple(
            sorted({f.finding_id: f for f in findings}.values(), key=lambda f: f.finding_id)
        ),
    )
