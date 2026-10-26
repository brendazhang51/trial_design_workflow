"""Reproducible profile packaging from local staged inputs only."""

import csv
import io
import json
from pathlib import Path, PurePosixPath

from pydantic import ValidationError

from ..serialization import canonical_json, sha256
from .models import (
    ParameterDefinition,
    ProfileFinding,
    StandardsProfile,
    TerminologyTerm,
    ValidationReport,
    ValueMap,
)
from .validation import normalized_payload, validate_profile

BUILD_VERSION = "master-lookup-builder-v1"
JSON_FILES = {
    "manifest.json": "manifest",
    "source_index.json": "sources",
    "fact_keys.json": "fact_keys",
    "applicability_rules.json": "applicability_rules",
    "value_profiles.json": "value_profiles",
    "derivation_rules.json": "derivations",
    "grouping_rules.json": "grouping_rules",
}
CSV_FILES = {
    "master_lookup.csv": ("parameters", ParameterDefinition),
    "terminology.csv": ("terminology", TerminologyTerm),
    "value_maps.csv": ("value_maps", ValueMap),
}
PROFILE_FILES = set(JSON_FILES) | set(CSV_FILES)


class ProfileError(ValueError):
    def __init__(self, report: ValidationReport):
        self.report = report
        super().__init__("Standards profile failed validation; inspect structured findings.")


def safe_path(root: Path, filename: str) -> Path:
    relative = PurePosixPath(filename)
    if relative.is_absolute() or ".." in relative.parts or "\\" in filename or not filename:
        raise ValueError("Profile paths must be relative and remain inside their directory")
    target = (root / filename).resolve()
    if not target.is_relative_to(root.resolve()) or target == root.resolve():
        raise ValueError("Profile path escapes its directory")
    return target


def json_bytes(payload: object) -> bytes:
    return (canonical_json(payload) + "\n").encode()


def csv_bytes(rows: list[dict], model: type) -> bytes:
    stream = io.StringIO(newline="")
    writer = csv.DictWriter(stream, fieldnames=list(model.model_fields), lineterminator="\n")
    writer.writeheader()
    # JSON-encoded cells distinguish null, empty strings, booleans, lists and numbers.
    writer.writerows({k: canonical_json(v) for k, v in row.items()} for row in rows)
    return stream.getvalue().encode()


def csv_payload(content: bytes, model: type) -> list[dict]:
    reader = csv.DictReader(io.StringIO(content.decode("utf-8"), newline=""))
    if reader.fieldnames != list(model.model_fields):
        raise ValueError("Profile CSV header does not match its versioned schema")
    rows = []
    for row in reader:
        if None in row or any(v is None for v in row.values()):
            raise ValueError("Malformed profile CSV row")
        rows.append({k: json.loads(v) for k, v in row.items()})
    return rows


def build_profile(profile: StandardsProfile, source_root: Path, output: Path) -> Path:
    """Only writes a new directory; timestamps/versions come from supplied inputs."""
    if output.exists():
        raise FileExistsError("Profile output already exists; choose a new version/directory")
    if profile.manifest.build_tool_version != BUILD_VERSION:
        raise ValueError("Profile must explicitly select this builder version")
    report = validate_profile(profile, allow_draft=True)
    if not report.valid:
        raise ProfileError(report)
    payload = normalized_payload(profile)
    files: dict[str, bytes] = {}
    for source in profile.sources:
        if not source.local_filename.startswith("sources/"):
            raise ValueError("Source files must be stored under sources/")
        source_path = safe_path(source_root, source.local_filename)
        content = source_path.read_bytes()
        if sha256(content) != source.sha256:
            raise ValueError("Staged source hash mismatch")
        files[source.local_filename] = content
    for filename, (key, model) in CSV_FILES.items():
        files[filename] = csv_bytes(payload[key], model)
    for filename, key in JSON_FILES.items():
        if filename != "manifest.json":
            files[filename] = json_bytes(payload[key])
    payload["manifest"]["output_hashes"] = {
        name: sha256(content) for name, content in sorted(files.items())
    }
    files["manifest.json"] = json_bytes(payload["manifest"])
    files["checksums.json"] = json_bytes(
        {name: sha256(content) for name, content in sorted(files.items())}
    )
    # All inputs and schema gates have passed before any output is created.
    output.mkdir(parents=True, exist_ok=False)
    for filename, content in sorted(files.items()):
        target = safe_path(output, filename)
        target.parent.mkdir(parents=True, exist_ok=True)
        with target.open("xb") as stream:
            stream.write(content)
    return output


