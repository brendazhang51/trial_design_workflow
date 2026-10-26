"""Offline Step 0 contracts, adversarial assets, migration and reproducibility."""

import json
from pathlib import Path

import pytest
from pydantic import ValidationError

from trial_design_workflow.serialization import sha256
from trial_design_workflow.standards.cli import main
from trial_design_workflow.standards.legacy import build_legacy_profile, legacy_seed
from trial_design_workflow.standards.models import Predicate, StandardsProfile
from trial_design_workflow.standards.profile import (
    ProfileError,
    build_profile,
    inspect_profile,
    load_profile,
    read_profile,
    safe_path,
    semantic_diff,
)
from trial_design_workflow.standards.validation import content_digest, validate_profile
from trial_design_workflow.ts_cli import main as ts_main

FIXTURE = Path(__file__).parent / "fixtures/standards/minimal-profile"
ASSETS = Path(__file__).parents[1] / "src/trial_design_workflow/assets"


@pytest.fixture
def profile():
    return StandardsProfile.model_validate_json((FIXTURE / "profile.json").read_bytes())


def changed(profile, mutate):
    payload = profile.model_dump(mode="json")
    mutate(payload)
    return StandardsProfile.model_validate(payload)


def codes(report):
    return {f.code for f in report.findings}


def test_draft_opt_in_and_synthetic_boundary(profile, tmp_path):
    assert not validate_profile(profile).valid
    report = validate_profile(profile, allow_draft=True)
    assert report.valid
    assert codes(report) == {"DRAFT_PROFILE", "NON_CLINICAL_PROFILE"}
    assert all(f.blocking for f in report.findings)
    build_profile(profile, FIXTURE, tmp_path / "profile")
    with pytest.raises(ProfileError):
        load_profile(tmp_path / "profile")
    loaded = load_profile(tmp_path / "profile", allow_draft=True)
    assert {p.tsparmcd: p for p in loaded.parameters} == {p.tsparmcd: p for p in profile.parameters}


def test_reproducible_build_and_roundtrip(profile, tmp_path):
    first, second = tmp_path / "first", tmp_path / "second"
    build_profile(profile, FIXTURE, first)

    def reverse(payload):
        for key in ("parameters", "terminology", "applicability_rules", "derivations"):
            payload[key].reverse()

    reordered = changed(profile, reverse)
    build_profile(reordered, FIXTURE, second)
    files = {p.relative_to(first): p.read_bytes() for p in first.rglob("*") if p.is_file()}
    assert files == {
        p.relative_to(second): p.read_bytes() for p in second.rglob("*") if p.is_file()
    }
    # A loaded package can itself be used as staging to rebuild exactly.
    third = tmp_path / "third"
    build_profile(read_profile(first), first, third)
    assert files == {p.relative_to(third): p.read_bytes() for p in third.rglob("*") if p.is_file()}
    assert content_digest(profile) == content_digest(reordered)
    assert semantic_diff(profile, reordered)["changes"] == []


@pytest.mark.parametrize(
    "mutation, expected",
    [
        (lambda p: p["parameters"].append(p["parameters"][0]), "DUPLICATE_IDENTIFIER"),
        (lambda p: p["terminology"].append(p["terminology"][0]), "DUPLICATE_IDENTIFIER"),
        (lambda p: p["parameters"].pop(), "PARAMETER_COVERAGE"),
        (lambda p: p["parameters"][0].update(tsparm="Wrong name"), "PARAMETER_IDENTITY"),
        (lambda p: p["parameters"][0].update(ct_release="wrong"), "CT_RELEASE_MISMATCH"),
        (lambda p: p["parameters"][0].update(fact_key="unknown"), "UNKNOWN_FACT_KEY"),
        (lambda p: p["parameters"][0].update(value_profile_id="unknown"), "UNKNOWN_REFERENCE"),
        (lambda p: p["parameters"][0].update(derivation_id="unknown"), "UNKNOWN_REFERENCE"),
        (lambda p: p["parameters"][0].update(tsgrpid_rule_id="unknown"), "UNKNOWN_REFERENCE"),
        (lambda p: p["parameters"][0].update(value_map_id="unknown"), "UNKNOWN_REFERENCE"),
        (lambda p: p["value_profiles"][0].update(response_codelist="unknown"), "UNKNOWN_CODELIST"),
        (
            lambda p: p["applicability_rules"][0]["authority_refs"][0].update(source_id="unknown"),
            "UNKNOWN_SOURCE",
        ),
        (
            lambda p: p["manifest"]["standards"]["ct"].update(version="wrong"),
            "SOURCE_VERSION_MISMATCH",
        ),
        (
            lambda p: p["applicability_rules"][0].update(
                predicate={"op": "rule_ref", "rule_id": "unknown"}
            ),
            "UNKNOWN_RULE",
        ),
        (
            lambda p: p["applicability_rules"][0].update(
                predicate={"op": "rule_ref", "rule_id": "title-present-v1"}
            ),
            "RULE_CYCLE",
        ),
    ],
)
def test_cross_asset_validation(profile, mutation, expected, tmp_path):
    invalid = changed(profile, mutation)
    assert expected in codes(validate_profile(invalid, allow_draft=True))
    with pytest.raises(ProfileError):
        build_profile(invalid, FIXTURE, tmp_path / "invalid")
    assert not (tmp_path / "invalid").exists()


