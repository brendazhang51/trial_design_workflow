"""Reproducible, source-pinned clinical review draft. Never approves standards.

The first eight parameter policies are project choices for a programmer-review
draft. They are not assertions that CDISC universally requires these rows.
"""

from datetime import date, datetime
from pathlib import Path
from tempfile import TemporaryDirectory
from typing import Literal

from pypdf import PdfReader

from ..schemas import Digest, Model, Text
from ..serialization import sha256
from .acquisition import (
    CodetableSnapshot,
    ExtractedTerm,
    SourceDiscrepancy,
    read_codetable,
    read_ct_pdf,
    read_ts_conformance,
    verify_codetable,
)
from .catalog import ParameterPolicyCatalog, compile_catalog
from .models import StandardsProfile
from .profile import BUILD_VERSION, build_profile, json_bytes, safe_path, semantic_diff
from .reconciliation import POLICY_ID, POLICY_RULES, annotate_reconciliation, reconcile_codetable
from .review import PRIORITY, ReviewContent, export_review, initialize_content, readable_csv
from .validation import content_digest

POLICY = """Clinical TS review-draft policy v1 (proposed, not qualified signoff)
Scope: TS programmer-review draft; no regulator-specific submission.
IG 3.4 section 7.4.2 Assumption 2 delegates parameter requirements to recipients.
This project elects descriptive TITLE, TPHASE, RANDOM, TBLIND, PLANSUB, ACTSUB rows.
Their applicability is independent of value availability: missing/conflicting values
remain exceptions. RANDOM includes both Y and N; TBLIND includes open-label designs.
TPHASE NOT APPLICABLE requires affirmative evidence; never infer it from missingness.
TRT and CURTRT require reviewer-established applicability inputs with exactly
present/absent values following full design review. Absent may exclude; missing,
unreviewed, invalid or conflicting inputs must remain unknown/manual assessment.
These applicability inputs are human design assessments, not AI-generated approvals.
ACTSUB needs actual study-data counts matching CT, not planned or assumed registry counts.
TRT/CURTRT protocol names are retained; coded output is manual/external until an
authorized terminology is selected. The IG UNII example does not impose UNII on
this non-regulator-specific profile, and no UNII lookup integration is added.
Every other parameter remains explicitly unadjudicated with a parameter-specific
content gap, rather than inheriting the first eight policies.
Single-value cardinality for the six descriptive parameters is a project proposal.
Multiple TRT/CURTRT names need stable intervention keys and treatment review.
No null flavors or long-text splitting are enabled in this increment. No facts,
dates, dictionary identifiers or codes may be invented. Inputs and outputs are draft.
"""


class LocalSourceInput(Model):
    filename: Text
    sha256: Digest
    version: Text
    publication_date: date | None
    retrieval_date: date | None = None
    url: Text | None = None


class ClinicalBuildSpec(Model):
    schema_version: Text
    profile_id: Text
    profile_version: Text
    created_at: datetime
    ct_release: Text
    inputs: dict[str, LocalSourceInput]
    parameter_policy: LocalSourceInput | None = None
    source_precedence: Literal["strict", "selected_ct_authoritative"] = "strict"


FACTS = {
    "TITLE": ("study_title", "protocol", "copy_text"),
    "TPHASE": ("study_phase", "protocol", "map_exact_ct"),
    "RANDOM": ("randomization", "protocol", "map_exact_ct"),
    "TBLIND": ("blinding", "protocol", "map_exact_ct"),
    "PLANSUB": ("planned_enrollment", "protocol", "format_integer"),
    "ACTSUB": ("actual_enrollment", "study_data", "format_integer"),
    "TRT": ("investigational_interventions", "protocol", "manual"),
    "CURTRT": ("current_therapies", "protocol", "manual"),
}


def ref(source: str, locator: str) -> list[dict]:
    return [{"source_id": source, "locator": locator}]


