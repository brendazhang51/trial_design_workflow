"""Synthetic approval decisions: exact binding, real gates, immutable source packages."""

import json
from pathlib import Path

import pytest

from trial_design_workflow.serialization import sha256
from trial_design_workflow.standards.approval import (
    ActiveProfile,
    ProfileApproval,
    apply_approval,
    promote_bundle,
    resolve_active_profile,
)
from trial_design_workflow.standards.cli import main
from trial_design_workflow.standards.models import StandardsProfile
from trial_design_workflow.standards.profile import (
    ProfileError,
    build_profile,
    json_bytes,
    load_profile,
)
from trial_design_workflow.standards.review import (
    SECTIONS,
    ReviewContent,
    export_review,
    initialize_content,
    validate_content,
)
from trial_design_workflow.standards.validation import content_digest, validate_profile

FIXTURE = Path(__file__).parent / "fixtures/standards/minimal-profile"


@pytest.fixture
def prepared(tmp_path):
    # Deliberately simulated authority/reviewer; no real CDISC claims or licensed bytes.
    payload = json.loads((FIXTURE / "profile.json").read_bytes())
    payload["manifest"]["scope"] = "clinical"
    payload["sources"][0].update(provenance="cdisc", normative_level=2)
    payload["parameters"] = payload["parameters"][:1]
    payload["parameters"][0]["authority_scope"] = "cdisc"
    payload["terminology"] = payload["terminology"][:2]
    payload["applicability_rules"] = payload["applicability_rules"][:1]
    payload["derivations"] = payload["derivations"][:1]
    profile = StandardsProfile.model_validate(payload)
    content = initialize_content(profile).model_dump(mode="json")
    refs = [{"source_id": "synthetic", "locator": "Fictional test section"}]
    assertion = dict(
        status="source_backed",
        text="Synthetic test contract",
        basis="standard",
        source_refs=refs,
        action_required=None,
    )
    for parameter in content["parameters"]:
        for section in SECTIONS:
            parameter[section] = assertion
        parameter.update(
            codelist_status="not_applicable", no_codelist_reason="Fictional text field"
        )
    content["variable_inventory"] = assertion
    content["variables"] = [
        {
            "name": "STUDYID",
            "label": "Study Identifier",
            "data_type": "Char",
            "order": 1,
            "role": "Identifier",
            "core": "Req",
            "codelist_or_format": None,
            "implementation_notes": "Synthetic fixture",
            "source_refs": refs,
        }
    ]
    content = ReviewContent.model_validate(content)
    assert {f.code for f in validate_content(profile, content).findings} == {"DRAFT_PROFILE"}
    bundle = tmp_path / "draft"
    build_profile(profile, FIXTURE, bundle / "profile")
    export_review(profile, content, bundle / "review")
    (bundle / "content.json").write_bytes(json_bytes(content.model_dump(mode="json")))
    hashes = {
        p.relative_to(bundle).as_posix(): sha256(p.read_bytes())
        for p in bundle.rglob("*")
        if p.is_file()
    }
    (bundle / "bundle_checksums.json").write_bytes(json_bytes(hashes))
    approval = ProfileApproval(
        schema_version="1",
        decision="approved_for_mvp",
        profile_id=profile.manifest.profile_id,
        profile_version=profile.manifest.profile_version,
        profile_content_sha256=content_digest(profile),
        review_content_sha256=sha256(json_bytes(content.model_dump(mode="json"))),
        reviewer_id="SIMULATED_TEST_ONLY",
        recorded_at="2026-01-01T00:00:00Z",
        authorization="Synthetic decision fixture only",
        scope="Fictional engineering test",
    )
    return bundle, profile, content, approval


def test_approved_package_works_without_draft_opt_in_and_preserves_input(prepared, tmp_path):
    bundle, profile, content, approval = prepared
    original = {
        p.relative_to(bundle).as_posix(): p.read_bytes() for p in bundle.rglob("*") if p.is_file()
    }
    record = tmp_path / "approval.json"
    record.write_bytes(json_bytes(approval.model_dump(mode="json")))
    output = promote_bundle(bundle, record, tmp_path / "approved")
    approved = load_profile(output / "profile")
    assert approved.manifest.status == "approved_for_mvp"
    assert content_digest(approved) == content_digest(profile)
    assert validate_content(approved, content).findings == ()
    summary = json.loads((output / "review/review_manifest.json").read_bytes())
    assert summary["step0_ready"] and summary["content_checks_passed"]
    assert summary["blocking_findings"] == 0
    assert "approved MVP baseline" in (output / "review/master_lookup_review.md").read_text()
    assert {
        p.relative_to(bundle).as_posix(): p.read_bytes() for p in bundle.rglob("*") if p.is_file()
    } == original
    assert {
        c["id"] for c in json.loads((output / "promotion_diff.json").read_bytes())["changes"]
    } == {"status", "signoff"}
    for name, digest in json.loads((output / "bundle_checksums.json").read_bytes()).items():
        assert sha256((output / name).read_bytes()) == digest
    with pytest.raises(FileExistsError):
        promote_bundle(bundle, record, output)
    again = promote_bundle(bundle, record, tmp_path / "again")
    assert (output / "bundle_checksums.json").read_bytes() == (
        again / "bundle_checksums.json"
    ).read_bytes()