def test_indirect_rule_cycle(profile):
    def cycle(p):
        p["applicability_rules"][0]["predicate"] = {"op": "rule_ref", "rule_id": "manual-v1"}
        p["applicability_rules"][1]["predicate"] = {"op": "rule_ref", "rule_id": "title-present-v1"}

    assert "RULE_CYCLE" in codes(validate_profile(changed(profile, cycle), allow_draft=True))


@pytest.mark.parametrize(
    "mutation",
    [
        lambda p: p["manifest"].pop("standards"),
        lambda p: p["manifest"]["standards"].pop("ct"),
        lambda p: p["manifest"].update(created_at="2026-01-01T00:00:00"),
        lambda p: p["manifest"].update(status="approved_for_mvp"),
        lambda p: p["parameters"][0].update(authority_refs=[]),
        lambda p: p["parameters"][0].update(max_records=0),
        lambda p: p["sources"][0].update(sha256="wrong"),
        lambda p: p["value_profiles"][0].update(allow_tsvalnf=True),
        lambda p: p["manifest"]["standards"]["sdtmig"].update(
            status="not_applicable", source_id=None
        ),
        lambda p: p.update(unexpected="rejected"),
    ],
)
def test_malformed_contracts_rejected(profile, mutation):
    with pytest.raises(ValidationError):
        changed(profile, mutation)


@pytest.mark.parametrize(
    "payload",
    [
        {"op": "all", "children": []},
        {"op": "not", "children": []},
        {"op": "fact_present", "fact_key": "title", "value": "unused"},
        {"op": "fact_count", "fact_key": "title", "value": "1"},
        {"op": "fact_count", "fact_key": "title", "value": -1},
        {"op": "fact_in", "fact_key": "title", "values": []},
        {"op": "eval", "value": "arbitrary code"},
        {"op": "rule_ref", "rule_id": "test", "fact_key": "unused"},
    ],
)
def test_rule_language_rejects_ambiguous_or_executable_predicates(payload):
    with pytest.raises(ValidationError):
        Predicate.model_validate(payload)


def test_deprecated_parameter_never_included(profile):
    def retire(p):
        p["parameters"][0]["parameter_status"] = "deprecated"
        for term in p["terminology"]:
            if term["code"] == "SYN1":
                term["status"] = "deprecated"

    retired = changed(profile, retire)
    assert "INACTIVE_PARAMETER_INCLUDED" in codes(validate_profile(retired, allow_draft=True))
    safe = changed(retired, lambda p: p["parameters"][0].update(applicability_rule_id="manual-v1"))
    assert validate_profile(safe, allow_draft=True).valid


def test_mapping_must_match_active_exact_code_and_release(profile):
    def mapping(p):
        p["value_maps"] = [
            {
                "value_map_id": "alias",
                "input_value": "alias",
                "codelist": "C66738",
                "term_code": "SYN1",
                "submission_value": "WRONG",
                "release": "synthetic-v1",
                "authority_refs": [{"source_id": "synthetic", "locator": "test alias"}],
            }
        ]

    assert "INVALID_VALUE_MAPPING" in codes(
        validate_profile(changed(profile, mapping), allow_draft=True)
    )


