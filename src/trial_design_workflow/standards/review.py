"""Readable Step 0 joins and source-gap tracking; never executes study rules.

Content is a separate, digest-bound transcription workspace. It cannot approve a
profile, supply missing runtime rules, or change any immutable schema-v2 asset.
"""

import csv
import io
from pathlib import Path
from typing import Literal, Self

from pydantic import Field, model_validator

from ..schemas import Digest, Model, Text
from ..serialization import sha256
from .models import (
    ApplicabilityRule,
    Predicate,
    ProfileFinding,
    SourceRef,
    StandardsProfile,
    ValidationReport,
)
from .profile import ProfileError, json_bytes
from .validation import content_digest, validate_profile

SECTIONS = (
    "definition",
    "inclusion",
    "value_source",
    "response",
    "derivation",
    "exceptions",
    "cardinality",
)
PRIORITY = ("TITLE", "TPHASE", "RANDOM", "TBLIND", "PLANSUB", "ACTSUB", "TRT", "CURTRT")
PRIORITY_QUESTIONS = {
    "TITLE": "Establish which protocol title/version supplies the value and its text policy.",
    "TPHASE": "Establish phase applicability, mixed-phase handling and exact response codelist.",
    "RANDOM": "Establish applicability separately from the randomization response value.",
    "TBLIND": "Establish masking definitions, arm differences and exact response codelist.",
    "PLANSUB": "Establish planned enrollment definition, population and protocol version.",
    "ACTSUB": "Establish actual subject-count definition and documented study-data source; "
    "do not substitute planned enrollment or assume a registry count is equivalent.",
    "TRT": "Establish intervention multiplicity and required terminology; an unverified "
    "external identifier must remain unresolved.",
    "CURTRT": "Establish treatment-design evidence needed for inclusion or exclusion; "
    "missing extraction is not evidence of non-applicability.",
}


def inventory_sources(directory: Path) -> dict:
    """Hash local candidates without reading their text or claiming authority/license."""
    if not directory.is_dir():
        raise ValueError("Expected a local standards directory")
    files = []
    for path in sorted(directory.rglob("*")):
        if path.is_symlink():
            raise ValueError("Source inventory does not follow symlinks")
        if path.is_file() and path.name != "README.md":
            content = path.read_bytes()
            files.append(
                {
                    "filename": path.relative_to(directory).as_posix(),
                    "sha256": sha256(content),
                    "size_bytes": len(content),
                    "status": "candidate_not_verified",
                    "publisher": None,
                    "version": None,
                    "url": None,
                    "retrieval_date": None,
                    "license_note": None,
                    "selected_for_clinical_use": False,
                }
            )
    return {"schema_version": "1", "files": files, "selection_performed": False}


class ContentAssertion(Model):
    status: Literal["missing", "proposed", "source_backed"]
    text: Text
    basis: Literal["standard", "project_policy"]
    source_refs: tuple[SourceRef, ...]
    action_required: Text | None

    @model_validator(mode="after")
    def evidence(self) -> Self:
        if self.status == "source_backed" and not self.source_refs:
            raise ValueError("source-backed content requires exact source references")
        if self.status != "source_backed" and not self.action_required:
            raise ValueError("unresolved content requires a concrete next action")
        return self


class ParameterContent(Model):
    tsparmcd: Text
    definition: ContentAssertion
    inclusion: ContentAssertion
    value_source: ContentAssertion
    response: ContentAssertion
    derivation: ContentAssertion
    exceptions: ContentAssertion
    cardinality: ContentAssertion
    # Response metadata is separate from prose so missing and not-applicable differ.
    codelist_status: Literal["unresolved", "codelist", "not_applicable", "external"]
    codelist_id: Text | None
    codelist_name: Text | None
    terminology_release: Text | None
    no_codelist_reason: Text | None

    @model_validator(mode="after")
    def response_metadata(self) -> Self:
        if self.codelist_status == "codelist":
            if not all((self.codelist_id, self.codelist_name, self.terminology_release)):
                raise ValueError("codelist requires ID, name and release")
        elif any((self.codelist_id, self.codelist_name, self.terminology_release)):
            raise ValueError("only a selected codelist may declare codelist metadata")
        if self.codelist_status == "not_applicable" and not self.no_codelist_reason:
            raise ValueError("no codelist requires an explicit reason")
        if self.codelist_status != "not_applicable" and self.no_codelist_reason:
            raise ValueError("no-codelist reason requires not_applicable status")
        return self


