"""TS Parameter Registry: versioned CSV, deterministic applicability and exact CT lookup."""

import csv
import json
import re
import unicodedata
from datetime import date
from pathlib import Path
from typing import Literal

from pydantic import Field

from .inputs import ASSETS, StudyField, StudyInputs
from .schemas import Model, Text
from .serialization import sha256


class ParameterEntry(Model):
    TSPARMCD: str = Field(pattern=r"^[A-Z][A-Z0-9]{0,7}$")
    TSPARM: Text
    applicability_rule: Literal["review", "include_if_present", "exclude", "external"]
    expected_fact_key: str
    value_type: Literal["text", "integer", "date"]
    response_codelist: str
    likely_source: Text
    automation_status: Literal["propose", "manual", "unsupported"]
    rule_source: Text
    notes: str
    registry_version: Text
    ct_release: Text


class ParameterRegistry(Model):
    entries: tuple[ParameterEntry, ...]
    version: Text
    ct_release: Text
    sha256: Text


class CTTerm(Model):
    release: Text
    codelist: Text
    code: Text
    value: Text


class CTSnapshot(Model):
    terms: tuple[CTTerm, ...]
    release: Text
    sha256: Text


class ParameterCandidate(Model):
    parameter: ParameterEntry
    recommendation: Literal[
        "suggested_keep",
        "needs_review",
        "missing",
        "conflict",
        "not_applicable",
        "needs_external_source",
        "unsupported",
    ]
    applicability: str
    field: StudyField | None
    draft_value: str | None
    ct_result: str
    message: str
    review_status: Literal["needs_review"] = "needs_review"


def verify_builtin(path: Path) -> None:
    if path.resolve().parent == ASSETS.resolve():
        metadata = json.loads((ASSETS / "sources.json").read_bytes())
        if metadata["files"].get(path.name) != sha256(path.read_bytes()):
            raise ValueError(f"Bundled asset changed without versioning: {path.name}")


def load_registry(path: Path) -> ParameterRegistry:
    verify_builtin(path)
    with path.open(encoding="utf-8-sig", newline="") as stream:
        entries = tuple(ParameterEntry.model_validate(r) for r in csv.DictReader(stream))
    if not entries:
        raise ValueError("Parameter registry is empty")
    if len({e.TSPARMCD for e in entries}) != len(entries):
        raise ValueError("Duplicate TSPARMCD in registry")
    versions, releases = {e.registry_version for e in entries}, {e.ct_release for e in entries}
    if len(versions) != 1 or len(releases) != 1:
        raise ValueError("Registry must explicitly select one version and CT release")
    return ParameterRegistry(
        entries=tuple(sorted(entries, key=lambda e: e.TSPARMCD)),
        version=versions.pop(),
        ct_release=releases.pop(),
        sha256=sha256(path.read_bytes()),
    )


def load_ct(path: Path) -> CTSnapshot:
    verify_builtin(path)
    with path.open(encoding="utf-8-sig", newline="") as stream:
        terms = tuple(CTTerm.model_validate(r) for r in csv.DictReader(stream))
    if not terms or len({t.release for t in terms}) != 1:
        raise ValueError("CT snapshot must explicitly select one nonempty release")
    keys = [(t.codelist, t.value) for t in terms]
    codes = [(t.codelist, t.code) for t in terms]
    if len(keys) != len(set(keys)) or len(codes) != len(set(codes)):
        raise ValueError("Duplicate or ambiguous CT mappings in the same codelist")
    return CTSnapshot(terms=terms, release=terms[0].release, sha256=sha256(path.read_bytes()))


# Project normalization proposals, never applied across input sources to conceal disagreement.
PHASE_ALIASES = {
    **{
        f"PHASE{i}": f"PHASE {roman} TRIAL"
        for i, roman in ((1, "I"), (2, "II"), (3, "III"), (4, "IV"))
    },
    **{str(i): f"PHASE {roman} TRIAL" for i, roman in ((1, "I"), (2, "II"), (3, "III"), (4, "IV"))},
    "1A": "PHASE IA TRIAL",
    "1B": "PHASE IB TRIAL",
    "2A": "PHASE IIA TRIAL",
    "2B": "PHASE IIB TRIAL",
    "3A": "PHASE IIIA TRIAL",
    "3B": "PHASE IIIB TRIAL",
}
MASK_ALIASES = {
    "NONE": "OPEN LABEL",
    "SINGLE": "SINGLE BLIND",
    "DOUBLE": "DOUBLE BLIND",
    "TRIPLE": "TRIPLE BLIND",
    "QUADRUPLE": "QUADRUPLE BLIND",
}