def test_signoff_digest_changes_with_rules_and_evidence(profile):
    digest = content_digest(profile)

    def sign(p):
        p["manifest"]["signoff"] = {
            "reviewer_id": "SIMULATED_TEST_ONLY",
            "reviewed_at": "2026-01-01T00:00:00Z",
            "rationale": "Test digest binding only",
            "content_sha256": digest,
        }

    signed = changed(profile, sign)
    assert validate_profile(signed, allow_draft=True).valid
    revised = changed(signed, lambda p: p["applicability_rules"][0].update(explanation="Changed"))
    assert "STALE_PROFILE_SIGNOFF" in codes(validate_profile(revised, allow_draft=True))


def test_clinical_profile_rejects_historical_rules(profile):
    clinical = changed(profile, lambda p: p["manifest"].update(scope="clinical"))
    assert {"NON_NORMATIVE_RULE", "NON_NORMATIVE_STANDARD"} <= codes(
        validate_profile(clinical, allow_draft=True)
    )


@pytest.mark.parametrize("attack", ["../outside", "/tmp/outside", "sources/../../outside"])
def test_profile_path_traversal_rejected(tmp_path, attack):
    with pytest.raises(ValueError):
        safe_path(tmp_path, attack)


def test_source_symlink_escape_rejected(tmp_path):
    root = tmp_path / "root"
    root.mkdir()
    (root / "escape").symlink_to(tmp_path)
    with pytest.raises(ValueError):
        safe_path(root, "escape/outside")


def test_packaged_integrity_and_no_overwrite(profile, tmp_path):
    destination = build_profile(profile, FIXTURE, tmp_path / "profile")
    with pytest.raises(FileExistsError):
        build_profile(profile, FIXTURE, destination)
    (destination / "master_lookup.csv").write_text("tampered")
    report = inspect_profile(destination, allow_draft=True)
    assert codes(report) == {"PROFILE_INTEGRITY_ERROR"}


def test_staging_hash_mismatch_fails_before_output(profile, tmp_path):
    invalid = changed(profile, lambda p: p["sources"][0].update(sha256="0" * 64))
    with pytest.raises(ValueError, match="hash mismatch"):
        build_profile(invalid, FIXTURE, tmp_path / "profile")
    assert not (tmp_path / "profile").exists()


def test_semantic_diff_covers_rules_labels_terminology_and_sources(profile):
    def revise(p):
        p["parameters"][0]["tsparm"] = "Changed title"
        p["applicability_rules"][0]["explanation"] = "Changed rule"
        p["value_profiles"][0]["response_terminology"] = "Changed terminology"
        p["sources"][0]["version"] = "Changed version"

    diff = semantic_diff(profile, changed(profile, revise))
    assert {c["table"] for c in diff["changes"]} == {
        "parameters",
        "applicability_rules",
        "value_profiles",
        "sources",
    }


def test_legacy_migration_keeps_129_identities_and_immutable_assets(tmp_path):
    before = {
        name: sha256((ASSETS / name).read_bytes())
        for name in (
            "ts-parameters-v1.csv",
            "ct-2025-03-28.csv",
            "protocol-facts-v1.json",
            "sources.json",
        )
    }
    destination = build_legacy_profile(ASSETS, tmp_path / "stage", tmp_path / "profile")
    migrated = load_profile(destination, allow_draft=True)
    assert len(migrated.parameters) == 129
    assert {p.base_disposition for p in migrated.parameters} == {"manual_assessment"}
    assert {p.automation_level for p in migrated.parameters} == {"manual"}
    assert all(p.fact_key is None and p.value_map_id is None for p in migrated.parameters)
    assert "STANDARDS_INPUT_MISSING" in codes(validate_profile(migrated, allow_draft=True))
    for name, digest in before.items():
        assert sha256((ASSETS / name).read_bytes()) == digest
        assert (destination / "sources" / name).read_bytes() == (ASSETS / name).read_bytes()
    assert content_digest(legacy_seed(ASSETS)[0]) == content_digest(migrated)