class VariableMetadata(Model):
    order: int = Field(ge=1)
    name: Text
    label: Text
    data_type: Literal["Char", "Num"]
    role: Text
    core: Literal["Req", "Exp", "Perm"]
    codelist_or_format: Text | None
    implementation_notes: Text
    source_refs: tuple[SourceRef, ...] = Field(min_length=1)


class ReviewContent(Model):
    schema_version: Literal["1"]
    content_version: Text
    profile_id: Text
    profile_content_sha256: Digest
    parameters: tuple[ParameterContent, ...]
    variables: tuple[VariableMetadata, ...]
    variable_inventory: ContentAssertion


def initialize_content(profile: StandardsProfile) -> ReviewContent:
    """Create actionable transcription gaps, never suggested clinical answers."""
    parameters = []
    for parameter in sorted(profile.parameters, key=lambda p: p.tsparmcd):
        identity = f"{parameter.tsparmcd} ({parameter.tsparm})"
        actions = {
            "definition": f"Transcribe the authoritative definition for {identity}, with locator.",
            "inclusion": f"Cite applicability for {identity}; specify include, exclude and "
            "unknown conditions independently of value availability.",
            "value_source": f"Identify authorized source type and exact fact inputs "
            f"for {identity}.",
            "response": f"Verify response type and codelist ID/name/release for {identity}, "
            "or cite why no codelist applies; do not infer from TSPARMCD membership.",
            "derivation": f"Document the value transform, unit, precision and target fields "
            f"for {identity}.",
            "exceptions": f"Specify missing, conflicting, unmapped and unverified-source "
            f"handling for {identity}; no automatic exclusion or null flavor.",
            "cardinality": f"Verify record counts, repeat keys, grouping and ordering "
            f"for {identity}.",
        }
        fields = {}
        for section, action in actions.items():
            if parameter.tsparmcd in PRIORITY_QUESTIONS:
                action += " " + PRIORITY_QUESTIONS[parameter.tsparmcd]
            fields[section] = ContentAssertion(
                status="missing",
                text=f"Not established for {identity}.",
                basis="standard",
                source_refs=(),
                action_required=action,
            )
        parameters.append(
            ParameterContent(
                tsparmcd=parameter.tsparmcd,
                **fields,
                codelist_status="unresolved",
                codelist_id=None,
                codelist_name=None,
                terminology_release=None,
                no_codelist_reason=None,
            )
        )
    return ReviewContent(
        schema_version="1",
        content_version="1",
        profile_id=profile.manifest.profile_id,
        profile_content_sha256=content_digest(profile),
        parameters=tuple(parameters),
        variables=(),
        variable_inventory=ContentAssertion(
            status="missing",
            text="Full TS variable inventory is not established.",
            basis="standard",
            source_refs=(),
            action_required="Transcribe all TS variable metadata from the pinned SDTMIG/model; "
            "verify required, expected and permissible columns separately from parameter rows.",
        ),
    )