def variable_metadata() -> list[dict]:
    # Exact names, labels, types, core and roles transcribed from pp. 417-418.
    # Notes below are implementation summaries; original specification is bundled.
    rows = [
        (
            "STUDYID",
            "Study Identifier",
            "Char",
            "Identifier",
            "Req",
            None,
            "Unique study identifier.",
            417,
        ),
        (
            "DOMAIN",
            "Domain Abbreviation",
            "Char",
            "Identifier",
            "Req",
            "TS",
            "Domain abbreviation is TS.",
            417,
        ),
        (
            "TSSEQ",
            "Sequence Number",
            "Num",
            "Identifier",
            "Req",
            None,
            "Unique within a parameter, not necessarily globally unique across parameters.",
            417,
        ),
        (
            "TSGRPID",
            "Group ID",
            "Char",
            "Identifier",
            "Perm",
            None,
            "Associates related records; see Assumption 13.",
            417,
        ),
        (
            "TSPARMCD",
            "Trial Summary Parameter Short Name",
            "Char",
            "Topic",
            "Req",
            "(TSPARMCD)",
            "At most eight characters; companion to TSPARM.",
            417,
        ),
        (
            "TSPARM",
            "Trial Summary Parameter",
            "Char",
            "Synonym Qualifier",
            "Req",
            "(TSPARM)",
            "At most forty characters; companion to TSPARMCD.",
            417,
        ),
        (
            "TSVAL",
            "Parameter Value",
            "Char",
            "Result Qualifier",
            "Exp",
            "*",
            "Null only with TSVALNF; values over 200 characters use TSVAL1-TSVALn, "
            "per Assumption 4 and section 4.5.3.2. Splitting is not implemented here.",
            417,
        ),
        (
            "TSVALNF",
            "Parameter Value Null Flavor",
            "Char",
            "Result Qualifier",
            "Perm",
            "ISO 21090 NullFlavor",
            "Only populated if TSVAL is null; no automatic null flavors.",
            418,
        ),
        (
            "TSVALCD",
            "Parameter Value Code",
            "Char",
            "Result Qualifier",
            "Exp",
            "*",
            "Code of the term in TSVAL; external codes may exceed eight characters.",
            418,
        ),
        (
            "TSVCDREF",
            "Name of the Reference Terminology",
            "Char",
            "Result Qualifier",
            "Exp",
            "(DICTNAM)",
            "Identifies the reference terminology for TSVALCD.",
            418,
        ),
        (
            "TSVCDVER",
            "Version of the Reference Terminology",
            "Char",
            "Result Qualifier",
            "Exp",
            None,
            "Terminology version when applicable.",
            418,
        ),
    ]
    return [
        dict(
            order=index,
            name=name,
            label=label,
            data_type=kind,
            role=role,
            core=core,
            codelist_or_format=fmt,
            implementation_notes=notes,
            source_refs=ref("sdtmig", f"7.4.2 TS Specification; PDF/printed page {page}"),
        )
        for index, (name, label, kind, role, core, fmt, notes, page) in enumerate(rows, 1)
    ]


