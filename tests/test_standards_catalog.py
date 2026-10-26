"""Complete policy coverage and source-specific cases using synthetic standards.

The small test-only interpreter checks declarative policy scenarios including the
closed input domain. It is not a production Study Facts/selection implementation.
"""

from collections import Counter
from pathlib import Path

import pytest
from pydantic import ValidationError

from trial_design_workflow.serialization import sha256
from trial_design_workflow.standards.acquisition import (
    CodetableParameter,
    CodetableSnapshot,
    ExtractedTerm,
    ResponseLink,
    verify_codetable,
)
from trial_design_workflow.standards.catalog import (
    ConditionPolicy,
    ParameterPolicyCatalog,
    compile_catalog,
)
from trial_design_workflow.standards.clinical import (
    ClinicalBuildSpec,
    assemble_profile,
    build_clinical_review,
)
from trial_design_workflow.standards.models import StandardsProfile
from trial_design_workflow.standards.review import validate_content
from trial_design_workflow.standards.validation import validate_profile

ROOT = Path(__file__).parents[1]
CATALOG = ROOT / "config/standards/ts-parameter-policies-v2.json"
CODES = [
    p.code for p in ParameterPolicyCatalog.model_validate_json(CATALOG.read_bytes()).parameters
]


@pytest.fixture(scope="module")
def compiled():
    catalog = ParameterPolicyCatalog.model_validate_json(CATALOG.read_bytes())
    roles = ("sdtm", "sdtmig", "ct", "ct_relationships", "conformance")
    spec = ClinicalBuildSpec(
        schema_version="1",
        profile_id="synthetic-complete",
        profile_version="2",
        created_at="2026-01-01T00:00:00Z",
        ct_release="fictional",
        inputs={
            r: dict(
                filename=f"{r}.txt", sha256="0" * 64, version="fictional", publication_date=None
            )
            for r in roles
        },
    )
    sources = [
        dict(
            source_id=r,
            title="Synthetic standards fixture",
            publisher="Tests",
            version="fictional",
            url=None,
            publication_date=None,
            retrieval_date=None,
            local_filename=f"sources/{r}.txt",
            sha256="0" * 64,
            license_note="Synthetic fixture",
            normative_level=5,
            provenance="synthetic",
        )
        for r in (*roles, "project-policy", "parameter-policies")
    ]
    terms, parameters = [], []
    for i, policy in enumerate(catalog.parameters, 1000):
        concept = f"C{i}"
        label = f"Synthetic {policy.code}"
        for cl, value in (("C66738", policy.code), ("C67152", label)):
            terms.append(
                ExtractedTerm(
                    codelist=cl,
                    code=concept,
                    value=value,
                    definition=f"Synthetic definition of {policy.code}",
                    pages=(1,),
                )
            )
        links = ()
        if policy.response == "codetable":
            links = (
                ResponseLink(
                    codelist="C900",
                    codelist_name="Fictional response",
                    term_code="C901",
                    value="SYNTHETIC",
                    locator="E2:F2",
                ),
            )
        if policy.code == "FDATCHSP":
            links += (
                ResponseLink(
                    codelist="C900",
                    codelist_name="Fictional response",
                    term_code="CNEW",
                    value="Unverified",
                    locator="E3:F3",
                ),
            )
        parameters.append(
            CodetableParameter(
                concept_code="C99999" if policy.code == "BRIND" else concept,
                tsparmcd=policy.code,
                tsparm=label,
                locators=("A2:C2",),
                responses=links,
            )
        )
    terms.append(
        ExtractedTerm(
            codelist="C900",
            code="C901",
            value="SYNTHETIC",
            definition="Fictional response",
            pages=(1,),
        )
    )
    snapshot = CodetableSnapshot(release="fictional", parameters=tuple(parameters))
    disagreements = verify_codetable(snapshot, tuple(terms))
    profile, content = assemble_profile(spec, sources, snapshot, tuple(terms), disagreements)
    # Keep synthetic standards explicitly nonclinical in tests.
    payload = profile.model_dump(mode="json")
    payload["manifest"]["scope"] = "synthetic"
    profile = StandardsProfile.model_validate(payload)
    profile, content = compile_catalog(profile, content, catalog)
    return catalog, profile, content


