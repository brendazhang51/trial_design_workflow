"""Identity-only migration of the immutable 2025 CT candidate assets."""

import csv
import io
import json
from datetime import UTC, datetime
from pathlib import Path

from ..serialization import sha256
from .models import StandardsProfile
from .profile import BUILD_VERSION, build_profile

POLICY = (
    "Legacy migration policy v1. Parameter identity only, not SDTMIG requiredness.\n"
    "All applicability, response mapping, cardinality and external requirements need review.\n"
    "No null flavor or automated derivation is authorized.\n"
)


def legacy_seed(assets: Path) -> tuple[StandardsProfile, dict[str, bytes]]:
    metadata = json.loads((assets / "sources.json").read_bytes())
    filenames = ("ct-2025-03-28.csv", "ts-parameters-v1.csv", "protocol-facts-v1.json")
    staged = {}
    for filename in filenames:
        content = (assets / filename).read_bytes()
        if sha256(content) != metadata["files"][filename]:
            raise ValueError("Legacy asset differs from its immutable source metadata")
        staged["sources/" + filename] = content
    staged["sources/sources.json"] = (assets / "sources.json").read_bytes()
    staged["sources/migration-policy-v1.txt"] = POLICY.encode()
    release = metadata["ct_release"]
    sources = []
    for filename, content in sorted(staged.items()):
        official = filename.endswith("ct-2025-03-28.csv")
        sources.append(
            {
                "source_id": "legacy-ct" if official else Path(filename).name,
                "title": "Bundled NCI CT subset" if official else Path(filename).name,
                "publisher": "NCI EVS" if official else "trial_design_workflow",
                "version": release if official else "legacy-v1",
                "url": metadata["source_url"] if official else None,
                "publication_date": None,
                "retrieval_date": None,
                "local_filename": filename,
                "sha256": sha256(content),
                "license_note": "Existing repository asset; original source license not inferred.",
                "normative_level": 3 if official else 5,
                "provenance": "cdisc" if official else "historical",
            }
        )
    policy_ref = [{"source_id": "migration-policy-v1.txt", "locator": "identity-only migration"}]
    rows = list(
        csv.DictReader(
            io.StringIO(
                staged["sources/ts-parameters-v1.csv"].decode("utf-8-sig"),
                newline="",
            )
        )
    )
    terms = list(
        csv.DictReader(
            io.StringIO(
                staged["sources/ct-2025-03-28.csv"].decode("utf-8-sig"),
                newline="",
            )
        )
    )
    codes = {t["value"]: t["code"] for t in terms if t["codelist"] == "C66738"}
    parameters = []
    for row in rows:
        parameters.append(
            {
                "tsparmcd": row["TSPARMCD"],
                "tsparm": row["TSPARM"],
                "concept_code": codes[row["TSPARMCD"]],
                "ct_release": release,
                "parameter_status": "active",
                "applicability_rule_id": "manual-review-v1",
                "base_disposition": "manual_assessment",
                "authority_scope": "historical",
                "authority_refs": [{"source_id": "legacy-ct", "locator": "C66738/C67152"}],
                "min_records": 0,
                "max_records": None,
                "repeat_key": [],
                "tsgrpid_rule_id": None,
                "sort_key": row["TSPARMCD"],
                "value_profile_id": "manual-value-v1",
                "fact_key": None,
                "derivation_id": "manual-derivation-v1",
                "value_map_id": None,
                "automation_level": "manual",
                "evidence_requirements": "Document exact evidence and an authoritative value rule.",
                "review_reason": "SDTMIG applicability and response rules have not been supplied.",
                "notes": "Legacy suggestion (not executable): "
                + json.dumps(
                    {
                        k: row[k]
                        for k in ("expected_fact_key", "response_codelist", "likely_source")
                    },
                    sort_keys=True,
                ),
            }
        )
    roles = (
        "sdtm",
        "sdtmig",
        "errata",
        "conformance",
        "ct",
        "ct_relationships",
        "regulator_catalog",
        "regulator_guide",
        "sponsor_rules",
    )
    standards = {
        role: {
            "status": "missing",
            "version": {"sdtm": "2.0", "sdtmig": "3.4"}.get(role),
            "source_id": None,
            "reason": "Authoritative source/scope not supplied or reviewed.",
        }
        for role in roles
    }
    standards["ct"] = {
        "status": "pinned",
        "version": release,
        "source_id": "legacy-ct",
        "reason": "Existing immutable seven-codelist subset, not a complete standards package.",
    }
    return StandardsProfile.model_validate(
        {
            "manifest": {
                "schema_version": "2",
                "profile_id": "legacy-candidates-2025-03-28",
                "profile_version": "1",
                "created_at": datetime(2026, 10, 26, tzinfo=UTC),
                "status": "draft",
                "scope": "legacy",
                "submission_context": "Unselected; historical CT candidate migration only",
                "standards": standards,
                "build_tool_version": BUILD_VERSION,
                "output_hashes": {},
                "signoff": None,
            },
            "sources": sources,
            "fact_keys": [],
            "parameters": parameters,
            "applicability_rules": [
                {
                    "rule_id": "manual-review-v1",
                    "version": "1",
                    "priority": 0,
                    "predicate": None,
                    "on_true": "manual_assessment",
                    "on_false": "manual_assessment",
                    "on_unknown": "manual_assessment",
                    "authority_refs": policy_ref,
                    "explanation": "No authoritative rule supplied; human assessment needed.",
                }
            ],
            "value_profiles": [
                {
                    "value_profile_id": "manual-value-v1",
                    "value_type": "manual",
                    "response_terminology": None,
                    "response_codelist": None,
                    "allow_tsvalnf": False,
                    "allowed_null_flavors": [],
                    "external_source_required": False,
                    "target_fields": ["TSVAL"],
                    "long_text_policy": "block_for_review",
                    "authority_refs": policy_ref,
                }
            ],
            "derivations": [
                {
                    "derivation_id": "manual-derivation-v1",
                    "version": "1",
                    "fact_keys": [],
                    "transform": "manual",
                    "source_requirement": "manual",
                    "authority_refs": policy_ref,
                }
            ],
            "grouping_rules": [],
            "terminology": [
                {**term, "status": "active", "source_id": "legacy-ct"} for term in terms
            ],
            "value_maps": [],
        }
    ), staged


def build_legacy_profile(assets: Path, staging: Path, output: Path) -> Path:
    """Explicit maintenance operation; never modifies the legacy inputs."""
    profile, files = legacy_seed(assets)
    if staging.exists() or output.exists():
        raise FileExistsError("Staging and profile output must both be new directories")
    staging.mkdir(parents=True, exist_ok=False)
    for filename, content in sorted(files.items()):
        target = staging / filename
        target.parent.mkdir(parents=True, exist_ok=True)
        with target.open("xb") as stream:
            stream.write(content)
    with (staging / "profile.json").open("x") as stream:
        stream.write(profile.model_dump_json(indent=2) + "\n")
    return build_profile(profile, staging, output)
