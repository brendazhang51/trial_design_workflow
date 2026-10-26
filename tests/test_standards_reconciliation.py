"""Pinned-CT precedence resolves exact source evidence, never study facts or approvals."""

from collections import Counter

import pytest

from trial_design_workflow.standards.acquisition import (
    CodetableParameter,
    CodetableSnapshot,
    ExtractedTerm,
    ResponseLink,
    verify_codetable,
)
from trial_design_workflow.standards.reconciliation import reconcile_codetable


def term(codelist, code, value):
    return ExtractedTerm(
        codelist=codelist, code=code, value=value, definition="Synthetic definition", pages=(1,)
    )


def snapshot(responses, concept="C100", label="Synthetic flag"):
    return CodetableSnapshot(
        release="fictional",
        parameters=(
            CodetableParameter(
                concept_code=concept,
                tsparmcd="X_FLAG",
                tsparm=label,
                locators=("A2:C2",),
                responses=tuple(responses),
            ),
        ),
    )


def response(code, value, row=2, kind="text", codelist="C900"):
    return ResponseLink(
        codelist=codelist,
        codelist_name="Fictional response",
        term_code=code,
        value=value,
        locator=f"E{row}:F{row}",
        source_value_kind=kind,
    )


IDENTITIES = (term("C66738", "C100", "X_FLAG"), term("C67152", "C100", "Synthetic flag"))


def test_nine_source_differences_are_disposed_without_changing_raw_sources():
    terms = (
        *IDENTITIES,
        term("C66738", "C200", "X_MANUAL"),
        term("C67152", "C200", "Synthetic manual"),
        term("C900", "C901", "Y"),
        term("C900", "C902", "N"),
        term("C900", "C903", "Synthetic version A"),
        term("C900", "C904", "Synthetic version B"),
        term("C900", "C905", "3.1.1"),
        term("C900", "C906", "3.1.2"),
        term("C900", "C907", "1.0"),
    )
    raw = snapshot(
        [
            response("C901", "Y"),
            response("C902", "N", 3),
            response("CNEW", "Synthetic version A", 4),
            response("CNEW", "Synthetic version B", 5),
            response("C905", "3.1.1 ", 6),
            response("C906", "3.1.2 ", 7),
            response("C907", "1", 8, "numeric"),
            response("C9999", "OTHER", 9),
        ],
        concept="C999",
    )
    original = raw.model_dump_json()
    assert len(verify_codetable(raw, terms)) == 9
    result = reconcile_codetable(raw, terms)
    assert raw.model_dump_json() == original
    assert len(result.resolutions) == 9 and not result.unresolved
    assert Counter(r.disposition for r in result.resolutions) == {
        "ct_identity_selected": 2,
        "ct_code_from_exact_value": 2,
        "ct_value_canonicalized": 3,
        "response_omitted": 1,
        "ct_only_parameter_manual": 1,
    }
    parameter = result.effective_snapshot.parameters[0]
    assert parameter.concept_code == "C100"
    assert len(parameter.responses) == 7
    assert {r.term_code for r in parameter.responses} == {
        "C901",
        "C902",
        "C903",
        "C904",
        "C905",
        "C906",
        "C907",
    }
    assert "OTHER" not in {r.value for r in parameter.responses}
    assert {r.value for r in parameter.responses} >= {"3.1.1", "3.1.2", "1.0"}
    assert all(r.authority_refs for r in result.resolutions)
    # CT-only membership remains explicitly manual; no fictitious codetable row is created.
    assert "X_MANUAL" not in {p.tsparmcd for p in result.effective_snapshot.parameters}


@pytest.mark.parametrize(
    "value,kind,expected",
    [
        ("1", "numeric", "ct_value_canonicalized"),
        ("1", "text", "unresolved"),
        ("2", "numeric", "unresolved"),
        (" 1.0 ", "text", "ct_value_canonicalized"),
    ],
)
def test_numeric_version_representation_is_not_a_general_text_version_alias(value, kind, expected):
    raw = snapshot([response("C901", value, kind=kind)])
    result = reconcile_codetable(raw, (*IDENTITIES, term("C900", "C901", "1.0")))
    assert result.resolutions[0].disposition == expected


def test_cnew_requires_a_unique_exact_value_in_the_same_codelist():
    raw = snapshot([response("CNEW", "Synthetic version A")])
    result = reconcile_codetable(raw, (*IDENTITIES, term("C900", "C901", "Synthetic version A")))
    assert result.effective_snapshot.parameters[0].responses[0].term_code == "C901"
    assert not result.unresolved
    wrong_list = reconcile_codetable(
        raw, (*IDENTITIES, term("C901", "C901", "Synthetic version A"))
    )
    assert wrong_list.unresolved
    ambiguous = reconcile_codetable(
        raw,
        (
            *IDENTITIES,
            term("C900", "C901", "Synthetic version A"),
            term("C900", "C902", "Synthetic version A"),
        ),
    )
    assert ambiguous.unresolved
    fuzzy = reconcile_codetable(
        snapshot([response("CNEW", "synthetic version A")]),
        (*IDENTITIES, term("C900", "C901", "Synthetic version A")),
    )
    assert fuzzy.unresolved


def test_known_code_conflicting_with_another_known_value_is_not_silently_repaired():
    result = reconcile_codetable(
        snapshot([response("C901", "N")]),
        (*IDENTITIES, term("C900", "C901", "Y"), term("C900", "C902", "N")),
    )
    assert result.unresolved
    assert result.effective_snapshot.parameters[0].responses[0].term_code == "C901"


def test_unavailable_codelist_does_not_prove_a_value_is_absent():
    result = reconcile_codetable(snapshot([response("C999", "OTHER")]), IDENTITIES)
    assert result.unresolved
    assert result.resolutions[0].disposition != "response_omitted"


def test_concept_rebase_requires_exact_paired_parameter_label():
    result = reconcile_codetable(
        snapshot([], concept="C999", label="Different meaning"), IDENTITIES
    )
    assert result.unresolved
    assert result.effective_snapshot.parameters[0].concept_code == "C999"


def test_reconciliation_is_reproducible_and_does_not_fetch_versions():
    raw = snapshot([response("CNEW", "Synthetic version A")])
    terms = (*IDENTITIES, term("C900", "C901", "Synthetic version A"))
    first = reconcile_codetable(raw, terms)
    assert first.model_dump_json() == reconcile_codetable(raw, terms).model_dump_json()
    assert first.selected_release == raw.release == "fictional"
