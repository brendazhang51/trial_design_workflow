"""Step 3 exact coding, source precision, grouping, nulls and rejection boundaries."""

import pytest
from pipeline_fixtures import REVIEW, make_inputs, make_profile
from pydantic import ValidationError

from trial_design_workflow.generation import BASE_COLUMNS, TSGeneration, TSRecord, generate_ts
from trial_design_workflow.normalization import (
    MappingException,
    decimal,
    integer,
    iso_date,
    iso_duration,
    ratio,
    split_tsval,
)
from trial_design_workflow.selection import (
    ParameterSelection,
    RuntimeProfile,
    load_runtime,
    select_parameters,
)
from trial_design_workflow.serialization import sha256
from trial_design_workflow.standards.validation import content_digest
from trial_design_workflow.study_context import StudyContext, digest


@pytest.fixture
def setup(tmp_path):
    runtime = load_runtime(make_profile(tmp_path), allow_draft=True)
    _, context = make_inputs(tmp_path / "inputs")
    return context, runtime


def generate(context, runtime):
    selection = select_parameters(context, runtime, allow_draft=True)
    return generate_ts(context, selection, runtime, allow_draft=True)


def corrected(context, key, value):
    payload = context.model_dump(mode="json")
    for fact in payload["facts"]:
        if fact["fact_key"] == key:
            fact.update(reviewed_value=value, review={**REVIEW, "action": "correct"})
    return StudyContext.model_validate(payload)


def changed_runtime(runtime, change):
    payload = runtime.model_dump(mode="json")
    change(payload["profile"])
    from trial_design_workflow.standards.models import StandardsProfile

    payload["content"]["profile_content_sha256"] = content_digest(
        StandardsProfile.model_validate(payload["profile"])
    )
    return RuntimeProfile.model_validate(payload)


def codes(result):
    return {f.code for f in result.findings}


def test_complete_ts_structure_exact_maps_external_sources_and_trace(setup):
    context, runtime = setup
    result = generate(context, runtime)
    records = {r.TSPARMCD: r for r in result.records}
    assert set(BASE_COLUMNS) == set(result.columns)
    assert records["PLANSUB"].TSVAL == "1200"
    assert records["RANDOM"].TSVAL == "YES" and records["RANDOM"].TSVALCD == "SYN-Y"
    assert records["RANDOM"].TSVCDVER == "3.4"
    assert (
        records["EXT"].TSVALCD == "SYN-ALPHA" and records["EXT"].TSVCDREF == "Fictional Dictionary"
    )
    assert records["DATE"].TSVAL == "2026-02" and records["DUR"].TSVAL == "P12W"
    assert records["DEC"].TSVAL == "1.250" and records["RATIO"].TSVAL == "0.5"
    assert "EXCL" not in records
    repeated = [r for r in result.records if r.TSPARMCD == "REPEAT"]
    assert len(repeated) == 2 and len({r.TSGRPID for r in repeated}) == 2
    assert all(
        t.evidence and t.identity_evidence and t.input_fact_hashes and t.authority_refs
        for t in result.trace
    )
    assert next(t for t in result.trace if t.tsparmcd == "EXT").external_coding
    assert all(set(r.model_dump()) <= set(result.columns) for r in result.records)
    TSGeneration.model_validate_json(result.model_dump_json())


@pytest.mark.parametrize(
    "key,value,expected",
    [
        ("randomization", "maybe", "CONTROLLED_TERM_UNMAPPED"),
        ("planned_enrollment", "approximately 10", "INVALID_INTEGER"),
        ("date", "2026-02-30", "INVALID_ISO8601_DATE"),
        ("date", "2026-02-01", "DATE_SOURCE_PRECISION_REQUIRES_REVIEW"),
        ("duration", "P3M", "DURATION_SOURCE_PRECISION_REQUIRES_REVIEW"),
        ("decimal", "NaN", "INVALID_DECIMAL"),
        ("denominator", "0", "RATIO_DENOMINATOR_NOT_POSITIVE"),
        ("denominator", "241", "RATIO_ROUNDING_POLICY_REQUIRED"),
    ],
)
def test_invalid_unmapped_or_increased_precision_never_becomes_a_normal_value(
    setup, key, value, expected
):
    context, runtime = setup
    result = generate(corrected(context, key, value), runtime)
    assert expected in codes(result)
    assert all(r.TSVAL != value for r in result.records)


