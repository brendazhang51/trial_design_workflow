"""Synthetic source-layout, source-conflict and draft-policy contract tests."""

from pathlib import Path

import pytest
from openpyxl import Workbook

from trial_design_workflow.standards.acquisition import (
    CodetableParameter,
    CodetableSnapshot,
    ExtractedTerm,
    ResponseLink,
    ct_page_records,
    read_codetable,
    read_ts_conformance,
    verify_codetable,
)
from trial_design_workflow.standards.clinical import (
    ClinicalBuildSpec,
    assemble_profile,
    build_clinical_review,
    variable_metadata,
)
from trial_design_workflow.standards.review import PRIORITY, validate_content


def workbook(path: Path, *, bad_identity=False, value="YES", response_code="C901"):
    book = Workbook()
    sheet = book.active
    sheet.title = "TS_Codetable_Mapping fictional"
    sheet.append(
        [
            "Concept code",
            "TSPARMCD (codelist code = C66738)",
            "TSPARM (codelist code = C67152)",
            None,
            "Concept code",
            "Fictional Response (SYN) (codelist code = C900)",
            None,
        ]
    )
    sheet.append(["C100", "X_TITLE", "Fictional title", None, response_code, value])
    if bad_identity:
        sheet.append(["C101", "X_TITLE", "Conflicting title", None, None, None])
    book.save(path)
    book.close()


def test_codetable_header_release_and_conflicting_identity(tmp_path):
    path = tmp_path / "table.xlsx"
    workbook(path)
    snapshot = read_codetable(path, "fictional")
    assert snapshot.parameters[0].responses[0].value == "YES"
    assert "row 2" in snapshot.parameters[0].responses[0].locator
    with pytest.raises(ValueError, match="selected release"):
        read_codetable(path, "different")
    workbook(path, bad_identity=True)
    with pytest.raises(ValueError, match="Conflicting parameter"):
        read_codetable(path, "fictional")


def test_codetable_numeric_response_and_unresolved_cnew_are_preserved(tmp_path):
    path = tmp_path / "table.xlsx"
    workbook(path, value=3.4)
    parsed = read_codetable(path, "fictional").parameters[0].responses[0]
    assert parsed.value == "3.4" and parsed.source_value_kind == "numeric"
    workbook(path, response_code="CNEW")
    assert read_codetable(path, "fictional").parameters[0].responses[0].term_code == "CNEW"
    workbook(path, value="=1+1")
    with pytest.raises(ValueError, match="formula-based"):
        read_codetable(path, "fictional")


def test_ct_rows_retain_multiline_and_cross_page_definitions():
    records, last = ct_page_records(
        [
            (85, 1090, "NCI Code"),
            (47, 1080, "C100"),
            (160, 1080, "X_TITLE"),
            (387, 1080, "Fictional definition"),
            (387, 1070, "continued"),
            (273, 1070, "Not part of the definition"),
            (700, 1070, "Nor this preferred term"),
        ],
        "C66738",
        1,
    )
    more, last = ct_page_records(
        [
            (85, 1090, "NCI Code"),
            (387, 1080, "over the page"),
            (47, 1070, "C101"),
            (160, 1070, "X_OTHER"),
            (387, 1070, "Second definition"),
        ],
        "C66738",
        2,
        last,
    )
    assert records[0]["definition_parts"] == ["Fictional definition", "continued", "over the page"]
    assert records[0]["pages"] == [1, 2]
    assert more[0]["code"] == "C101"
    with pytest.raises(ValueError, match="column header"):
        ct_page_records([], "C66738", 1)
    with pytest.raises(ValueError, match="Orphan"):
        ct_page_records([(85, 1090, "NCI Code"), (387, 1080, "Orphan")], "C66738", 1)


def term(codelist, code, value):
    return ExtractedTerm(
        codelist=codelist, code=code, value=value, definition="Fictional definition", pages=(1,)
    )


def test_ct_is_identity_universe_and_discrepancies_never_mint_codes():
    snapshot = CodetableSnapshot(
        release="fictional",
        parameters=(
            CodetableParameter(
                concept_code="C999",
                tsparmcd="X_TITLE",
                tsparm="Fictional title",
                locators=("A2:C2",),
                responses=(
                    ResponseLink(
                        codelist="C900",
                        codelist_name="Fictional",
                        term_code="CNEW",
                        value="UNVERIFIED",
                        locator="E2:F2",
                    ),
                ),
            ),
        ),
    )
    terms = (
        term("C66738", "C100", "X_TITLE"),
        term("C67152", "C100", "Fictional title"),
        term("C66738", "C101", "X_EXTRA"),
        term("C67152", "C101", "Fictional extra"),
    )
    discrepancies = verify_codetable(snapshot, terms)
    assert {d.code for d in discrepancies} == {
        "CODETABLE_IDENTITY_MISMATCH",
        "CODETABLE_CT_MISMATCH",
        "CODETABLE_UNIVERSE_MISMATCH",
    }
    assert "X_EXTRA" in {d.tsparmcd for d in discrepancies}
    assert all(t.code != "CNEW" for t in terms)


