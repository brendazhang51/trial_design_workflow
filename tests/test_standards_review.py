"""Content review remains unresolved until evidence AND executable contracts exist."""

import csv
import io
import json
from pathlib import Path

import pytest
from pydantic import ValidationError

from trial_design_workflow.serialization import sha256
from trial_design_workflow.standards.cli import main
from trial_design_workflow.standards.models import StandardsProfile
from trial_design_workflow.standards.profile import load_profile
from trial_design_workflow.standards.review import (
    PRIORITY,
    SECTIONS,
    ContentAssertion,
    ReviewContent,
    export_review,
    initialize_content,
    inventory_sources,
    predicate_text,
    readable_csv,
    review_rows,
    validate_content,
)

ROOT = Path(__file__).parents[1]
LEGACY = ROOT / "src/trial_design_workflow/assets/standards/legacy-candidates-2025-03-28"
FIXTURE = ROOT / "tests/fixtures/standards/minimal-profile/profile.json"


@pytest.fixture
def profile():
    return StandardsProfile.model_validate_json(FIXTURE.read_bytes())


def mutate(content, change):
    payload = content.model_dump(mode="json")
    change(payload)
    return ReviewContent.model_validate(payload)


def codes(profile, content):
    return {f.code for f in validate_content(profile, content).findings}


def test_legacy_full_coverage_and_specific_priority_actions():
    profile = load_profile(LEGACY, allow_draft=True)
    content = initialize_content(profile)
    assert len(content.parameters) == 129
    rows = review_rows(profile, content)
    assert [r["TSPARMCD"] for r in rows[:8]] == list(PRIORITY)
    assert len({r["TSPARMCD"] for r in rows}) == 129
    assert all(r["Response codelist status"] == "unresolved" for r in rows)
    actual = next(p for p in content.parameters if p.tsparmcd == "ACTSUB")
    current = next(p for p in content.parameters if p.tsparmcd == "CURTRT")
    assert "do not substitute planned enrollment" in actual.value_source.action_required
    assert "missing extraction is not evidence" in current.inclusion.action_required
    assert {
        "CONTENT_SOURCE_GAP",
        "INCLUSION_NOT_IMPLEMENTED",
        "VALUE_NOT_IMPLEMENTED",
        "SOURCE_NOT_IMPLEMENTED",
        "RESPONSE_UNRESOLVED",
        "VARIABLE_METADATA_INCOMPLETE",
    } <= codes(profile, content)


def test_source_backed_claim_requires_refs_and_missing_requires_action():
    with pytest.raises(ValidationError, match="exact source references"):
        ContentAssertion(
            status="source_backed",
            text="claim",
            basis="standard",
            source_refs=(),
            action_required=None,
        )
    with pytest.raises(ValidationError, match="concrete next action"):
        ContentAssertion(
            status="missing", text="claim", basis="standard", source_refs=(), action_required=None
        )


@pytest.mark.parametrize(
    "change, code",
    [
        (lambda p: p.update(profile_content_sha256="0" * 64), "CONTENT_PROFILE_MISMATCH"),
        (lambda p: p["parameters"].pop(), "CONTENT_COVERAGE"),
        (lambda p: p["parameters"].append(p["parameters"][0]), "CONTENT_COVERAGE"),
    ],
)
def test_content_cannot_silently_drift(profile, tmp_path, change, code):
    content = mutate(initialize_content(profile), change)
    assert code in codes(profile, content)
    with pytest.raises(ValueError, match="exact profile"):
        export_review(profile, content, tmp_path / "out")
    assert not (tmp_path / "out").exists()


def test_readable_join_exposes_engine_not_just_notes(profile):
    content = initialize_content(profile)
    rows = review_rows(profile, content)
    title = next(r for r in rows if r["TSPARMCD"] == "X_TITLE")
    assert title["If true"] == "include"
    assert "title" in title["Inclusion predicate"]
    assert title["Fact inputs"] == "study_title"
    assert title["Transform"] == "copy_text"
    assert title["Response type"] == "text"
    assert title["Content state"] == "unresolved"


def test_prose_cannot_replace_runtime_value_contract_or_standard_sources(profile):
    payload = initialize_content(profile).model_dump(mode="json")
    for parameter in payload["parameters"]:
        for section in SECTIONS:
            parameter[section].update(
                status="source_backed",
                source_refs=[
                    {
                        "source_id": profile.sources[0].source_id,
                        "locator": "fictional section 1",
                    }
                ],
                action_required=None,
            )
    content = ReviewContent.model_validate(payload)
    findings = codes(profile, content)
    assert "CONTENT_SOURCE_AUTHORITY" in findings  # synthetic is never clinical authority
    assert "SOURCE_NOT_IMPLEMENTED" in findings
    payload["parameters"][0]["definition"]["source_refs"][0]["source_id"] = "absent"
    assert "CONTENT_SOURCE_UNKNOWN" in codes(profile, ReviewContent.model_validate(payload))