def test_unreviewed_values_do_not_generate_and_no_null_is_invented(setup):
    context, runtime = setup
    payload = context.model_dump(mode="json")
    for fact in payload["facts"]:
        fact.update(status="needs_review", reviewed_value=None, review=None, coding=None)
    result = generate(StudyContext.model_validate(payload), runtime)
    assert result.records == ()
    assert not any(r.TSVALNF for r in result.records)


def test_no_identity_review_means_no_ts_records(setup):
    context, runtime = setup
    payload = context.model_dump(mode="json")
    payload["identity_review"] = None
    result = generate(StudyContext.model_validate(payload), runtime)
    assert result.records == () and "STUDY_ID_REVIEW_REQUIRED" in codes(result)


def test_external_dictionary_must_be_explicit_and_match_code_label_version(setup):
    context, runtime = setup
    payload = context.model_dump(mode="json")
    for fact in payload["facts"]:
        if fact["fact_key"] == "intervention":
            fact["coding"] = None
    result = generate(StudyContext.model_validate(payload), runtime)
    assert "EXTERNAL_DICTIONARY_REQUIRED" in codes(result)
    assert not any(r.TSPARMCD == "EXT" for r in result.records)
    changed = corrected(context, "intervention", "Different reviewed term")
    assert "EXTERNAL_CODE_VALUE_MISMATCH" in codes(generate(changed, runtime))


def test_forged_selection_or_changed_profile_is_rejected(setup):
    context, runtime = setup
    selection = select_parameters(context, runtime, allow_draft=True)
    payload = selection.model_dump(mode="json")
    for decision in payload["decisions"]:
        if decision["tsparmcd"] == "EXCL":
            decision["decision"] = "include"
    with pytest.raises(ValueError, match="replay"):
        generate_ts(context, ParameterSelection.model_validate(payload), runtime, allow_draft=True)
    other = changed_runtime(runtime, lambda p: p["manifest"].update(profile_version="new"))
    with pytest.raises(ValueError, match="replay"):
        generate_ts(context, selection, other, allow_draft=True)


def test_stable_sequence_grouping_and_record_hashes_under_input_reordering(setup):
    context, runtime = setup
    original = generate(context, runtime)
    payload = context.model_dump(mode="json")
    payload["facts"].reverse()
    payload["sources"].reverse()
    result = generate(StudyContext.model_validate(payload), runtime)
    assert result.records == original.records and result.trace == original.trace
    assert digest(result) == digest(original)


def replace_title_source(context, text):
    payload = context.model_dump(mode="json")
    source = next(s for s in payload["sources"] if s["source_id"] == "protocol")
    old = source["pages"][0]["text"]
    source["pages"][0]["text"] = old + "\n" + text
    source["sha256"] = sha256(source["pages"][0]["text"].encode())
    for fact in payload["facts"]:
        for e in fact["evidence"]:
            if e["source_id"] == "protocol":
                e["source_sha256"] = source["sha256"]
        if fact["fact_key"] == "study_title":
            start = len(old) + 1
            fact.update(raw_value=text, proposed_value=text, reviewed_value=text, review=REVIEW)
            fact["evidence"] = [
                dict(
                    source_id="protocol",
                    source_sha256=source["sha256"],
                    pdf_page_index=0,
                    printed_page=None,
                    start=start,
                    end=start + len(text),
                    quote=text,
                    locator="Synthetic extra line",
                )
            ]
    for e in payload["identity_review"]["evidence"]:
        e["source_sha256"] = source["sha256"]
    return StudyContext.model_validate(payload)


def test_long_text_respects_profile_and_opt_in_continuation_preserves_words(setup):
    context, runtime = setup
    text = "word " * 100 + "end"
    context = replace_title_source(context, text)
    assert "LONG_TEXT_BLOCKED_BY_PROFILE" in codes(generate(context, runtime))

    def enable(p):
        next(v for v in p["value_profiles"] if v["value_profile_id"] == "TITLE-value")[
            "long_text_policy"
        ] = "sdtmig34_tsval_continuation"

    permitted = changed_runtime(runtime, enable)
    result = generate(context, permitted)
    record = next(r for r in result.records if r.TSPARMCD == "TITLE")
    values = [record.TSVAL] + [
        record.model_dump()[k] for k in result.columns if k.startswith("TSVAL") and k[5:].isdigit()
    ]
    assert "".join(values) == text and all(len(v) <= 200 for v in values)
    assert result.continuation_policy_refs
    blocked = replace_title_source(context, "x" * 201)
    assert "LONG_TEXT_TOKEN_REQUIRES_REVIEW" in codes(generate(blocked, permitted))