def ct_lookup(snapshot: CTSnapshot, codelist: str, value: str) -> tuple[str | None, str]:
    if not codelist:
        return value, "not_applicable (project free-text/numeric mapping; verify)"
    if codelist == "UNVERIFIED":
        return None, "unverified_response_codelist"
    proposal = value
    if codelist == "C66737":
        proposal = PHASE_ALIASES.get(value.upper(), value)
    elif codelist == "C66735":
        proposal = MASK_ALIASES.get(value.upper(), value)
    match = next(
        (t for t in snapshot.terms if t.codelist == codelist and t.value == proposal), None
    )
    if match:
        suffix = "; project alias applied, review" if proposal != value else ""
        return match.value, f"valid_in_snapshot {snapshot.release}; {match.code}" + suffix
    return None, f"unverified_value_or_codelist {codelist}; release={snapshot.release}"


def valid_partial_date(value: str) -> bool:
    if not re.fullmatch(r"\d{4}(?:-\d{2}){0,2}", value):
        return False
    try:
        # Padding is validation-only. TSVAL preserves the original date precision.
        date.fromisoformat(value + {4: "-01-01", 7: "-01", 10: ""}[len(value)])
    except ValueError:
        return False
    return True


def build_candidates(
    inputs: StudyInputs,
    registry: ParameterRegistry,
    terminology: CTSnapshot,
) -> tuple[ParameterCandidate, ...]:
    if registry.ct_release != terminology.release:
        raise ValueError("Registry CT release does not match selected CT snapshot")
    fields = {f.field_key: f for f in inputs.facts}
    codes = {t.value: t.code for t in terminology.terms if t.codelist == "C66738"}
    names = {t.code: t.value for t in terminology.terms if t.codelist == "C67152"}
    candidates = []
    for parameter in registry.entries:
        field = fields.get(parameter.expected_fact_key)
        state, value, result = "needs_review", None, "not_checked"
        applicability = "needs_review: authoritative applicability rule not supplied"
        message = "All rows are unapproved draft candidates. "
        if (
            parameter.TSPARMCD not in codes
            or names.get(codes[parameter.TSPARMCD]) != parameter.TSPARM
        ):
            state, result = "needs_review", "unverified_parameter_code_or_label"
            message += "Verify parameter code/label in selected CT before using a value."
        elif parameter.applicability_rule == "exclude":
            state, applicability = "not_applicable", "exclude: " + parameter.rule_source
            message += "Explicit supplied exclusion; retained for audit and deletion."
        elif parameter.applicability_rule == "external":
            state = "needs_external_source"
            message += "Document an external value source before use."
        elif parameter.automation_status == "unsupported":
            state = "unsupported"
            message += "No automated derivation is implemented."
        elif not parameter.expected_fact_key or parameter.automation_status == "manual":
            state = "needs_review"
            message += (
                "Manual source/interpretation required; absence does not imply non-applicability."
            )
        elif field is None:
            state = "missing"
            message += (
                "No input fact matched the configured key; inspect protocol or external source."
            )
        elif field.result == "conflict":
            state = "conflict"
            message += "Differing values retained in review/evidence; TSVAL intentionally blank."
        else:
            raw = field.values[0].proposed_value
            invalid_type = (
                parameter.value_type == "integer" and not re.fullmatch(r"\d+", raw)
            ) or (parameter.value_type == "date" and not valid_partial_date(raw))
            if invalid_type:
                result = "invalid_value_type"
                message += "Value does not match the registry type."
            else:
                value, result = ct_lookup(terminology, parameter.response_codelist, raw)
                if value is not None:
                    state = "suggested_keep"
                    message += (
                        f"{field.result}; applicability and source meaning still need review."
                    )
                    if parameter.applicability_rule == "include_if_present":
                        applicability = "include_if_present: " + parameter.rule_source
                else:
                    message += "CT lookup unresolved; raw candidate retained in review only."
            if value is not None and (
                len(value) > 200 or any(unicodedata.category(c).startswith("C") for c in value)
            ):
                value, state = None, "needs_review"
                message += (
                    " Long/control text blocked; 200 is a project review threshold, "
                    "not a CDISC rule."
                )
        candidates.append(
            ParameterCandidate(
                parameter=parameter,
                recommendation=state,
                applicability=applicability,
                field=field,
                draft_value=value,
                ct_result=result,
                message=message,
            )
        )
    return tuple(candidates)