def test_codelist_contract_requires_exact_metadata_and_runtime_match(profile):
    payload = initialize_content(profile).model_dump(mode="json")
    parameter = payload["parameters"][0]
    parameter.update(codelist_status="codelist")
    with pytest.raises(ValidationError, match="ID, name and release"):
        ReviewContent.model_validate(payload)
    parameter.update(codelist_id="C_FAKE", codelist_name="Fictional", terminology_release="2000")
    assert "RESPONSE_PROFILE_MISMATCH" in codes(profile, ReviewContent.model_validate(payload))
    parameter.update(
        codelist_status="not_applicable",
        codelist_id=None,
        codelist_name=None,
        terminology_release=None,
    )
    with pytest.raises(ValidationError, match="explicit reason"):
        ReviewContent.model_validate(payload)


def test_export_reproducible_no_overwrite_and_hashes(profile, tmp_path):
    content = initialize_content(profile)
    first, second = tmp_path / "first", tmp_path / "second"
    export_review(profile, content, first)
    reordered = mutate(content, lambda p: p["parameters"].reverse())
    # Content artifact preserves original author order, while the review is sorted.
    export_review(profile, reordered, second)
    assert (first / "master_lookup_review.csv").read_bytes() == (
        second / "master_lookup_review.csv"
    ).read_bytes()
    assert json.loads((first / "review_manifest.json").read_bytes())["step0_ready"] is False
    assert "order,name,label,data_type,role,core" in (first / "ts_variable_metadata.csv").read_text(
        "utf-8-sig"
    )
    for name, digest in json.loads((first / "checksums.json").read_bytes()).items():
        assert sha256((first / name).read_bytes()) == digest
    with pytest.raises(FileExistsError):
        export_review(profile, content, first)
    third = tmp_path / "third"
    export_review(profile, content, third)
    assert {p.name: p.read_bytes() for p in first.iterdir()} == {
        p.name: p.read_bytes() for p in third.iterdir()
    }


def test_csv_formula_protection_and_plain_strings():
    rows = [
        {"code": "TITLE", "text": '  =HYPERLINK("bad")'},
        {"code": "@bad", "text": 'A, quoted "title"\nsecond line'},
    ]
    output = readable_csv(rows).decode("utf-8-sig")
    parsed = list(csv.DictReader(io.StringIO(output)))
    assert parsed[0]["code"] == "TITLE"
    assert parsed[0]["text"].startswith("'  =")
    assert parsed[1]["code"] == "'@bad"
    assert parsed[1]["text"] == rows[1]["text"]


def test_nested_rule_references_are_expanded_for_review(profile):
    from trial_design_workflow.standards.models import Predicate

    rule = profile.applicability_rules[0]
    predicate = Predicate(op="not", children=(Predicate(op="rule_ref", rule_id=rule.rule_id),))
    text = predicate_text(predicate, {rule.rule_id: rule})
    assert "NOT(" in text
    assert f"unknown={rule.on_unknown}" in text
    assert f"true={rule.on_true}" in text


def test_inventory_hashes_not_authority(tmp_path):
    (tmp_path / "sdtmig-3.4").mkdir()
    (tmp_path / "sdtmig-3.4/guide.txt").write_text("fictional bytes")
    inventory = inventory_sources(tmp_path)
    assert inventory == inventory_sources(tmp_path)
    file = inventory["files"][0]
    assert file["sha256"] == sha256(b"fictional bytes")
    assert file["version"] is None
    assert file["selected_for_clinical_use"] is False
    (tmp_path / "link").symlink_to(tmp_path / "sdtmig-3.4/guide.txt")
    with pytest.raises(ValueError, match="symlinks"):
        inventory_sources(tmp_path)


def test_review_cli_and_content_gate(tmp_path, capsys):
    content = tmp_path / "content.json"
    base = ["--profile", str(LEGACY), "--allow-draft-standards"]
    assert main(["review-init", *base, "--output", str(content)]) == 0
    assert (
        main(
            [
                "review-export",
                *base,
                "--content",
                str(content),
                "--output",
                str(tmp_path / "review"),
            ]
        )
        == 0
    )
    assert main(["validate", *base, "--content", str(content)]) == 1
    assert main(["review-init", *base, "--output", str(content)]) == 2
    assert main(["content-schema"]) == 0
    capsys.readouterr()
