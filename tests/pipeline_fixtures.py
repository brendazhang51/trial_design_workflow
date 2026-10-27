"""Fictional standards and reviewed facts; never imports clinical source documents."""

import json
from pathlib import Path

from trial_design_workflow.generation import BASE_COLUMNS
from trial_design_workflow.serialization import sha256
from trial_design_workflow.standards.models import StandardsProfile
from trial_design_workflow.standards.profile import build_profile, json_bytes
from trial_design_workflow.standards.review import ReviewContent, initialize_content
from trial_design_workflow.standards.validation import content_digest
from trial_design_workflow.study_context import CuratedInputs, read_curated

REVIEW = {
    "reviewer_id": "SIMULATED_TEST_ONLY",
    "reviewed_at": "2026-01-01T00:00:00Z",
    "action": "approve",
    "rationale": "Synthetic reference fixture, not a real human approval.",
}
TEXT = (
    "Study SYN-001\nTitle: A fictional study\nPlanned count: 1,200\nRandomization: Yes\n"
    "Study type: INTERVENTIONAL\nArm A Alpha\nArm B Beta\nDate: 2026-02\nDuration: P12W\n"
    "Decimal: 1.250 mg\nNumerator 120; denominator 240\nNo upper age limit\n"
)


def make_profile(root: Path):
    fixture = Path(__file__).parent / "fixtures/standards/minimal-profile/profile.json"
    payload = json.loads(fixture.read_bytes())
    payload["manifest"].update(profile_id="fictional-pipeline", profile_version="1")
    payload["sources"][0]["version"] = "3.4"
    for role in payload["manifest"]["standards"].values():
        if role["status"] == "pinned":
            role["version"] = "3.4"
    source_bytes = (
        Path(__file__).parent / "fixtures/standards/minimal-profile/sources/synthetic-standard.txt"
    ).read_bytes()
    payload["sources"][0]["sha256"] = sha256(source_bytes)
    payload["parameters"] = []
    payload["applicability_rules"] = []
    payload["value_profiles"] = []
    payload["derivations"] = []
    payload["terminology"] = []
    payload["fact_keys"] = []
    payload["value_maps"] = []
    payload["grouping_rules"] = [
        dict(
            rule_id="arm-group",
            fact_keys=["arm_id"],
            authority_refs=[dict(source_id="synthetic", locator="Fictional group contract")],
        )
    ]
    refs = [dict(source_id="synthetic", locator="Fictional rule; Assumption 4 / 4.5.3.2")]
    specs = [
        ("TITLE", "study_title", "text", "copy_text", None, ()),
        ("PLANSUB", "planned_enrollment", "integer", "format_integer", None, ()),
        ("RANDOM", "randomization", "controlled", "map_exact_ct", None, ()),
        (
            "COND",
            "conditional_value",
            "text",
            "copy_text",
            dict(op="fact_equals", fact_key="study_type", value="INTERVENTIONAL"),
            (),
        ),
        ("EXT", "intervention", "external", "manual", None, ()),
        ("DATE", "date", "date", "preserve_iso8601_precision", None, ()),
        ("DUR", "duration", "duration", "preserve_iso8601_duration", None, ()),
        ("DEC", "decimal", "decimal", "format_decimal", None, ()),
        (
            "RATIO",
            "numerator",
            "decimal",
            "ratio_from_counts",
            dict(op="fact_equals", fact_key="randomization", value="Y"),
            (),
        ),
        ("REPEAT", "repeated_value", "text", "copy_text", None, ("arm_id",)),
        ("EXCL", "excluded_value", "text", "copy_text", None, ()),
    ]
    for i, (code, key, typ, transform, predicate, repeat) in enumerate(specs):
        include = code != "EXCL"
        payload["parameters"].append(
            dict(
                tsparmcd=code,
                tsparm="Fictional " + code,
                concept_code="SYN" + str(i),
                ct_release="3.4",
                parameter_status="active",
                applicability_rule_id=code + "-rule",
                base_disposition="conditional"
                if predicate
                else "always"
                if include
                else "out_of_scope",
                authority_scope="synthetic",
                authority_refs=refs,
                min_records=1 if include else 0,
                max_records=None if repeat else 1,
                repeat_key=repeat,
                tsgrpid_rule_id="arm-group" if repeat else None,
                sort_key=f"{i:03d}",
                value_profile_id=code + "-value",
                fact_key=key,
                derivation_id=code + "-derive",
                value_map_id="YN-map" if typ == "controlled" else None,
                automation_level="propose_only" if typ == "external" else "deterministic",
                evidence_requirements="Fictional exact source quote",
                review_reason="Synthetic fixture only",
                notes="Not clinical standards",
            )
        )
        payload["applicability_rules"].append(
            dict(
                rule_id=code + "-rule",
                version="1",
                priority=i,
                predicate=predicate,
                on_true="include" if include else "exclude",
                on_false="exclude" if predicate or not include else "include",
                on_unknown="manual_assessment",
                explanation="Fictional applicability contract",
                authority_refs=refs,
            )
        )
        payload["value_profiles"].append(
            dict(
                value_profile_id=code + "-value",
                value_type=typ,
                response_terminology="Fictional CT"
                if typ == "controlled"
                else "Fictional Dictionary"
                if typ == "external"
                else None,
                response_codelist="SYN-YN" if typ == "controlled" else None,
                allow_tsvalnf=False,
                allowed_null_flavors=[],
                external_source_required=typ == "external",
                target_fields=["TSVAL", "TSVALCD", "TSVCDREF", "TSVCDVER"]
                if typ in {"controlled", "external"}
                else ["TSVAL"],
                long_text_policy="block_for_review",
                authority_refs=refs,
            )
        )
        keys = ["numerator", "denominator"] if code == "RATIO" else [key]
        payload["derivations"].append(
            dict(
                derivation_id=code + "-derive",
                version="1",
                fact_keys=keys,
                transform=transform,
                source_requirement="protocol",
                authority_refs=refs,
            )
        )
        payload["fact_keys"].extend(keys)
        payload["terminology"].extend(
            [
                dict(
                    release="3.4",
                    codelist=cl,
                    code="SYN" + str(i),
                    value=value,
                    status="active",
                    source_id="synthetic",
                )
                for cl, value in (("C66738", code), ("C67152", "Fictional " + code))
            ]
        )
    for raw, value, code in (("Y", "YES", "SYN-Y"), ("N", "NO", "SYN-N")):
        payload["terminology"].append(
            dict(
                release="3.4",
                codelist="SYN-YN",
                code=code,
                value=value,
                status="active",
                source_id="synthetic",
            )
        )
        payload["value_maps"].append(
            dict(
                value_map_id="YN-map",
                input_value=raw,
                codelist="SYN-YN",
                term_code=code,
                submission_value=value,
                release="3.4",
                authority_refs=refs,
            )
        )
    payload["fact_keys"] = sorted(set(payload["fact_keys"]) | {"study_type", "arm_id"})
    domain_bytes = json_bytes(
        dict(
            schema_version="1",
            domains=[
                dict(fact_key="randomization", values=["Y", "N"], source_type="protocol"),
                dict(
                    fact_key="study_type",
                    values=["INTERVENTIONAL", "OBSERVATIONAL"],
                    source_type="protocol",
                ),
            ],
        )
    )
    payload["sources"].append(
        dict(
            source_id="condition-input-domains",
            title="Synthetic closed domains",
            publisher="Tests",
            version="1",
            url=None,
            publication_date=None,
            retrieval_date=None,
            local_filename="sources/domains.json",
            sha256=sha256(domain_bytes),
            license_note="Synthetic fixture",
            normative_level=5,
            provenance="synthetic",
        )
    )
    profile = StandardsProfile.model_validate(payload)
    package = root / "standards"
    staging = root / "staging/sources"
    staging.mkdir(parents=True)
    (staging / "synthetic-standard.txt").write_bytes(source_bytes)
    (staging / "domains.json").write_bytes(domain_bytes)
    build_profile(profile, staging.parent, package / "profile")
    content = initialize_content(profile).model_dump(mode="json")
    content["variables"] = [
        dict(
            order=i + 1,
            name=name,
            label="Fictional " + name,
            data_type="Num" if name == "TSSEQ" else "Char",
            role="Synthetic",
            core="Req" if name in {"STUDYID", "DOMAIN", "TSSEQ", "TSPARMCD", "TSPARM"} else "Perm",
            codelist_or_format=None,
            implementation_notes="Fictional metadata only",
            source_refs=refs,
        )
        for i, name in enumerate(BASE_COLUMNS)
    ]
    content["profile_content_sha256"] = content_digest(profile)
    (package / "content.json").write_bytes(
        json_bytes(ReviewContent.model_validate(content).model_dump(mode="json"))
    )
    return package / "profile"