def assemble_profile(
    spec: ClinicalBuildSpec,
    sources: list[dict],
    snapshot: CodetableSnapshot,
    terms: tuple[ExtractedTerm, ...],
    discrepancies: tuple[SourceDiscrepancy, ...],
) -> tuple[StandardsProfile, ReviewContent]:
    lookup = {(t.codelist, t.code): t for t in terms}
    by_parameter = {p.tsparmcd: p for p in snapshot.parameters}
    bad_identity = {
        d.tsparmcd
        for d in discrepancies
        if d.code in {"CODETABLE_IDENTITY_MISMATCH", "CODETABLE_UNIVERSE_MISMATCH"}
    }
    policies = ref("project-policy", "Clinical TS review-draft policy v1; proposed policy")
    ig_refs = ref("sdtmig", "7.4.2, Assumptions 2, 7-9; PDF/printed page 418")
    rules, values, derivations, parameters, mappings = [], [], [], [], []
    fact_keys = {v[0] for v in FACTS.values()} | {
        "reviewed_trt_applicability",
        "reviewed_curtrt_applicability",
        "intervention_id",
    }
    for identity in sorted((t for t in terms if t.codelist == "C66738"), key=lambda t: t.value):
        code = identity.value
        label = lookup[("C67152", identity.code)].value
        definition_refs = ref("ct", f"C66738/{identity.code}; PDF pages {identity.pages}")
        entry = by_parameter.get(code)
        links = entry.responses if entry and code not in bad_identity else ()
        codelists = {r.codelist for r in links}
        if len(codelists) > 1:
            raise ValueError("Multiple response codelists need an explicit per-parameter contract")
        selected = next(iter(codelists), None)
        mapping_refs = ref("ct_relationships", entry.locators[0]) if entry else ig_refs
        fact, source, transform = FACTS.get(code, (None, "manual", "manual"))
        priority = code in PRIORITY
        conditional = code in {"TRT", "CURTRT"}
        rule_id, value_id, derivation_id = f"{code}-app-v1", f"{code}-value-v1", f"{code}-derive-v1"
        rules.append(
            dict(
                rule_id=rule_id,
                version="1",
                priority=0,
                predicate={
                    "op": "fact_equals",
                    "fact_key": f"reviewed_{code.lower()}_applicability",
                    "value": "present",
                }
                if conditional
                else None,
                on_true="include" if priority else "manual_assessment",
                on_false="exclude"
                if conditional
                else "include"
                if priority
                else "manual_assessment",
                on_unknown="manual_assessment",
                explanation=(
                    f"Project draft policy proposes {code}; applicability does not depend "
                    "on whether the value is available."
                )
                if priority
                else (
                    f"{code} ({label}): review recipient/project applicability "
                    "using the CT definition; "
                    "IG Assumption 2 is not a universal required-parameter list."
                ),
                authority_refs=policies + ig_refs,
            )
        )
        value_type = (
            "controlled"
            if selected
            else {
                "TITLE": "text",
                "PLANSUB": "integer",
                "ACTSUB": "integer",
                "TRT": "external",
                "CURTRT": "external",
            }.get(code, "manual")
        )
        values.append(
            dict(
                value_profile_id=value_id,
                value_type=value_type,
                response_terminology="CDISC CT" if selected else None,
                response_codelist=selected,
                allow_tsvalnf=False,
                allowed_null_flavors=[],
                external_source_required=conditional,
                target_fields=["TSVAL", "TSVALCD", "TSVCDREF", "TSVCDVER"]
                if selected or conditional
                else ["TSVAL"],
                long_text_policy="block_for_review",
                authority_refs=mapping_refs + ig_refs + policies,
            )
        )
        for response in links:
            ct_term = lookup.get((response.codelist, response.term_code))
            if ct_term and ct_term.value == response.value:
                mappings.append(
                    dict(
                        value_map_id=f"{code}-exact-v1",
                        input_value=response.value,
                        codelist=response.codelist,
                        term_code=response.term_code,
                        submission_value=response.value,
                        release=spec.ct_release,
                        authority_refs=ref("ct_relationships", response.locator),
                    )
                )
        derivations.append(
            dict(
                derivation_id=derivation_id,
                version="1",
                fact_keys=[fact] if fact else [],
                transform=transform,
                source_requirement=source,
                authority_refs=definition_refs + policies,
            )
        )
        parameters.append(
            dict(
                tsparmcd=code,
                tsparm=label,
                concept_code=identity.code,
                ct_release=spec.ct_release,
                parameter_status="active",
                applicability_rule_id=rule_id,
                base_disposition="conditional"
                if conditional
                else "always"
                if priority
                else "manual_assessment",
                authority_scope="study",
                authority_refs=definition_refs,
                min_records=1 if priority and not conditional else 0,
                max_records=None if conditional or not priority else 1,
                repeat_key=["intervention_id"] if conditional else [],
                tsgrpid_rule_id=None,
                sort_key=code,
                value_profile_id=value_id,
                fact_key=fact,
                derivation_id=derivation_id,
                value_map_id=f"{code}-exact-v1"
                if any(m["value_map_id"] == f"{code}-exact-v1" for m in mappings)
                else None,
                automation_level="manual" if conditional or not priority else "propose_only",
                evidence_requirements=f"Exact source observation matching the CT definition "
                f"of {code}; "
                "protocol evidence cannot establish actual study data or external identifiers.",
                review_reason="Draft policy and source interpretation require qualified review."
                if priority
                else f"Adjudicate applicability and value-source definition for {code} ({label}).",
                notes=f"CT definition (not an inclusion rule): {identity.definition}",
            )
        )
    selections = {
        role: dict(
            status="pinned",
            version=source.version,
            source_id=role,
            reason="User-supplied local bytes pinned for this draft; not approval.",
        )
        for role, source in spec.inputs.items()
    }
    context = "SDTMIG v3.4 TS programmer-review draft; no regulator-specific submission"
    for role in ("regulator_catalog", "regulator_guide"):
        selections[role] = dict(
            status="not_applicable", version=None, source_id=None, reason=context
        )
    selections["sponsor_rules"] = dict(
        status="not_applicable",
        version=None,
        source_id=None,
        reason="No sponsor-specific rules supplied; project draft policy is labeled separately.",
    )
    selections.setdefault(
        "errata",
        dict(
            status="missing",
            version=None,
            source_id=None,
            reason="A dated local errata/known-issue snapshot is still needed; "
            "do not infer none exist.",
        ),
    )
    profile = StandardsProfile.model_validate(
        dict(
            manifest=dict(
                schema_version="2",
                profile_id=spec.profile_id,
                profile_version=spec.profile_version,
                created_at=spec.created_at,
                status="draft",
                scope="clinical",
                submission_context=context,
                standards=selections,
                build_tool_version=BUILD_VERSION,
                output_hashes={},
                signoff=None,
            ),
            sources=sources,
            fact_keys=sorted(fact_keys),
            parameters=parameters,
            applicability_rules=rules,
            value_profiles=values,
            derivations=derivations,
            grouping_rules=[],
            terminology=[
                dict(
                    release=spec.ct_release,
                    codelist=t.codelist,
                    code=t.code,
                    value=t.value,
                    status="active",
                    source_id="ct",
                )
                for t in terms
            ],
            value_maps=mappings,
        )
    )
    payload = initialize_content(profile).model_dump(mode="json")

    def assertion(text, refs, *, basis="standard", status="source_backed", action=None):
        return dict(status=status, text=text, basis=basis, source_refs=refs, action_required=action)

    for item in payload["parameters"]:
        code = item["tsparmcd"]
        parameter = next(p for p in profile.parameters if p.tsparmcd == code)
        term = lookup[("C66738", parameter.concept_code)]
        refs = ref("ct", f"C66738/{term.code}; PDF pages {term.pages}")
        item["definition"] = assertion(term.definition, refs)
        entry = by_parameter.get(code)
        links = entry.responses if entry and code not in bad_identity else ()
        if links:
            item.update(
                codelist_status="codelist",
                codelist_id=links[0].codelist,
                codelist_name=links[0].codelist_name,
                terminology_release=spec.ct_release,
            )
            item["response"] = assertion(
                "Exact response subset from the TS codetable, cross-checked against CT. "
                "Only verified code/value pairs enter the exact map; no new aliases are inferred.",
                ref("ct_relationships", entry.locators[0]) + refs,
            )
        item["exceptions"] = assertion(
            f"{code}: missing/conflicting facts, unknown terms or unverified sources remain "
            "exceptions. No automatic null flavor, guessed code or absence-based exclusion.",
            policies,
            basis="project_policy",
        )
        if code in PRIORITY:
            fact, source, transform = FACTS[code]
            conditional = code in {"TRT", "CURTRT"}
            item["inclusion"] = assertion(
                (
                    f"Project proposal: include {code} when the reviewer-established "
                    f"reviewed_{code.lower()}_applicability is present; "
                    "exclude only on explicit absent after complete design review. "
                    "Missing, unreviewed or conflicting input is unknown."
                )
                if conditional
                else (
                    f"Project proposal: include {code} in this review-draft profile even if its "
                    "value is unavailable; route unavailable values to exceptions. "
                    "This is not a CDISC universally required parameter assertion."
                ),
                policies + ig_refs,
                basis="project_policy",
            )
            detail = {
                "ACTSUB": "Actual enrolled count, including non-randomized subjects where "
                "the CT definition applies; do not substitute planned or registry enrollment.",
                "CURTRT": "Protocol-specified background medication taken as standard of care, "
                "not all concomitant medications and not inferred solely from ADDON.",
                "TRT": "Protocol-defined investigational drug, device, therapy, "
                "procedure or process; "
                "not restricted to drug studies.",
            }.get(code, f"Use the protocol statement matching the {code} definition.")
            item["value_source"] = assertion(
                f"Project fact input {fact}; source type {source}. {detail}",
                refs + policies,
                basis="project_policy",
            )
            item["derivation"] = assertion(
                f"{fact} → {transform}; preserve source meaning and precision. "
                + (
                    "Integer subject count; no invented count or coded value."
                    if code in {"ACTSUB", "PLANSUB"}
                    else "Coded treatment values remain manual/external; no dictionary is selected."
                    if conditional
                    else "No uncontrolled synonym mapping or inferred value."
                ),
                policies + ig_refs,
                basis="project_policy",
            )
            item["cardinality"] = assertion(
                "Project proposal: one record per distinct intervention_id; grouping unresolved "
                "until design review. No arbitrary upper bound."
                if conditional
                else "Project proposal: one descriptive value; conflicting or "
                "multiple source values remain exceptions rather than being silently collapsed.",
                policies + ref("sdtmig", "7.4.2 Assumptions 12-13; PDF/printed page 419"),
                basis="project_policy",
            )
            if code in {"TITLE", "PLANSUB", "ACTSUB"}:
                item.update(
                    codelist_status="not_applicable",
                    no_codelist_reason="Free text title or numeric count, not a response code; "
                    "IG Assumptions "
                    "7 and 9 and Example 1 ACTSUB row 45.",
                )
                item["response"] = assertion(
                    "TITLE is text; PLANSUB/ACTSUB are subject counts. TSVALCD remains null "
                    "for these uncoded values. A blank codetable cell alone "
                    "is not this rule's basis.",
                    ig_refs + ref("sdtmig", "7.4.2 Example 1; pages 420-421"),
                )
            elif conditional:
                item["codelist_status"] = "external"
                item["response"] = assertion(
                    "No external dictionary/version has been selected. IG Example 1 uses UNII "
                    "but is not a universal mandate. Project coded treatment output remains "
                    "manual/external; no lookup service or unverified code is added.",
                    policies + ig_refs,
                    basis="project_policy",
                )
        relevant = [d for d in discrepancies if d.tsparmcd == code]
        if relevant:
            item["response"] = assertion(
                " ".join(d.message for d in relevant),
                ref("ct_relationships", relevant[0].locator),
                status="proposed",
                action="Resolve the supplied codetable/CT discrepancy; invalid pairs are omitted "
                "from executable exact maps, while the original source is retained.",
            )
    payload["variables"] = variable_metadata()
    payload["variable_inventory"] = assertion(
        "Eleven base TS variables transcribed from the selected IG. TSVAL1-TSVALn is the "
        "conditional long-text continuation series, not extra fixed base columns. Runtime "
        "generation, splitting and requiredness QC remain Step 3/4 work.",
        ref("sdtmig", "7.4.2 TS Specification, pages 417-418; Assumption 4; 4.5.3.2"),
    )
    return profile, ReviewContent.model_validate(payload)