def scenario(compiled, code, observations=None, *, reviewed=True):
    """Interpret only the declared, validated condition domain for contract tests."""
    catalog, profile, _ = compiled
    policy = next(p for p in catalog.parameters if p.code == code)
    condition = catalog.conditions[policy.condition]
    rule = next(r for r in profile.applicability_rules if r.rule_id == f"{code}-app-v1")
    if condition.mode != "conditional":
        return rule.on_true
    value = (observations or {}).get(condition.fact_key)
    if not reviewed or value not in {condition.include_value, condition.exclude_value}:
        return rule.on_unknown
    return rule.on_true if value == condition.include_value else rule.on_false


@pytest.mark.parametrize("code", CODES)
def test_every_parameter_has_closed_condition_and_concrete_value_contract(compiled, code):
    catalog, profile, content = compiled
    policy = next(p for p in catalog.parameters if p.code == code)
    condition = catalog.conditions[policy.condition]
    parameter = next(p for p in profile.parameters if p.tsparmcd == code)
    derivation = next(d for d in profile.derivations if d.derivation_id == parameter.derivation_id)
    row = next(p for p in content.parameters if p.tsparmcd == code)
    assert derivation.fact_keys and derivation.source_requirement != "manual"
    assert row.value_source.status == "source_backed"
    assert row.inclusion.basis == "project_policy"
    assert (
        row.derivation.status == row.cardinality.status == row.exceptions.status == "source_backed"
    )
    assert row.value_source.text.find(policy.source_detail) >= 0
    if condition.mode == "conditional":
        assert scenario(compiled, code, {condition.fact_key: condition.include_value}) == "include"
        assert scenario(compiled, code, {condition.fact_key: condition.exclude_value}) == "exclude"
        assert scenario(compiled, code) == "manual_assessment"
        assert scenario(compiled, code, {condition.fact_key: "UNKNOWN"}) == "manual_assessment"
        assert (
            scenario(compiled, code, {condition.fact_key: condition.exclude_value}, reviewed=False)
            == "manual_assessment"
        )
    elif condition.mode == "always":
        # Missing value does not change applicability, including actual-study values.
        assert scenario(compiled, code) == "include"
        assert parameter.min_records == 1
    else:
        assert scenario(compiled, code) == "exclude"
        assert "legal status" in parameter.review_reason


def test_design_specific_cases_do_not_use_missingness_or_indicator_response_as_exclusion(compiled):
    assert scenario(compiled, "RANDOM", {"randomization": "N"}) == "include"
    assert scenario(compiled, "ADAPT", {"design.study_type": "OBSERVATIONAL"}) == "exclude"
    assert scenario(compiled, "OBSMODEL", {"design.study_type": "OBSERVATIONAL"}) == "include"
    assert scenario(compiled, "OBSMODEL", {"design.study_type": "INTERVENTIONAL"}) == "exclude"
    assert (
        scenario(compiled, "OBSMODEL", {"design.study_type": "EXPANDED ACCESS"})
        == "manual_assessment"
    )
    assert scenario(compiled, "RANDQT", {"randomization": "N"}) == "exclude"
    assert scenario(compiled, "RANDQT") == "manual_assessment"
    assert (
        scenario(compiled, "INDIC", {"eligibility.healthy_subjects_allowed": "Y"})
        == "manual_assessment"
    )
    assert scenario(compiled, "INDIC", {"design.indication_applicable": "Y"}) == "include"
    assert scenario(compiled, "CURTRT", {"design.add_on_product": "N"}) == "manual_assessment"
    assert scenario(compiled, "CURTRT", {"reviewed_curtrt_applicability": "absent"}) == "exclude"
    assert (
        scenario(compiled, "BRDNAIND", {"design.specimen_collection_planned": "Y"})
        == "manual_assessment"
    )
    assert scenario(compiled, "BRDNAIND", {"actual.biospecimens_retained": "N"}) == "exclude"


def test_actual_dates_country_and_durations_have_different_contracts(compiled):
    _, profile, content = compiled
    derivations = {d.derivation_id: d for d in profile.derivations}
    for code in ("SSTDTC", "SENDTC", "ACTSUB", "BRIND", "RTSPCDES", "EGBLIND"):
        assert derivations[f"{code}-derive-v1"].source_requirement == "study_data"
    assert derivations["FCNTRY-derive-v1"].source_requirement == "sponsor"
    rows = {p.tsparmcd: p for p in content.parameters}
    assert "excluding screen failures" in rows["SSTDTC"].value_source.text
    assert "IRB approval" in rows["FCNTRY"].value_source.text
    assert "not total calendar" in rows["LENGTH"].value_source.text
    assert "whole trial" in rows["PLNTRDUR"].value_source.text
    ratio = derivations["RANDQT-derive-v1"]
    assert ratio.transform == "ratio_from_counts"
    assert set(ratio.fact_keys) == {
        "design.planned_investigational_exposed_count",
        "design.planned_total_count",
    }
    assert "denominator" in rows["RANDQT"].derivation.text
    assert "positive" in rows["RANDQT"].derivation.text