def read_profile(directory: Path) -> StandardsProfile:
    """Verify closed-set artifact hashes before parsing domain contracts."""
    checksums = json.loads(safe_path(directory, "checksums.json").read_bytes())
    if not isinstance(checksums, dict) or not PROFILE_FILES <= set(checksums):
        raise ValueError("Incomplete profile checksum inventory")
    for filename, expected in sorted(checksums.items()):
        if filename == "checksums.json":
            raise ValueError("Checksum inventory cannot hash itself")
        if filename not in PROFILE_FILES and not filename.startswith("sources/"):
            raise ValueError("Unexpected artifact in profile checksum inventory")
        if sha256(safe_path(directory, filename).read_bytes()) != expected:
            raise ValueError("Profile artifact hash mismatch")
    actual = {p.relative_to(directory).as_posix() for p in directory.rglob("*") if p.is_file()}
    if actual != set(checksums) | {"checksums.json"}:
        raise ValueError("Uninventoried or missing profile artifacts")
    payload = {
        key: json.loads(safe_path(directory, filename).read_bytes())
        for filename, key in JSON_FILES.items()
    }
    for filename, (key, model) in CSV_FILES.items():
        payload[key] = csv_payload(safe_path(directory, filename).read_bytes(), model)
    profile = StandardsProfile.model_validate(payload)
    expected_outputs = {
        name: digest for name, digest in checksums.items() if name != "manifest.json"
    }
    if profile.manifest.output_hashes != expected_outputs:
        raise ValueError("Manifest output hashes differ from checksum inventory")
    expected_sources = {s.local_filename for s in profile.sources}
    actual_sources = set(checksums) - PROFILE_FILES
    if expected_sources != actual_sources:
        raise ValueError("Source index differs from packaged source inventory")
    for source in profile.sources:
        if source.sha256 != checksums[source.local_filename]:
            raise ValueError("Source hash differs from declared provenance")
    return profile


def inspect_profile(directory: Path, *, allow_draft: bool = False) -> ValidationReport:
    try:
        return validate_profile(read_profile(directory), allow_draft=allow_draft)
    except ValidationError as exc:
        # Never echo input values or raw source text in error output.
        return ValidationReport(
            profile_id=None,
            findings=tuple(
                ProfileFinding(
                    code="PROFILE_SCHEMA_INVALID",
                    severity="error",
                    blocking=True,
                    location=".".join(map(str, e["loc"])),
                    message="Profile field failed schema validation: " + e["type"],
                )
                for e in exc.errors(include_input=False, include_url=False)
            ),
        )
    except (OSError, ValueError, TypeError, KeyError) as exc:
        return ValidationReport(
            profile_id=None,
            findings=(
                ProfileFinding(
                    code="PROFILE_INTEGRITY_ERROR",
                    severity="error",
                    blocking=True,
                    location="profile",
                    message="Profile cannot be verified: " + type(exc).__name__,
                ),
            ),
        )


def load_profile(directory: Path, *, allow_draft: bool = False) -> StandardsProfile:
    report = inspect_profile(directory, allow_draft=allow_draft)
    if not report.valid:
        raise ProfileError(report)
    return read_profile(directory)


def semantic_diff(before: StandardsProfile, after: StandardsProfile) -> dict:
    """Return content changes independently of packaging hashes and list order."""
    old, new = normalized_payload(before), normalized_payload(after)
    changes = []
    tables = {
        "parameters": "tsparmcd",
        "applicability_rules": "rule_id",
        "value_profiles": "value_profile_id",
        "derivations": "derivation_id",
        "grouping_rules": "rule_id",
        "sources": "source_id",
    }
    for table, key in tables.items():
        left, right = ({r[key]: r for r in p[table]} for p in (old, new))
        for identity in sorted(left.keys() | right.keys()):
            if left.get(identity) != right.get(identity):
                changes.append(
                    {
                        "table": table,
                        "id": identity,
                        "before": left.get(identity),
                        "after": right.get(identity),
                    }
                )
    for table in ("value_maps", "terminology", "fact_keys"):
        if old[table] != new[table]:
            changes.append({"table": table, "before": old[table], "after": new[table]})
    for field in (
        "standards",
        "submission_context",
        "scope",
        "status",
        "signoff",
        "profile_version",
        "schema_version",
        "build_tool_version",
    ):
        if old["manifest"][field] != new["manifest"][field]:
            changes.append(
                {
                    "table": "manifest",
                    "id": field,
                    "before": old["manifest"][field],
                    "after": new["manifest"][field],
                }
            )
    return {
        "before_profile": before.manifest.profile_id,
        "after_profile": after.manifest.profile_id,
        "changes": changes,
    }
