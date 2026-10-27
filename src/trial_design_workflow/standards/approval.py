"""Apply an explicit, content-bound human decision to a new standards package."""

import json
from datetime import datetime
from pathlib import Path
from typing import Literal, Self

from pydantic import model_validator

from ..schemas import Digest, Model, Text
from ..serialization import sha256
from .models import Signoff, StandardsProfile
from .profile import ProfileError, build_profile, json_bytes, load_profile, safe_path, semantic_diff
from .review import ReviewContent, export_review, validate_content
from .validation import content_digest


class ProfileApproval(Model):
    schema_version: Literal["1"]
    decision: Literal["approved_for_mvp"]
    profile_id: Text
    profile_version: Text
    profile_content_sha256: Digest
    review_content_sha256: Digest
    reviewer_id: Text
    recorded_at: datetime
    authorization: Text
    scope: Text

    @model_validator(mode="after")
    def timezone(self) -> Self:
        if self.recorded_at.tzinfo is None:
            raise ValueError("approval record timestamp requires a timezone")
        return self

    def signoff(self) -> Signoff:
        return Signoff(
            reviewer_id=self.reviewer_id,
            reviewed_at=self.recorded_at,
            rationale=self.authorization + " Scope: " + self.scope,
            content_sha256=self.profile_content_sha256,
            review_content_sha256=self.review_content_sha256,
        )


class ActiveProfile(Model):
    schema_version: Literal["1"]
    profile_id: Text
    profile_version: Text
    profile_content_sha256: Digest
    local_bundle: Text
    recipe_filename: Text
    recipe_sha256: Digest
    approval_filename: Text
    approval_sha256: Digest


def resolve_active_profile(selection_path: Path, repository_root: Path) -> Path:
    """Resolve an explicit pinned selection, never a latest-version/default search."""
    selection = ActiveProfile.model_validate_json(selection_path.read_bytes())
    config = selection_path.parent
    for name, digest in (
        (selection.recipe_filename, selection.recipe_sha256),
        (selection.approval_filename, selection.approval_sha256),
    ):
        if sha256(safe_path(config, name).read_bytes()) != digest:
            raise ValueError("Active profile configuration hash mismatch")
    approval = ProfileApproval.model_validate_json(
        safe_path(config, selection.approval_filename).read_bytes()
    )
    bundle = safe_path(repository_root, selection.local_bundle)
    profile = load_profile(bundle / "profile")
    content = ReviewContent.model_validate_json((bundle / "content.json").read_bytes())
    if (
        selection.profile_id != profile.manifest.profile_id
        or selection.profile_id != approval.profile_id
        or selection.profile_version != profile.manifest.profile_version
        or selection.profile_version != approval.profile_version
        or selection.profile_content_sha256 != content_digest(profile)
        or selection.profile_content_sha256 != approval.profile_content_sha256
        or sha256(json_bytes(content.model_dump(mode="json"))) != approval.review_content_sha256
        or profile.manifest.signoff != approval.signoff()
    ):
        raise ValueError("Active profile differs from its approved content")
    report = validate_content(profile, content)
    if not report.valid or any(f.blocking for f in report.findings):
        raise ProfileError(report)
    return bundle


def apply_approval(
    profile: StandardsProfile, content: ReviewContent, approval: ProfileApproval
) -> StandardsProfile:
    """No inferred approval, content edits, missing-source override, or credential assertion."""
    profile = StandardsProfile.model_validate_json(profile.model_dump_json())
    content = ReviewContent.model_validate_json(content.model_dump_json())
    approval = ProfileApproval.model_validate_json(approval.model_dump_json())
    if profile.manifest.status != "draft" or profile.manifest.scope != "clinical":
        raise ValueError("Promotion requires a clinical draft")
    if (
        approval.profile_id != profile.manifest.profile_id
        or approval.profile_version != profile.manifest.profile_version
        or approval.profile_content_sha256 != content_digest(profile)
        or approval.review_content_sha256 != sha256(json_bytes(content.model_dump(mode="json")))
    ):
        raise ValueError("Approval does not bind to this exact profile and review content")
    report = validate_content(profile, content)
    if any(f.blocking and f.code != "DRAFT_PROFILE" for f in report.findings):
        raise ProfileError(report)
    payload = profile.model_dump(mode="json")
    payload["manifest"].update(
        status="approved_for_mvp",
        signoff=approval.signoff().model_dump(mode="json"),
    )
    approved = StandardsProfile.model_validate(payload)
    report = validate_content(approved, content)
    if not report.valid or any(f.blocking for f in report.findings):
        raise ProfileError(report)
    return approved


def promote_bundle(bundle: Path, approval_path: Path, output: Path) -> Path:
    """Preserve the immutable draft and emit an approved, independently checked descendant."""
    if output.exists():
        raise FileExistsError("Choose a new output directory")
    inventory_bytes = safe_path(bundle, "bundle_checksums.json").read_bytes()
    inventory = json.loads(inventory_bytes)
    if not isinstance(inventory, dict):
        raise ValueError("Invalid bundle inventory")
    actual = {p.relative_to(bundle).as_posix() for p in bundle.rglob("*") if p.is_file()}
    if actual != set(inventory) | {"bundle_checksums.json"}:
        raise ValueError("Unexpected or missing bundle files")
    root_artifacts = {}
    for name, digest in sorted(inventory.items()):
        path = safe_path(bundle, name)
        data = path.read_bytes()
        if sha256(data) != digest:
            raise ValueError("Bundle artifact hash mismatch")
        if "/" not in name:
            root_artifacts[name] = data
    approval_bytes = approval_path.read_bytes()
    approval = ProfileApproval.model_validate_json(approval_bytes)
    draft = load_profile(bundle / "profile", allow_draft=True)
    content = ReviewContent.model_validate_json(root_artifacts["content.json"])
    approved = apply_approval(draft, content, approval)
    output.mkdir(parents=True, exist_ok=False)
    build_profile(approved, bundle / "profile", output / "profile")
    export_review(approved, content, output / "review")
    root_artifacts.update(
        {
            "approval.json": approval_bytes,
            "promotion_diff.json": json_bytes(semantic_diff(draft, approved)),
            "promotion_provenance.json": json_bytes(
                {
                    "source_bundle_checksums_sha256": sha256(inventory_bytes),
                    "approval_sha256": sha256(approval_bytes),
                    "profile_content_unchanged": content_digest(draft) == content_digest(approved),
                    "historical_artifacts": "Original build/diff/source records retained.",
                }
            ),
        }
    )
    # This flag described the old comparison stage; the new copy records current status.
    if "source_resolutions.json" in root_artifacts:
        resolutions = json.loads(root_artifacts["source_resolutions.json"])
        resolutions["profile_approved"] = True
        root_artifacts["source_resolutions.json"] = json_bytes(resolutions)
    for name, data in sorted(root_artifacts.items()):
        with (output / name).open("xb") as stream:
            stream.write(data)
    hashes = {
        p.relative_to(output).as_posix(): sha256(p.read_bytes())
        for p in sorted(output.rglob("*"))
        if p.is_file()
    }
    (output / "bundle_checksums.json").write_bytes(json_bytes(hashes))
    load_profile(output / "profile")
    return output
