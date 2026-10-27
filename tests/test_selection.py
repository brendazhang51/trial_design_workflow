"""Step 2 truth tables, closed domains, complete audit and unapproved-fact boundaries."""

import pytest
from pipeline_fixtures import make_inputs, make_profile

from trial_design_workflow.selection import evaluate_predicate, load_runtime, select_parameters
from trial_design_workflow.standards.models import Predicate
from trial_design_workflow.study_context import StudyContext, context_digest, digest


@pytest.fixture
def setup(tmp_path):
    runtime = load_runtime(make_profile(tmp_path), allow_draft=True)
    _, context = make_inputs(tmp_path / "inputs")
    return context, runtime


def changed(context, key, **values):
    payload = context.model_dump(mode="json")
    for fact in payload["facts"]:
        if fact["fact_key"] == key:
            fact.update(values)
    return StudyContext.model_validate(payload)


def test_every_parameter_has_one_auditable_decision(setup):
    context, runtime = setup
    result = select_parameters(context, runtime, allow_draft=True)
    assert len(result.decisions) == len(runtime.profile.parameters) == 11
    decisions = {d.tsparmcd: d for d in result.decisions}
    assert decisions["EXCL"].decision == "exclude"
    assert decisions["COND"].decision == "include"
    assert decisions["RATIO"].decision == "include"
    assert all(
        d.rule_id and d.rule_version and d.rationale and d.authority_refs for d in result.decisions
    )
    assert decisions["COND"].predicate.fact_ids and decisions["COND"].input_fact_hashes


@pytest.mark.parametrize(
    "value,expected",
    [
        ("INTERVENTIONAL", "include"),
        ("OBSERVATIONAL", "exclude"),
        ("UNKNOWN", "manual_assessment"),
        ("interventional", "manual_assessment"),
    ],
)
def test_closed_domain_does_not_treat_any_unequal_value_as_false(setup, value, expected):
    context, runtime = setup
    context = changed(
        context,
        "study_type",
        reviewed_value=value,
        review={**context.facts[0].review.model_dump(mode="json"), "action": "correct"},
    )
    result = select_parameters(context, runtime, allow_draft=True)
    assert next(d for d in result.decisions if d.tsparmcd == "COND").decision == expected


def test_unreviewed_or_missing_facts_stay_unknown_even_under_not(setup):
    context, runtime = setup
    pending = changed(
        context, "study_type", status="needs_review", review=None, reviewed_value=None
    )
    pred = Predicate(
        op="not",
        children=[Predicate(op="fact_equals", fact_key="study_type", value="INTERVENTIONAL")],
    )
    assert evaluate_predicate(pred, pending, runtime).result is None
    payload = context.model_dump(mode="json")
    payload["facts"] = [f for f in payload["facts"] if f["fact_key"] != "study_type"]
    missing = StudyContext.model_validate(payload)
    assert evaluate_predicate(pred, missing, runtime).result is None
    result = select_parameters(missing, runtime, allow_draft=True)
    decision = next(d for d in result.decisions if d.tsparmcd == "COND")
    assert (
        decision.decision == "manual_assessment" and "study_type" in decision.missing_prerequisites
    )


def test_missing_value_does_not_exclude_an_always_parameter(setup):
    context, runtime = setup
    pending = changed(
        context, "planned_enrollment", status="needs_review", review=None, reviewed_value=None
    )
    decision = next(
        d
        for d in select_parameters(pending, runtime, allow_draft=True).decisions
        if d.tsparmcd == "PLANSUB"
    )
    assert decision.decision == "include" and "VALUE_NOT_REVIEWED" in decision.exception_codes


def test_boolean_groups_in_and_present_are_three_valued(setup):
    context, runtime = setup
    yes = Predicate(op="fact_equals", fact_key="randomization", value="Y")
    unknown = Predicate(op="fact_present", fact_key="not_recorded")
    assert (
        evaluate_predicate(Predicate(op="all", children=[yes, unknown]), context, runtime).result
        is None
    )
    assert (
        evaluate_predicate(Predicate(op="any", children=[yes, unknown]), context, runtime).result
        is True
    )
    assert (
        evaluate_predicate(
            Predicate(op="fact_in", fact_key="study_type", values=["INTERVENTIONAL"]),
            context,
            runtime,
        ).result
        is True
    )
    assert (
        evaluate_predicate(
            Predicate(op="fact_status", fact_key="study_type", value="reviewed"), context, runtime
        ).result
        is True
    )
    assert (
        evaluate_predicate(
            Predicate(op="fact_present", fact_key="study_title"), context, runtime
        ).result
        is True
    )
    assert (
        evaluate_predicate(Predicate(op="rule_ref", rule_id="EXCL-rule"), context, runtime).result
        is False
    )