def test_grouping_preserves_objectives_contacts_and_dose_dimensions(compiled):
    _, profile, _ = compiled
    parameters = {p.tsparmcd: p for p in profile.parameters}
    assert parameters["OBJPRIM"].tsgrpid_rule_id == parameters["OUTMSPRI"].tsgrpid_rule_id
    assert parameters["CONNAME"].tsgrpid_rule_id == parameters["CONEMAIL"].tsgrpid_rule_id
    assert parameters["DCUTDTC"].tsgrpid_rule_id == parameters["DCUTDESC"].tsgrpid_rule_id
    assert parameters["DOSU"].tsgrpid_rule_id == parameters["DOSE"].tsgrpid_rule_id
    assert "dose_level_id" in parameters["DOSE"].repeat_key
    assert "analysis_id" in parameters["OUTMSPRI"].repeat_key
    assert len({p.tsparmcd for p in profile.parameters}) == 133
    assert Counter(p.base_disposition for p in profile.parameters) == {
        "always": 48,
        "conditional": 61,
        "out_of_scope": 24,
    }


def test_catalog_cannot_hide_source_conflicts_or_approve_the_profile(compiled):
    _, profile, content = compiled
    report = validate_content(profile, content)
    gaps = {(f.code, f.location) for f in report.findings}
    assert ("CONTENT_SOURCE_GAP", "BRIND.response") in gaps
    assert ("CONTENT_SOURCE_GAP", "FDATCHSP.response") in gaps
    assert ("RESPONSE_CONTRACT_BLOCKED", "BRIND.response") in gaps
    assert not any(f.code == "VALUE_NOT_IMPLEMENTED" for f in report.findings)
    assert not any(
        f.code in {"INCLUSION_NOT_IMPLEMENTED", "SOURCE_NOT_IMPLEMENTED"} for f in report.findings
    )
    assert not any(m.term_code == "CNEW" for m in profile.value_maps)
    assert profile.manifest.status == "draft" and profile.manifest.signoff is None
    structural = validate_profile(profile, allow_draft=True)
    assert structural.valid


def test_policy_coverage_duplicates_and_condition_domains_fail_closed(compiled):
    catalog, profile, content = compiled
    payload = catalog.model_dump(mode="json")
    payload["parameters"].pop()
    incomplete = ParameterPolicyCatalog.model_validate(payload)
    with pytest.raises(ValueError, match="exactly the pinned"):
        compile_catalog(profile, content, incomplete)
    payload["parameters"].append(payload["parameters"][0])
    with pytest.raises(ValidationError, match="duplicate"):
        ParameterPolicyCatalog.model_validate(payload)
    with pytest.raises(ValidationError, match="distinct"):
        ConditionPolicy(
            mode="conditional",
            explanation="Synthetic",
            fact_key="fact",
            include_value="Y",
            exclude_value="Y",
            source_requirement="protocol",
        )


def test_real_recipe_pins_catalog_bytes_and_changed_hash_fails_before_output(tmp_path):
    spec = ClinicalBuildSpec.model_validate_json(
        (ROOT / "config/standards/clinical-review-2026-09-25-v2.json").read_bytes()
    )
    assert spec.parameter_policy.sha256 == sha256(CATALOG.read_bytes())
    assert spec.inputs["errata"].url.startswith("https://www.cdisc.org/")
    payload = spec.model_dump(mode="json")
    for role, source in payload["inputs"].items():
        source["filename"] = f"{role}.txt"
        (tmp_path / source["filename"]).write_text("synthetic")
        source["sha256"] = sha256(b"synthetic")
    (tmp_path / payload["parameter_policy"]["filename"]).write_text("changed catalog bytes")
    spec = ClinicalBuildSpec.model_validate(payload)
    with pytest.raises(ValueError, match="catalog hash"):
        build_clinical_review(spec, tmp_path, tmp_path / "out", policy_root=tmp_path)
    assert not (tmp_path / "out").exists()