def validate_content(profile: StandardsProfile, content: ReviewContent) -> ValidationReport:
    """Content readiness augments, rather than replaces, profile validation/signoff."""
    findings = list(validate_profile(profile, allow_draft=True).findings)

    def gap(code: str, location: str, message: str) -> None:
        findings.append(
            ProfileFinding(
                code=code,
                severity="error",
                blocking=True,
                location=location,
                message=message,
            )
        )

    if profile.manifest.status == "approved_for_mvp":
        signoff = profile.manifest.signoff
        if signoff.review_content_sha256 != sha256(json_bytes(content.model_dump(mode="json"))):
            gap(
                "STALE_CONTENT_SIGNOFF",
                "manifest.signoff.review_content_sha256",
                "Review content differs from the recorded approval; obtain a new bound decision.",
            )

    if (
        content.profile_id != profile.manifest.profile_id
        or content.profile_content_sha256 != content_digest(profile)
    ):
        gap("CONTENT_PROFILE_MISMATCH", "content", "Rebase content against this exact profile.")
    expected = {p.tsparmcd for p in profile.parameters}
    actual = [p.tsparmcd for p in content.parameters]
    if len(actual) != len(set(actual)) or set(actual) != expected:
        gap("CONTENT_COVERAGE", "parameters", "Require exactly one content row per parameter.")
    sources = {s.source_id: s for s in profile.sources}

    def check_refs(refs: tuple[SourceRef, ...], location: str, basis: str = "standard") -> None:
        for ref in refs:
            source = sources.get(ref.source_id)
            if source is None:
                gap("CONTENT_SOURCE_UNKNOWN", location, f"Unknown source: {ref.source_id}.")
            elif basis == "standard" and source.provenance not in {"cdisc", "regulatory"}:
                gap(
                    "CONTENT_SOURCE_AUTHORITY",
                    location,
                    f"{ref.source_id} cannot establish a clinical standard requirement.",
                )

    def check_assertion(assertion: ContentAssertion, location: str) -> None:
        if assertion.status != "source_backed":
            gap("CONTENT_SOURCE_GAP", location, assertion.action_required or assertion.text)
        check_refs(assertion.source_refs, location, assertion.basis)

    profiles = {v.value_profile_id: v for v in profile.value_profiles}
    definitions = {p.tsparmcd: p for p in profile.parameters}
    rules = {r.rule_id: r for r in profile.applicability_rules}
    derivations = {d.derivation_id: d for d in profile.derivations}
    for parameter in sorted(content.parameters, key=lambda p: p.tsparmcd):
        for section in SECTIONS:
            check_assertion(getattr(parameter, section), f"{parameter.tsparmcd}.{section}")
        definition = definitions.get(parameter.tsparmcd)
        if definition is None:
            continue
        value = profiles.get(definition.value_profile_id)
        if parameter.codelist_status == "unresolved":
            gap(
                "RESPONSE_UNRESOLVED",
                f"{parameter.tsparmcd}.response",
                "Verify response codelist or document a source-backed non-codelist contract.",
            )
        elif value:
            if parameter.codelist_status == "codelist" and (
                parameter.codelist_id != value.response_codelist
                or not any(
                    t.codelist == parameter.codelist_id
                    and t.release == parameter.terminology_release
                    for t in profile.terminology
                )
            ):
                gap(
                    "RESPONSE_PROFILE_MISMATCH",
                    f"{parameter.tsparmcd}.response",
                    "Codelist/release must resolve in the runtime value profile and terminology.",
                )
            if parameter.codelist_status == "not_applicable" and value.response_codelist:
                gap(
                    "RESPONSE_PROFILE_MISMATCH",
                    f"{parameter.tsparmcd}.response",
                    "Runtime value profile still selects a response codelist.",
                )
            if parameter.codelist_status == "external" and value.value_type != "external":
                gap(
                    "RESPONSE_PROFILE_MISMATCH",
                    f"{parameter.tsparmcd}.response",
                    "External response requires a matching external runtime value contract.",
                )
        rule = rules.get(definition.applicability_rule_id)
        derivation = derivations.get(definition.derivation_id)
        if rule and rule.predicate is None and rule.on_true == "manual_assessment":
            gap(
                "INCLUSION_NOT_IMPLEMENTED",
                f"{parameter.tsparmcd}.inclusion",
                "Replace the generic manual placeholder with a source-specific disposition.",
            )
        if value and value.value_type == "manual":
            if (
                parameter.value_source.status == "source_backed"
                and derivation
                and derivation.fact_keys
                and derivation.source_requirement != "manual"
            ):
                gap(
                    "RESPONSE_CONTRACT_BLOCKED",
                    f"{parameter.tsparmcd}.response",
                    parameter.response.action_required
                    or "The value source is specified, "
                    "but response coding still needs source review.",
                )
            else:
                gap(
                    "VALUE_NOT_IMPLEMENTED",
                    f"{parameter.tsparmcd}.value_source",
                    "Define a specific value contract, including documented manual/external needs.",
                )
        if derivation and derivation.source_requirement == "manual" and not derivation.fact_keys:
            gap(
                "SOURCE_NOT_IMPLEMENTED",
                f"{parameter.tsparmcd}.derivation",
                "Identify concrete source requirements; prose alone does not implement a rule.",
            )
    check_assertion(content.variable_inventory, "variables")
    names = [v.name for v in content.variables]
    orders = [v.order for v in content.variables]
    if not names or len(names) != len(set(names)) or len(orders) != len(set(orders)):
        gap("VARIABLE_METADATA_INCOMPLETE", "variables", "Require a nonempty unique TS inventory.")
    for variable in content.variables:
        check_refs(variable.source_refs, f"variables.{variable.name}")
    return ValidationReport(
        profile_id=profile.manifest.profile_id,
        findings=tuple(sorted(findings, key=lambda f: (f.location, f.code))),
    )