def test_conformance_filters_ts_and_v34_without_importing_removed_rules(tmp_path):
    book = Workbook()
    sheet = book.active
    sheet.title = "SDTMIG Conformance Rules v2.0"
    sheet.append(
        [
            "Rule ID",
            "SDTMIG Version",
            "Rule Version",
            "Class",
            "Domain",
            "Variable",
            "Condition",
            "Rule",
            "Document",
            "Section",
            "Item",
            "Cited Guidance",
        ]
    )
    for version, domain, identifier in (
        ("3.3", "TS", "OLD"),
        (3.4, "TS", "SYN1"),
        (3.4, "TA", "OTHER"),
    ):
        sheet.append(
            [
                identifier,
                version,
                1,
                "TDM",
                domain,
                "SYNVAR",
                None,
                "Synthetic rule",
                "Synthetic IG",
                "fictional",
                None,
                "Synthetic guidance",
            ]
        )
    path = tmp_path / "rules.xlsx"
    book.save(path)
    book.close()
    rules = read_ts_conformance(path)
    assert [r.rule_id for r in rules] == ["SYN1"]
    assert rules[0].row == 3


@pytest.fixture
def assembled():
    spec = ClinicalBuildSpec(
        schema_version="1",
        profile_id="fictional-review",
        profile_version="1",
        created_at="2026-01-01T00:00:00Z",
        ct_release="fictional",
        inputs={
            role: dict(
                filename=f"{role}.txt", sha256="0" * 64, version="fictional", publication_date=None
            )
            for role in ("ct", "sdtm", "sdtmig", "ct_relationships", "conformance")
        },
    )
    sources = [
        dict(
            source_id=role,
            title="Fictional source",
            publisher="Tests",
            version="fictional",
            url=None,
            publication_date=None,
            retrieval_date=None,
            local_filename=f"sources/{role}.txt",
            sha256="0" * 64,
            license_note="Synthetic tests only",
            normative_level=5,
            provenance="synthetic",
        )
        for role in (*spec.inputs, "project-policy")
    ]
    terms, parameters = [], []
    for index, code in enumerate((*PRIORITY, "X_EXTRA"), 100):
        concept = f"C{index}"
        terms.extend((term("C66738", concept, code), term("C67152", concept, f"Fictional {code}")))
        links = ()
        if code in {"RANDOM", "TBLIND", "TPHASE"}:
            links = (
                ResponseLink(
                    codelist="C900",
                    codelist_name="Fictional response",
                    term_code="C901",
                    value="SYNTHETIC",
                    locator="E2:F2",
                ),
            )
        parameters.append(
            CodetableParameter(
                concept_code=concept,
                tsparmcd=code,
                tsparm=f"Fictional {code}",
                locators=("A2:C2",),
                responses=links,
            )
        )
    terms.append(term("C900", "C901", "SYNTHETIC"))
    snapshot = CodetableSnapshot(release="fictional", parameters=tuple(parameters))
    return spec, *assemble_profile(spec, sources, snapshot, tuple(terms), ())


def test_first_eight_rules_separate_applicability_and_value_availability(assembled):
    _, profile, content = assembled
    rules = {r.rule_id: r for r in profile.applicability_rules}
    for code in PRIORITY:
        rule = rules[f"{code}-app-v1"]
        assert rule.on_unknown == "manual_assessment"
        if code in {"TRT", "CURTRT"}:
            assert rule.predicate.fact_key == f"reviewed_{code.lower()}_applicability"
            assert rule.predicate.value == "present"
            assert (rule.on_true, rule.on_false) == ("include", "exclude")
        else:
            # No fact-present condition: an absent value must not remove an applicable row.
            assert rule.predicate is None
            assert (rule.on_true, rule.on_false) == ("include", "include")
        row = next(p for p in content.parameters if p.tsparmcd == code)
        assert row.inclusion.basis == "project_policy"
        assert row.inclusion.status == "source_backed"  # not human approval
    derived = {d.derivation_id: d for d in profile.derivations}
    assert derived["ACTSUB-derive-v1"].source_requirement == "study_data"
    assert derived["PLANSUB-derive-v1"].source_requirement == "protocol"
    assert all(not v.allow_tsvalnf for v in profile.value_profiles)
    assert profile.manifest.signoff is None
    assert profile.manifest.status == "draft"
    assert profile.manifest.standards["regulator_guide"].status == "not_applicable"
    assert not validate_content(profile, content).valid


def test_no_codelist_is_not_inferred_from_blank_codetable(assembled):
    _, profile, content = assembled
    values = {p.tsparmcd: p for p in content.parameters}
    for code in ("TITLE", "ACTSUB", "PLANSUB"):
        assert values[code].codelist_status == "not_applicable"
        assert values[code].response.source_refs
    assert values["X_EXTRA"].codelist_status == "unresolved"
    assert values["X_EXTRA"].value_source.status == "missing"
    assert values["CURTRT"].codelist_status == "external"
    assert "not inferred solely from ADDON" in values["CURTRT"].value_source.text
    assert "not restricted to drug studies" in values["TRT"].value_source.text


def test_variable_metadata_matches_selected_guide_structure():
    variables = variable_metadata()
    assert len(variables) == 11
    assert {v["name"] for v in variables if v["core"] == "Req"} == {
        "STUDYID",
        "DOMAIN",
        "TSSEQ",
        "TSPARMCD",
        "TSPARM",
    }
    assert (
        "within a parameter"
        in next(v for v in variables if v["name"] == "TSSEQ")["implementation_notes"]
    )
    assert all("7.4.2" in v["source_refs"][0]["locator"] for v in variables)


def test_builder_refuses_changed_sources_before_writing(assembled, tmp_path):
    spec, _, _ = assembled
    for source in spec.inputs.values():
        (tmp_path / source.filename).write_text("synthetic changed bytes")
    with pytest.raises(ValueError, match="Source hash mismatch"):
        build_clinical_review(spec, tmp_path, tmp_path / "out")
    assert not (tmp_path / "out").exists()