def test_contradictions_do_not_choose_a_winner(setup):
    context, runtime = setup
    payload = context.model_dump(mode="json")
    duplicate = next(f.copy() for f in payload["facts"] if f["fact_key"] == "randomization")
    duplicate.update(
        fact_id="second-randomization",
        reviewed_value="N",
        review={**duplicate["review"], "action": "correct"},
    )
    payload["facts"].append(duplicate)
    context = StudyContext.model_validate(payload)
    decision = next(
        d
        for d in select_parameters(context, runtime, allow_draft=True).decisions
        if d.tsparmcd == "RATIO"
    )
    assert decision.decision == "manual_assessment"
    assert "FACT_CONFLICT" in decision.exception_codes


def test_stable_under_fact_and_source_ordering(setup):
    context, runtime = setup
    payload = context.model_dump(mode="json")
    payload["facts"].reverse()
    payload["sources"].reverse()
    reordered = StudyContext.model_validate(payload)
    assert context_digest(context) == context_digest(reordered)
    assert digest(select_parameters(context, runtime, allow_draft=True)) == digest(
        select_parameters(reordered, runtime, allow_draft=True)
    )


@pytest.mark.parametrize("scenario", ["positive", "negative", "unknown", "missing"])
def test_full_133_parameter_catalog_runs_through_production_selector(scenario):
    from test_standards_catalog import compiled

    from trial_design_workflow.extraction.pdf import parse_page
    from trial_design_workflow.selection import RuntimeProfile
    from trial_design_workflow.serialization import sha256
    from trial_design_workflow.standards.models import StandardsProfile
    from trial_design_workflow.standards.validation import content_digest
    from trial_design_workflow.study_context import SourceSnapshot

    catalog, profile, content = compiled.__wrapped__()
    policy_document = catalog.model_dump_json()
    payload = profile.model_dump(mode="json")
    source = next(s for s in payload["sources"] if s["source_id"] == "parameter-policies")
    source.update(sha256=sha256(policy_document.encode()), version=catalog.version)
    profile = StandardsProfile.model_validate(payload)
    notes = content.model_dump(mode="json")
    notes["profile_content_sha256"] = content_digest(profile)
    from trial_design_workflow.standards.review import ReviewContent

    runtime = RuntimeProfile(
        profile=profile,
        content=ReviewContent.model_validate(notes),
        policy_source_id="parameter-policies",
        policy_document=policy_document,
    )
    domains = runtime.domains()
    values = {}
    for key, domain in domains.items():
        if scenario == "missing":
            continue
        if scenario == "unknown":
            value = "UNASSESSED"
        elif set(domain.values) == {"INTERVENTIONAL", "OBSERVATIONAL"}:
            value = "INTERVENTIONAL" if scenario == "positive" else "OBSERVATIONAL"
        elif set(domain.values) == {"Y", "N"}:
            value = "Y" if scenario == "positive" else "N"
        else:
            value = "present" if scenario == "positive" else "absent"
        values[key] = value
    snapshots, facts = [], []
    for source_type in sorted({d.source_type for d in domains.values()}):
        lines = [
            key + ": " + value
            for key, value in sorted(values.items())
            if domains[key].source_type == source_type
        ]
        text = "\n".join(lines)
        source_id = "synthetic-" + source_type
        source_hash = sha256(text.encode())
        snapshots.append(
            SourceSnapshot(
                source_id=source_id,
                sha256=source_hash,
                version="fixture-1",
                source_type=source_type,
                format="text",
                parser="utf8-text-v1",
                pages=[parse_page(text, 0)[0]],
            )
        )
        for key, value in sorted(values.items()):
            if domains[key].source_type != source_type:
                continue
            quote = key + ": " + value
            start = text.index(quote)
            facts.append(
                dict(
                    fact_id=key,
                    fact_key=key,
                    source_type=source_type,
                    raw_value=value,
                    proposed_value=value,
                    reviewed_value=value,
                    status="reviewed",
                    review=dict(
                        reviewer_id="SIMULATED_TEST_ONLY",
                        reviewed_at="2026-01-01T00:00:00Z",
                        action="approve",
                        rationale="Synthetic condition matrix",
                    ),
                    evidence=[
                        dict(
                            source_id=source_id,
                            source_sha256=source_hash,
                            pdf_page_index=0,
                            start=start,
                            end=start + len(quote),
                            quote=quote,
                            locator="Synthetic matrix line",
                        )
                    ],
                )
            )
    context = StudyContext(
        schema_version="1",
        purpose="validated_study_context",
        study_id="SYN-133",
        identity_review=None,
        sources=snapshots,
        facts=facts,
        complete_collections=[],
    )
    result = select_parameters(context, runtime, allow_draft=True)
    assert len(result.decisions) == 133
    decisions = {d.tsparmcd: d.decision for d in result.decisions}
    for policy in catalog.parameters:
        condition = catalog.conditions[policy.condition]
        if condition.mode == "always":
            expected = "include"
        elif condition.mode == "out_of_scope":
            expected = "exclude"
        elif scenario in {"missing", "unknown"}:
            expected = "manual_assessment"
        else:
            expected = (
                "include" if values[condition.fact_key] == condition.include_value else "exclude"
            )
        assert decisions[policy.code] == expected, (scenario, policy.code)