def references(profile: StandardsProfile, refs: tuple[SourceRef, ...]) -> str:
    sources = {s.source_id: s for s in profile.sources}
    return "\n".join(
        f"{r.source_id} | {sources[r.source_id].version if r.source_id in sources else 'UNKNOWN'}"
        f" | {r.locator}"
        for r in refs
    )


def predicate_text(
    predicate: Predicate | None, rules: dict[str, ApplicabilityRule] | None = None
) -> str:
    if predicate is None:
        return "Unconditional (does not establish applicability by itself)"
    if predicate.children:
        return (
            f"{predicate.op.upper()}("
            + "; ".join(predicate_text(child, rules) for child in predicate.children)
            + ")"
        )
    if predicate.op == "rule_ref":
        if rules and predicate.rule_id in rules:
            referenced = rules[predicate.rule_id]
            return (
                f"Rule {referenced.rule_id}: "
                f"{predicate_text(referenced.predicate, rules)}; "
                f"true={referenced.on_true}; false={referenced.on_false}; "
                f"unknown={referenced.on_unknown}"
            )
        return f"Rule reference: {predicate.rule_id}"
    operand = predicate.values or predicate.value
    return f"{predicate.op}({predicate.fact_key}" + (
        f", {operand})" if operand is not None else ")"
    )