def test_cli_validation_build_diff_and_legacy_dispatch(profile, tmp_path, capsys, monkeypatch):
    destination = tmp_path / "profile"
    assert (
        main(["build", "--spec", str(FIXTURE / "profile.json"), "--output", str(destination)]) == 0
    )
    assert main(["validate", "--profile", str(destination)]) == 1
    assert main(["validate", "--profile", str(destination), "--allow-draft-standards"]) == 0
    capsys.readouterr()
    assert (
        main(
            [
                "diff",
                "--before",
                str(destination),
                "--after",
                str(destination),
                "--allow-draft-standards",
            ]
        )
        == 0
    )
    assert json.loads(capsys.readouterr().out)["changes"] == []
    monkeypatch.setattr(
        "sys.argv",
        [
            "trial-ts",
            "standards",
            "validate",
            "--profile",
            str(destination),
            "--allow-draft-standards",
        ],
    )
    assert ts_main() == 0


def test_cli_errors_do_not_echo_source_values(tmp_path, capsys):
    invalid = tmp_path / "invalid.json"
    invalid.write_text('{"confidential": "SECRET_SENTINEL"}')
    assert main(["build", "--spec", str(invalid), "--output", str(tmp_path / "new")]) == 2
    assert "SECRET_SENTINEL" not in capsys.readouterr().err


def test_exported_schema_matches_models():
    schema_path = Path(__file__).parents[1] / "schemas/master-lookup-v2.schema.json"
    assert json.loads(schema_path.read_bytes()) == StandardsProfile.model_json_schema()


def test_checked_in_legacy_profile_matches_rebuild(tmp_path):
    bundled = ASSETS / "standards/legacy-candidates-2025-03-28"
    assert inspect_profile(bundled, allow_draft=True).valid
    rebuilt = build_legacy_profile(ASSETS, tmp_path / "staging", tmp_path / "rebuilt")
    assert {p.relative_to(bundled): p.read_bytes() for p in bundled.rglob("*") if p.is_file()} == {
        p.relative_to(rebuilt): p.read_bytes() for p in rebuilt.rglob("*") if p.is_file()
    }


def test_uninventoried_artifact_rejected(profile, tmp_path):
    destination = build_profile(profile, FIXTURE, tmp_path / "profile")
    (destination / "untracked.txt").write_text("not in the manifest")
    assert "PROFILE_INTEGRITY_ERROR" in codes(inspect_profile(destination, allow_draft=True))


def test_missing_source_cannot_be_approved(profile):
    def missing(p):
        p["manifest"].update(
            scope="clinical",
            status="approved_for_mvp",
            signoff={
                "reviewer_id": "SIMULATED_TEST_ONLY",
                "reviewed_at": "2026-01-01T00:00:00Z",
                "rationale": "Synthetic fixture",
                "content_sha256": "0" * 64,
            },
        )
        p["manifest"]["standards"]["sdtmig"].update(
            status="missing",
            source_id=None,
            reason="No source supplied",
        )

    with pytest.raises(ValidationError, match="missing standards"):
        changed(profile, missing)


def test_signoff_promotion_and_source_change_invalidation(profile):
    # Entirely fictional authority/reviewer: exercises the gate, not a real approval.
    def clinical(p):
        p["manifest"]["scope"] = "clinical"
        p["sources"][0].update(provenance="cdisc", normative_level=2)
        for parameter in p["parameters"]:
            parameter["authority_scope"] = "cdisc"

    draft = changed(profile, clinical)
    digest = content_digest(draft)

    def approve(p):
        p["manifest"].update(
            status="approved_for_mvp",
            signoff={
                "reviewer_id": "SIMULATED_TEST_ONLY",
                "reviewed_at": "2026-01-01T00:00:00Z",
                "rationale": "Gate behavior test only",
                "content_sha256": digest,
            },
        )

    approved = changed(draft, approve)
    assert validate_profile(approved).valid
    changed_source = changed(approved, lambda p: p["sources"][0].update(sha256="0" * 64))
    assert "STALE_PROFILE_SIGNOFF" in codes(validate_profile(changed_source))
    changes = semantic_diff(draft, approved)["changes"]
    assert {c["id"] for c in changes} == {"status", "signoff"}


def test_unknown_nested_fact_key_rejected(profile):
    def nested(p):
        p["applicability_rules"][0]["predicate"] = {
            "op": "not",
            "children": [
                {
                    "op": "all",
                    "children": [
                        {"op": "fact_present", "fact_key": "unknown"},
                    ],
                }
            ],
        }

    assert "UNKNOWN_FACT_KEY" in codes(validate_profile(changed(profile, nested), allow_draft=True))