def build_clinical_review(
    spec: ClinicalBuildSpec,
    source_root: Path,
    output: Path,
    before: StandardsProfile | None = None,
    *,
    policy_root: Path | None = None,
) -> Path:
    required = {"sdtm", "sdtmig", "ct", "ct_relationships", "conformance"}
    if (
        spec.schema_version != "1"
        or not required <= set(spec.inputs)
        or not set(spec.inputs) <= required | {"errata"}
    ):
        raise ValueError("Clinical staging requires five source roles and optional errata")
    if spec.inputs["ct"].version != spec.ct_release:
        raise ValueError("CT source version must equal the selected release")
    if output.exists():
        raise FileExistsError("Choose a new review-draft output directory")
    source_bytes, sources, paths = {}, [], {}
    for role, source in sorted(spec.inputs.items()):
        path = safe_path(source_root, source.filename)
        content = path.read_bytes()
        if sha256(content) != source.sha256:
            raise ValueError(f"Source hash mismatch for {role}")
        local = "sources/" + Path(source.filename).name
        if local in source_bytes:
            raise ValueError("Duplicate source filename")
        source_bytes[local] = content
        paths[role] = path
        sources.append(
            dict(
                source_id=role,
                title=Path(source.filename).name,
                publisher="NCI EVS / CDISC" if role == "ct" else "CDISC",
                version=source.version,
                url=source.url,
                publication_date=source.publication_date,
                retrieval_date=source.retrieval_date,
                local_filename=local,
                sha256=source.sha256,
                license_note="User-supplied authorized local source; "
                "redistribution rights not inferred. "
                "Keep this generated package outside Git.",
                normative_level=3 if role in {"ct", "ct_relationships"} else 2,
                provenance="cdisc",
            )
        )
    catalog = None
    if spec.parameter_policy:
        if policy_root is None:
            raise ValueError("Explicit policy root is required for the pinned parameter catalog")
        policy_input = spec.parameter_policy
        policy_bytes = safe_path(policy_root, policy_input.filename).read_bytes()
        if sha256(policy_bytes) != policy_input.sha256:
            raise ValueError("Parameter policy catalog hash mismatch")
        catalog = ParameterPolicyCatalog.model_validate_json(policy_bytes)
        if catalog.version != policy_input.version:
            raise ValueError("Parameter policy catalog version mismatch")
        local = "sources/parameter-policies-v2.json"
        source_bytes[local] = policy_bytes
        sources.append(
            dict(
                source_id="parameter-policies",
                title="Complete parameter policy proposals v2",
                publisher="trial_design_workflow",
                version=catalog.version,
                url=None,
                publication_date=policy_input.publication_date,
                retrieval_date=None,
                local_filename=local,
                sha256=policy_input.sha256,
                license_note="Project-authored proposals, not approved standards content.",
                normative_level=4,
                provenance="study",
            )
        )
    policy_text = (
        POLICY
        if catalog is None
        else (
            "Clinical TS review-draft policy v2 (proposed, not qualified signoff)\n"
            + catalog.description
            + "\nAll parameter contracts are in parameter-policies-v2.json.\n"
            "Input assessments, facts and generated records "
            "do not acquire approval from this build.\n"
            "No automatic null flavor, invented value, dictionary version or code is authorized.\n"
            "No regulator-specific submission is targeted.\n"
        )
    )
    policy_filename = (
        "sources/project-policy-v1.txt" if catalog is None else ("sources/project-policy-v2.txt")
    )
    source_bytes[policy_filename] = policy_text.encode()
    sources.append(
        dict(
            source_id="project-policy",
            title="Clinical review-draft project policy (proposed)",
            publisher="trial_design_workflow",
            version="1" if catalog is None else "2",
            url=None,
            publication_date=None,
            retrieval_date=None,
            local_filename=policy_filename,
            sha256=sha256(policy_text.encode()),
            license_note="Project-authored implementation policy.",
            normative_level=4,
            provenance="study",
        )
    )
    snapshot = read_codetable(paths["ct_relationships"], spec.ct_release)
    terms = read_ct_pdf(
        paths["ct"],
        spec.ct_release,
        {"C66738", "C67152"} | {r.codelist for p in snapshot.parameters for r in p.responses},
    )
    raw_discrepancies = verify_codetable(snapshot, terms)
    reconciliation = None
    discrepancies = raw_discrepancies
    if spec.source_precedence == "selected_ct_authoritative":
        reconciliation = reconcile_codetable(snapshot, terms)
        snapshot = reconciliation.effective_snapshot
        discrepancies = reconciliation.unresolved
        precedence_content = json_bytes(
            dict(
                policy_id=POLICY_ID,
                ct_release=spec.ct_release,
                rules=POLICY_RULES,
                authorization="User instruction: resolve source differences using the latest "
                "selected CT. This does not approve applicability policies "
                "or the clinical profile.",
                scope="Standards-source reconciliation only; "
                "not a rule for repairing study workbooks.",
            )
        )
        source_bytes["sources/source-precedence-v1.json"] = precedence_content
        sources.append(
            dict(
                source_id="source-precedence",
                title="User-directed selected CT precedence",
                publisher="trial_design_workflow",
                version="1",
                url=None,
                publication_date=None,
                retrieval_date=None,
                local_filename="sources/source-precedence-v1.json",
                sha256=sha256(precedence_content),
                license_note="Project-authored reconciliation policy.",
                normative_level=4,
                provenance="study",
            )
        )
    conformance = read_ts_conformance(paths["conformance"])
    guide = PdfReader(paths["sdtmig"])
    if "7.4.2 Trial Summary" not in guide.pages[416].extract_text():
        raise ValueError("Pinned IG page/section anchor has changed")
    profile, content = assemble_profile(spec, sources, snapshot, terms, discrepancies)
    if catalog:
        profile, content = compile_catalog(profile, content, catalog)
    if reconciliation:
        profile, content = annotate_reconciliation(profile, content, reconciliation, terms)
    with TemporaryDirectory(prefix="trial-ts-clinical-") as temporary:
        staging = Path(temporary)
        for name, data in source_bytes.items():
            target = staging / name
            target.parent.mkdir(parents=True, exist_ok=True)
            target.write_bytes(data)
        output.mkdir(parents=True, exist_ok=False)
        build_profile(profile, staging, output / "profile")
    export_review(profile, content, output / "review")
    artifacts = {
        "content.json": content.model_dump(mode="json"),
        "source_discrepancies.json": [d.model_dump() for d in raw_discrepancies],
        "ts_conformance_index.json": [r.model_dump() for r in conformance],
        "ct_term_evidence.json": [t.model_dump() for t in terms],
        "build_spec.json": spec.model_dump(
            mode="json", exclude={"parameter_policy"} if catalog is None else set()
        ),
        "fact_input_contracts.json": {
            "purpose": "Proposed Step 2 input constraints; no study rule evaluator is added here.",
            "reviewed_trt_applicability": {
                "allowed": ["present", "absent"],
                "requires_human_design_review": True,
            },
            "reviewed_curtrt_applicability": {
                "allowed": ["present", "absent"],
                "requires_human_design_review": True,
            },
            "unknown_policy": "Missing, proposed, conflicting or invalid input must be unknown; "
            "never coerce it to absent. Enforce these constraints before future rule evaluation.",
        },
    }
    if reconciliation:
        artifacts["source_resolutions.json"] = {
            "policy_id": reconciliation.policy_id,
            "selected_ct_release": reconciliation.selected_release,
            "resolutions": [r.model_dump(mode="json") for r in reconciliation.resolutions],
            "unresolved_count": len(reconciliation.unresolved),
            "profile_approved": False,
        }
        artifacts["unresolved_source_discrepancies.json"] = [
            d.model_dump() for d in reconciliation.unresolved
        ]
        (output / "source_resolutions.csv").write_bytes(
            readable_csv(
                [
                    dict(
                        parameter=r.discrepancy.tsparmcd,
                        original_code=r.discrepancy.code,
                        raw_locator=r.discrepancy.locator,
                        disposition=r.disposition,
                        raw_concept_code=r.raw_concept_code,
                        raw_term_code=r.raw_term_code,
                        raw_value=r.raw_value,
                        selected_concept_code=r.selected_concept_code,
                        selected_term_code=r.selected_term_code,
                        selected_value=r.selected_value,
                        codelist=r.codelist,
                        rationale=r.rationale,
                        ct_evidence="; ".join(ref.locator for ref in r.authority_refs),
                    )
                    for r in reconciliation.resolutions
                ],
                [
                    "parameter",
                    "original_code",
                    "raw_locator",
                    "disposition",
                    "raw_concept_code",
                    "raw_term_code",
                    "raw_value",
                    "selected_concept_code",
                    "selected_term_code",
                    "selected_value",
                    "codelist",
                    "rationale",
                    "ct_evidence",
                ],
            )
        )
    if catalog:
        artifacts["fact_input_contracts.json"] = {
            "purpose": "Proposed constraints for the future Step 2 input boundary; "
            "no study selection engine or approval workflow is added in Step 0.",
            "conditions": {
                name: condition.model_dump(mode="json")
                for name, condition in sorted(catalog.conditions.items())
            },
            "requires_human_design_review": True,
            "unknown_policy": "Only documented reviewed assessments in a condition's "
            "explicit include/exclude domain are usable. Missing, proposed, conflicting, "
            "invalid or unsupported third values must be unknown, including under NOT. "
            "Never interpret any arbitrary unequal value as the exclude value.",
        }
    # Omit newly optional absent recipe metadata, preserving v1 build-spec bytes.
    for input_spec in artifacts["build_spec.json"]["inputs"].values():
        for key in ("url", "retrieval_date"):
            if input_spec.get(key) is None:
                input_spec.pop(key, None)
    if spec.source_precedence == "strict":
        artifacts["build_spec.json"].pop("source_precedence", None)
    if before:
        artifacts["semantic_diff.json"] = semantic_diff(before, profile)
    for name, payload in artifacts.items():
        (output / name).write_bytes(json_bytes(payload))
    hashes = {
        p.relative_to(output).as_posix(): sha256(p.read_bytes())
        for p in sorted(output.rglob("*"))
        if p.is_file()
    }
    (output / "bundle_checksums.json").write_bytes(json_bytes(hashes))
    assert content.profile_content_sha256 == content_digest(profile)
    return output