def review_rows(profile: StandardsProfile, content: ReviewContent) -> list[dict]:
    """Join runtime assets and transcription notes, with explicit unresolved markers."""
    rules = {r.rule_id: r for r in profile.applicability_rules}
    values = {v.value_profile_id: v for v in profile.value_profiles}
    derivations = {d.derivation_id: d for d in profile.derivations}
    grouping = {g.rule_id: g for g in profile.grouping_rules}
    notes = {p.tsparmcd: p for p in content.parameters}
    rows = []
    for parameter in sorted(
        profile.parameters,
        key=lambda p: (
            PRIORITY.index(p.tsparmcd) if p.tsparmcd in PRIORITY else len(PRIORITY),
            p.tsparmcd,
        ),
    ):
        rule = rules[parameter.applicability_rule_id]
        value = values[parameter.value_profile_id]
        derivation = derivations[parameter.derivation_id]
        note = notes[parameter.tsparmcd]
        row = {
            "TSPARMCD": parameter.tsparmcd,
            "TSPARM": parameter.tsparm,
            "CT identity release": parameter.ct_release,
            "Content state": "unresolved"
            if any(getattr(note, s).status != "source_backed" for s in SECTIONS)
            else "source-backed transcription; approved for MVP"
            if profile.manifest.status == "approved_for_mvp"
            else "source-backed transcription; profile review still required",
        }
        for section in SECTIONS:
            assertion = getattr(note, section)
            row[section.replace("_", " ").title()] = assertion.text
            row[f"{section} status / basis"] = f"{assertion.status} / {assertion.basis}"
            row[f"{section} sources"] = references(profile, assertion.source_refs) or "UNRESOLVED"
            row[f"{section} action"] = assertion.action_required or ""
        row.update(
            {
                "Inclusion predicate": predicate_text(rule.predicate, rules),
                "If true": rule.on_true,
                "If false": rule.on_false,
                "If unknown": rule.on_unknown,
                "Inclusion explanation": rule.explanation,
                "Inclusion runtime source": references(profile, rule.authority_refs),
                "Value source type": derivation.source_requirement,
                "Fact inputs": ", ".join(derivation.fact_keys) or "UNRESOLVED",
                "Response type": value.value_type,
                "Response codelist status": note.codelist_status,
                "Response codelist ID": value.response_codelist
                or ("NOT APPLICABLE" if note.codelist_status == "not_applicable" else "UNRESOLVED"),
                "Response codelist name": note.codelist_name
                or ("NOT APPLICABLE" if note.codelist_status == "not_applicable" else "UNRESOLVED"),
                "Response codelist release": note.terminology_release
                or ("NOT APPLICABLE" if note.codelist_status == "not_applicable" else "UNRESOLVED"),
                "No codelist reason": note.no_codelist_reason or "",
                "Response terminology": value.response_terminology or "UNRESOLVED",
                "Response runtime source": references(profile, value.authority_refs),
                "External source required": value.external_source_required,
                "Transform": derivation.transform,
                "Derivation runtime source": references(profile, derivation.authority_refs),
                "Target fields": ", ".join(value.target_fields),
                "Null policy": ", ".join(value.allowed_null_flavors)
                if value.allow_tsvalnf
                else "Not authorized by this value profile",
                "Long text policy": value.long_text_policy,
                "Runtime min records": parameter.min_records,
                "Runtime max records": parameter.max_records
                if parameter.max_records is not None
                else "No upper bound encoded; source review required",
                "Repeat keys": ", ".join(parameter.repeat_key),
                "Grouping": "Group by: "
                + ", ".join(grouping[parameter.tsgrpid_rule_id].fact_keys)
                + " | "
                + references(profile, grouping[parameter.tsgrpid_rule_id].authority_refs)
                if parameter.tsgrpid_rule_id in grouping
                else "No grouping rule encoded",
                "Sort key": parameter.sort_key,
                "Value aliases": "\n".join(
                    f"{m.input_value} → {m.submission_value} ({m.term_code}; {m.release})"
                    for m in sorted(
                        profile.value_maps, key=lambda m: (m.value_map_id, m.input_value)
                    )
                    if m.value_map_id == parameter.value_map_id
                ),
                "Automation": parameter.automation_level,
                "Evidence requirements": parameter.evidence_requirements,
                "Review reason": parameter.review_reason,
            }
        )
        if profile.manifest.status == "approved_for_mvp":
            row["Profile approval"] = "approved_for_mvp"
            row["Review reason (as authored)"] = row.pop("Review reason")
        rows.append(row)
    return rows


def review_markdown(rows: list[dict], *, approved: bool = False) -> bytes:
    def cell(value: object) -> str:
        # Keep source material literal in the readable document.
        return (
            str(value)
            .replace("&", "&amp;")
            .replace("<", "&lt;")
            .replace(">", "&gt;")
            .replace("|", "&#124;")
            .replace("\n", "<br>")
        )

    lines = [
        "# Master Lookup content review",
        "",
        "Review only. Missing content is a blocking source gap, not a clinical rule.",
        "The first eight sections are the priority vertical examples; none is approved",
        "by exporting this document. Dataset columns are reviewed separately in",
        "ts_variable_metadata.csv. Workbook/CSV edits are annotations, not approvals.",
        "",
    ]
    if approved:
        lines = [
            "# Master Lookup — approved MVP baseline",
            "",
            "This profile has a content-bound human approval in manifest.signoff.",
            "Original policy wording is preserved as authored; historical proposal/review",
            "phrases do not reopen the recorded profile approval. Study facts and generated",
            "TS records still require their own review. CSV edits remain annotations.",
            "Dataset columns are documented separately in ts_variable_metadata.csv.",
            "",
        ]
    for row in rows:
        lines.extend(
            [
                f"## {cell(row['TSPARMCD'])} — {cell(row['TSPARM'])}",
                "",
                "| Item | Content |",
                "| --- | --- |",
            ]
        )
        for name, value in row.items():
            if name not in {"TSPARMCD", "TSPARM"}:
                lines.append(f"| {cell(name)} | {cell(value)} |")
        lines.append("")
    return ("\n".join(lines) + "\n").encode()