@pytest.mark.parametrize(
    "field", ["profile_id", "profile_version", "profile_content_sha256", "review_content_sha256"]
)
def test_approval_cannot_cover_other_versions_or_changed_review(prepared, field):
    _, profile, content, approval = prepared
    payload = approval.model_dump(mode="json")
    payload[field] = "0" * 64 if field.endswith("sha256") else "different"
    with pytest.raises(ValueError, match="exact profile"):
        apply_approval(profile, content, ProfileApproval.model_validate(payload))


def test_approval_does_not_override_content_gaps_and_changes_invalidate_signoff(prepared, tmp_path):
    _, profile, content, approval = prepared
    payload = content.model_dump(mode="json")
    payload["parameters"][0]["response"].update(status="missing", action_required="Supply evidence")
    content = ReviewContent.model_validate(payload)
    record = approval.model_dump(mode="json")
    record["review_content_sha256"] = sha256(json_bytes(content.model_dump(mode="json")))
    with pytest.raises(ProfileError):
        apply_approval(profile, content, ProfileApproval.model_validate(record))
    approved = apply_approval(profile, prepared[2], approval)
    assert "STALE_CONTENT_SIGNOFF" in {f.code for f in validate_content(approved, content).findings}
    with pytest.raises(ProfileError):
        export_review(approved, content, tmp_path / "stale-review")
    assert not (tmp_path / "stale-review").exists()
    changed = approved.model_dump(mode="json")
    changed["parameters"][0]["notes"] = "Changed rule content"
    assert "STALE_PROFILE_SIGNOFF" in {
        f.code for f in validate_profile(StandardsProfile.model_validate(changed)).findings
    }


def test_promotion_cli_and_integrity_failure(prepared, tmp_path, capsys):
    bundle, _, _, approval = prepared
    record = tmp_path / "approval.json"
    record.write_bytes(json_bytes(approval.model_dump(mode="json")))
    output = tmp_path / "approved"
    assert (
        main(
            ["promote", "--bundle", str(bundle), "--approval", str(record), "--output", str(output)]
        )
        == 0
    )
    assert (
        main(
            [
                "validate",
                "--profile",
                str(output / "profile"),
                "--content",
                str(output / "content.json"),
            ]
        )
        == 0
    )
    (bundle / "content.json").write_text("{}")
    assert (
        main(
            [
                "promote",
                "--bundle",
                str(bundle),
                "--approval",
                str(record),
                "--output",
                str(tmp_path / "bad"),
            ]
        )
        == 2
    )
    assert not (tmp_path / "bad").exists()
    capsys.readouterr()


def test_explicit_active_selection_requires_matching_pins(prepared, tmp_path, monkeypatch):
    bundle, _, _, approval = prepared
    record = tmp_path / "approval.json"
    record.write_bytes(json_bytes(approval.model_dump(mode="json")))
    recipe = tmp_path / "recipe.json"
    recipe.write_text('{"purpose":"synthetic test only"}\n')
    promote_bundle(bundle, record, tmp_path / "approved")
    selection = ActiveProfile(
        schema_version="1",
        profile_id=approval.profile_id,
        profile_version=approval.profile_version,
        profile_content_sha256=approval.profile_content_sha256,
        local_bundle="approved",
        recipe_filename=recipe.name,
        recipe_sha256=sha256(recipe.read_bytes()),
        approval_filename=record.name,
        approval_sha256=sha256(record.read_bytes()),
    )
    path = tmp_path / "active-profile.json"
    path.write_bytes(json_bytes(selection.model_dump(mode="json")))
    assert resolve_active_profile(path, tmp_path) == tmp_path / "approved"
    monkeypatch.chdir(tmp_path)
    assert main(["validate", "--active-profile", str(path)]) == 0
    recipe.write_text("changed recipe")
    with pytest.raises(ValueError, match="configuration hash mismatch"):
        resolve_active_profile(path, tmp_path)