def make_inputs(root: Path):
    root.mkdir(parents=True, exist_ok=True)
    text_path = root / "protocol.txt"
    text_path.write_text(TEXT)
    dictionary = json_bytes(
        {
            "terms": [
                {
                    "code": "SYN-ALPHA",
                    "value": "Alpha",
                    "reference": "Fictional Dictionary",
                    "version": "v1",
                }
            ]
        }
    )
    (root / "dictionary.json").write_bytes(dictionary)
    source = dict(
        source_id="protocol",
        path="protocol.txt",
        sha256=sha256(TEXT.encode()),
        version="v1",
        source_type="protocol",
        format="text",
    )

    def citation(quote):
        start = TEXT.index(quote)
        return dict(
            source_id="protocol",
            source_sha256=source["sha256"],
            pdf_page_index=0,
            printed_page=None,
            start=start,
            end=start + len(quote),
            quote=quote,
            locator="Synthetic line",
        )

    def fact(key, raw, *, reviewed=None, cardinality=None, quote=None):
        value = reviewed if reviewed is not None else raw
        return dict(
            fact_id=key + ":" + (next(iter((cardinality or {}).values()), "singleton")),
            fact_key=key,
            cardinality_key=cardinality or {},
            source_type="protocol",
            raw_value=raw,
            proposed_value=raw,
            reviewed_value=value,
            status="reviewed",
            review={**REVIEW, "action": "approve" if value == raw else "correct"},
            evidence=[citation(quote or raw)],
        )

    facts = [
        fact("study_title", "A fictional study"),
        fact("planned_enrollment", "1,200"),
        fact("randomization", "Yes", reviewed="Y"),
        fact("study_type", "INTERVENTIONAL"),
        fact("conditional_value", "A fictional study"),
        fact("date", "2026-02"),
        fact("duration", "P12W"),
        fact("decimal", "1.250"),
        fact("numerator", "120"),
        fact("denominator", "240"),
        fact("repeated_value", "Alpha", cardinality={"arm_id": "Arm A"}, quote="Arm A Alpha"),
        fact("repeated_value", "Beta", cardinality={"arm_id": "Arm B"}, quote="Arm B Beta"),
    ]
    external = fact("intervention", "Alpha")
    external["coding"] = {"source_id": "dictionary", "record_pointer": "/terms/0"}
    facts.append(external)
    inputs = CuratedInputs(
        schema_version="1",
        purpose="human_curated_study_inputs",
        study_id="SYN-001",
        identity_review=dict(review=REVIEW, evidence=[citation("Study SYN-001")]),
        sources=[
            source,
            dict(
                source_id="dictionary",
                path="dictionary.json",
                sha256=sha256(dictionary),
                version="v1",
                source_type="external",
                format="json",
            ),
        ],
        facts=facts,
    )
    path = root / "reviewed_inputs.json"
    path.write_bytes(json_bytes(inputs.model_dump(mode="json")))
    return path, read_curated(inputs, root)