def readable_csv(rows: list[dict], headers: list[str] | None = None) -> bytes:
    stream = io.StringIO(newline="")
    writer = csv.DictWriter(stream, fieldnames=headers or list(rows[0]), lineterminator="\n")
    writer.writeheader()
    # CSVs may be opened in Excel; make every source cell literal, without formulas.
    writer.writerows(
        {
            key: (
                "'" + value
                if isinstance(value, str) and value.lstrip().startswith(("=", "+", "-", "@"))
                else value
            )
            for key, value in row.items()
        }
        for row in rows
    )
    return stream.getvalue().encode("utf-8-sig")


def export_review(profile: StandardsProfile, content: ReviewContent, output: Path) -> Path:
    structural = validate_profile(profile, allow_draft=True)
    if not structural.valid:
        raise ProfileError(structural)
    report = validate_content(profile, content)
    if profile.manifest.status == "approved_for_mvp" and any(f.blocking for f in report.findings):
        raise ProfileError(report)
    # Unresolved content is exportable for review; malformed joins are not.
    if any(f.code in {"CONTENT_PROFILE_MISMATCH", "CONTENT_COVERAGE"} for f in report.findings):
        raise ValueError("Content must cover and bind to this exact profile before export")
    rows = review_rows(profile, content)
    files = {
        "master_lookup_review.csv": readable_csv(rows),
        "master_lookup_review.md": review_markdown(
            rows, approved=profile.manifest.status == "approved_for_mvp"
        ),
        "content.json": json_bytes(content.model_dump(mode="json")),
        "content_findings.json": json_bytes(report.model_dump(mode="json")),
        "source_inventory.csv": readable_csv(
            [
                {
                    "Role": role,
                    **selection.model_dump(mode="json"),
                    "Action required": "Acquire authorized source and pin exact version/hash"
                    if selection.status == "missing"
                    else selection.reason,
                }
                for role, selection in sorted(profile.manifest.standards.items())
            ]
        ),
        "source_index.json": json_bytes(
            [s.model_dump(mode="json") for s in sorted(profile.sources, key=lambda s: s.source_id)]
        ),
        "content_gaps.csv": readable_csv(
            [
                {
                    "Location": f.location,
                    "Code": f.code,
                    "Blocking": f.blocking,
                    "Action": f.message,
                }
                for f in report.findings
            ],
            ["Location", "Code", "Blocking", "Action"],
        ),
        "ts_variable_metadata.csv": readable_csv(
            [
                {
                    **v.model_dump(exclude={"source_refs"}),
                    "Sources": references(profile, v.source_refs),
                }
                for v in sorted(content.variables, key=lambda v: v.order)
            ],
            [
                "order",
                "name",
                "label",
                "data_type",
                "role",
                "core",
                "codelist_or_format",
                "implementation_notes",
                "Sources",
            ],
        ),
    }
    summary = {
        "profile_id": profile.manifest.profile_id,
        "profile_content_sha256": content_digest(profile),
        "content_version": content.content_version,
        "parameter_count": len(rows),
        "priority_parameters": list(PRIORITY),
        "blocking_findings": sum(f.blocking for f in report.findings),
        "content_checks_passed": report.valid and not any(f.blocking for f in report.findings),
        "profile_status": profile.manifest.status,
        # Export cannot create approval; it can report an existing valid bound signoff.
        "step0_ready": (
            profile.manifest.status == "approved_for_mvp"
            and profile.manifest.signoff is not None
            and report.valid
            and not any(f.blocking for f in report.findings)
        ),
        "variable_inventory_status": content.variable_inventory.status,
        "review_only": True,
    }
    if profile.manifest.status == "approved_for_mvp":
        summary["profile_signoff"] = profile.manifest.signoff.model_dump(mode="json")
    files["review_manifest.json"] = json_bytes(summary)
    files["checksums.json"] = json_bytes(
        {name: sha256(data) for name, data in sorted(files.items())}
    )
    output.mkdir(parents=True, exist_ok=False)
    for name, data in sorted(files.items()):
        with (output / name).open("xb") as stream:
            stream.write(data)
    return output