def test_null_flavor_only_from_reviewed_value_and_explicit_profile_rule(setup):
    context, runtime = setup
    payload = context.model_dump(mode="json")
    fact = next(f for f in payload["facts"] if f["fact_key"] == "date")
    fact.update(reviewed_value=None, null_flavor="SYN-UNK", review={**REVIEW, "action": "correct"})
    context = StudyContext.model_validate(payload)
    assert "NULL_FLAVOR_FORBIDDEN" in codes(generate(context, runtime))

    def permit(p):
        v = next(v for v in p["value_profiles"] if v["value_profile_id"] == "DATE-value")
        v.update(
            allow_tsvalnf=True, allowed_null_flavors=["SYN-UNK"], target_fields=["TSVAL", "TSVALNF"]
        )
        p["terminology"].append(
            dict(
                release="3.4",
                codelist="NULLFLAVOR",
                code="SYN-NULL",
                value="SYN-UNK",
                status="active",
                source_id="synthetic",
            )
        )

    result = generate(context, changed_runtime(runtime, permit))
    record = next(r for r in result.records if r.TSPARMCD == "DATE")
    assert record.TSVAL is None and record.TSVALNF == "SYN-UNK"


def test_formula_text_is_literal_data_and_illegal_characters_are_blocked(setup):
    context, runtime = setup
    value = '=HYPERLINK("example")'
    result = generate(replace_title_source(context, value), runtime)
    assert next(r for r in result.records if r.TSPARMCD == "TITLE").TSVAL == value
    assert next(t for t in result.trace if t.tsparmcd == "TITLE").requires_literal_excel
    assert "EXCEL_LITERAL_REQUIRED" in codes(result)
    assert "ILLEGAL_CHARACTER" in codes(
        generate(replace_title_source(context, "bad\x00value"), runtime)
    )


@pytest.mark.parametrize(
    "mutation",
    [
        {"TSVALNF": "UNKNOWN"},
        {"TSVALCD": "CODE"},
        {"TSVCDREF": "REFERENCE"},
        {"APPROVED": True},
        {"TSVAL2": "gap"},
        {"TSSEQ": True},
    ],
)
def test_ts_schema_rejects_inconsistent_codes_unapproved_columns_and_sequences(mutation):
    record = dict(STUDYID="SYN", TSPARMCD="TITLE", TSPARM="Fictional title", TSSEQ=1, TSVAL="Title")
    record.update(mutation)
    with pytest.raises(ValidationError):
        TSRecord.model_validate(record)


@pytest.mark.parametrize(
    "fn,value,expected",
    [
        (integer, "1,200", "1200"),
        (decimal, "001.2300", "1.2300"),
        (iso_date, "2026", "2026"),
        (iso_date, "2024-02-29T12:30:10Z", "2024-02-29T12:30:10Z"),
        (iso_duration, "P1Y2M", "P1Y2M"),
        (iso_duration, "PT1.5H", "PT1.5H"),
    ],
)
def test_named_normalizers_preserve_precision(fn, value, expected):
    assert fn(value) == expected


@pytest.mark.parametrize(
    "fn,value",
    [
        (integer, "-1"),
        (integer, "1,00"),
        (decimal, "1e3"),
        (iso_date, "2025-02-29"),
        (iso_date, "2026-13"),
        (iso_date, "2026-01T12"),
        (iso_duration, "12 weeks"),
        (iso_duration, "P1W2D"),
        (iso_duration, "P1.5Y2M"),
        (iso_duration, "PT"),
    ],
)
def test_unsupported_numeric_date_and_duration_forms_are_exceptions(fn, value):
    with pytest.raises(MappingException):
        fn(value)


def test_ratio_does_not_guess_rounding_and_continuation_reconstructs_source():
    assert ratio("1", "8") == "0.125"
    with pytest.raises(MappingException, match="ROUNDING"):
        ratio("1", "3")
    with pytest.raises(MappingException, match="EXCEEDS"):
        ratio("3", "2")
    text = "A long sentence. " * 60
    assert "".join(split_tsval(text)) == text


def test_continuation_variable_names_stay_within_project_eight_character_policy():
    values = {"TSVAL" + str(i): "part" for i in range(1, 1001)}
    with pytest.raises(ValidationError, match="standard TSVAL"):
        TSRecord(
            STUDYID="SYN",
            TSSEQ=1,
            TSPARMCD="TITLE",
            TSPARM="Fictional title",
            TSVAL="first part",
            **values,
        )
