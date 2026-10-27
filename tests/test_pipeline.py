"""Network-free staged selection/generation/replay with source-backed synthetic inputs."""

import json
import socket
import sys

import pytest
from pipeline_fixtures import REVIEW, make_inputs, make_profile
from pydantic import ValidationError

from trial_design_workflow.generation import TSGeneration
from trial_design_workflow.pipeline_cli import export_schemas, main, replay, run_stage
from trial_design_workflow.selection import load_runtime, select_parameters
from trial_design_workflow.serialization import sha256
from trial_design_workflow.study_context import CuratedInputs, StudyContext, read_curated


def test_end_to_end_offline_saved_input_replay_and_no_overwrite(tmp_path, monkeypatch):
    profile = make_profile(tmp_path)
    facts, _ = make_inputs(tmp_path / "inputs")

    def offline(*args, **kwargs):
        raise AssertionError("Network access is forbidden")

    monkeypatch.setattr(socket, "socket", offline)
    selection = tmp_path / "selection"
    assert (
        run_stage(
            stage="select",
            facts=facts,
            profile=profile,
            output=selection,
            allow_draft_standards=True,
        )
        == 1
    )
    generated = tmp_path / "generated"
    # The frozen context and runtime contracts suffice; original study files are not needed.
    (facts.parent / "protocol.txt").unlink()
    assert (
        run_stage(
            stage="generate",
            facts=selection / "study_context.json",
            runtime_profile=selection / "runtime_profile.json",
            selection=selection / "parameter_selection.json",
            output=generated,
            allow_draft_standards=True,
        )
        == 1
    )
    assert (
        replay(manifest=selection / "run_manifest.json", output=tmp_path / "selection-replay") == 1
    )
    assert (
        replay(manifest=generated / "run_manifest.json", output=tmp_path / "generation-replay") == 1
    )
    for name in (
        "ts_records.json",
        "record_trace.json",
        "ts_generation.json",
        "parameter_selection.json",
        "qc_findings.json",
    ):
        assert (generated / name).read_bytes() == (
            tmp_path / "generation-replay" / name
        ).read_bytes()
    result = TSGeneration.model_validate_json((generated / "ts_generation.json").read_bytes())
    assert len(result.records) == 11 and all(r.TSPARMCD != "EXCL" for r in result.records)
    manifest = json.loads((generated / "run_manifest.json").read_bytes())
    for name, expected in manifest["files"].items():
        assert sha256((generated / name).read_bytes()) == expected
    assert manifest["network_used"] is False and manifest["source_artifact_hashes"]
    assert not list(generated.glob("*.xlsx"))
    with pytest.raises(ValueError, match="exists"):
        replay(manifest=generated / "run_manifest.json", output=generated)


def test_changed_bundle_or_implementation_cannot_replay(tmp_path):
    profile = make_profile(tmp_path)
    facts, _ = make_inputs(tmp_path / "inputs")
    output = tmp_path / "selected"
    run_stage(
        stage="select", facts=facts, profile=profile, output=output, allow_draft_standards=True
    )
    path = output / "run_manifest.json"
    manifest = json.loads(path.read_bytes())
    manifest["implementation_sha256"]["selection.py"] = "0" * 64
    path.write_text(json.dumps(manifest))
    with pytest.raises(ValueError, match="implementation"):
        replay(manifest=path, output=tmp_path / "bad")
    (output / "parameter_selection.json").write_text("{}")
    with pytest.raises(ValueError, match="hash mismatch"):
        replay(manifest=path, output=tmp_path / "bad")
    assert not (tmp_path / "bad").exists()


def test_evidence_source_type_review_and_raw_values_are_validated(tmp_path):
    path, _ = make_inputs(tmp_path / "inputs")
    payload = json.loads(path.read_bytes())
    fact = payload["facts"][0]
    fact["evidence"][0]["start"] = 0
    with pytest.raises(ValueError, match="grounded"):
        read_curated(CuratedInputs.model_validate(payload), path.parent)
    payload = json.loads(path.read_bytes())
    payload["facts"][0]["source_type"] = "study_data"
    with pytest.raises(ValueError, match="types disagree"):
        read_curated(CuratedInputs.model_validate(payload), path.parent)
    payload = json.loads(path.read_bytes())
    payload["facts"][0]["raw_value"] = "invented quote"
    with pytest.raises(ValueError, match="not in the cited"):
        read_curated(CuratedInputs.model_validate(payload), path.parent)
    payload = json.loads(path.read_bytes())
    payload["facts"][0]["review"]["reviewed_at"] = "2026-01-01"
    with pytest.raises(ValidationError, match="timezone"):
        CuratedInputs.model_validate(payload)
    payload = json.loads(path.read_bytes())
    payload["facts"][0]["reviewed_value"] = "Changed without correction"
    with pytest.raises(ValidationError, match="use correct"):
        CuratedInputs.model_validate(payload)
    payload = json.loads(path.read_bytes())
    payload["facts"].append(payload["facts"][0])
    with pytest.raises(ValueError, match="duplicate"):
        read_curated(CuratedInputs.model_validate(payload), path.parent)


def test_unknown_input_fields_and_source_hashes_cannot_bypass_boundary(tmp_path):
    path, _ = make_inputs(tmp_path / "inputs")
    payload = json.loads(path.read_bytes())
    payload["TSVAL"] = "Injected row"
    with pytest.raises(ValidationError):
        CuratedInputs.model_validate(payload)
    payload = json.loads(path.read_bytes())
    payload["sources"][0]["sha256"] = "0" * 64
    with pytest.raises(ValueError, match="source hash"):
        read_curated(CuratedInputs.model_validate(payload), path.parent)


def test_cli_dispatch_and_errors_do_not_echo_source(tmp_path, monkeypatch, capsys):
    from trial_design_workflow.ts_cli import main as ts_main

    profile = make_profile(tmp_path)
    facts, _ = make_inputs(tmp_path / "inputs")
    monkeypatch.setattr(
        sys,
        "argv",
        [
            "trial-ts",
            "select",
            "--facts",
            str(facts),
            "--profile",
            str(profile),
            "--output",
            str(tmp_path / "selected"),
            "--allow-draft-standards",
        ],
    )
    assert ts_main() == 1
    facts.write_text('{"private protocol sentence":"do not echo"}')
    assert (
        main(
            "select",
            [
                "--facts",
                str(facts),
                "--profile",
                str(profile),
                "--output",
                str(tmp_path / "bad"),
                "--allow-draft-standards",
            ],
        )
        == 2
    )
    output = capsys.readouterr()
    assert "private protocol sentence" not in output.out + output.err
    assert json.loads(output.err)["code"] == "DETERMINISTIC_STAGE_INPUT_ERROR"


def test_complete_collection_count_requires_reviewed_completeness(tmp_path):
    from trial_design_workflow.selection import evaluate_predicate
    from trial_design_workflow.standards.models import Predicate

    runtime = load_runtime(make_profile(tmp_path), allow_draft=True)
    _, context = make_inputs(tmp_path / "inputs")
    predicate = Predicate(op="fact_count", fact_key="repeated_value", value=2)
    assert evaluate_predicate(predicate, context, runtime).result is None
    payload = context.model_dump(mode="json")
    payload["complete_collections"] = [
        dict(fact_key="repeated_value", review=REVIEW, evidence=payload["facts"][0]["evidence"])
    ]
    complete = StudyContext.model_validate(payload)
    assert evaluate_predicate(predicate, complete, runtime).result is True
    assert (
        evaluate_predicate(
            Predicate(op="fact_count", fact_key="repeated_value", value=0), complete, runtime
        ).result
        is False
    )


def test_generation_schemas_export_from_models(tmp_path):
    output = tmp_path / "schemas"
    export_schemas(output)
    assert (
        json.loads((output / "ts-generation-v1.schema.json").read_bytes())
        == TSGeneration.model_json_schema()
    )
    assert main("schemas", ["--output", str(tmp_path / "schemas-2")]) == 0
    from pathlib import Path

    from trial_design_workflow.selection import ParameterSelection

    root = Path(__file__).parents[1] / "schemas"
    assert (
        json.loads((root / "parameter-selection-v1.schema.json").read_bytes())
        == ParameterSelection.model_json_schema()
    )
    assert (
        json.loads((root / "ts-generation-v1.schema.json").read_bytes())
        == TSGeneration.model_json_schema()
    )


def test_rule_reference_cycles_are_blocked_by_profile_validation(tmp_path):
    runtime = load_runtime(make_profile(tmp_path), allow_draft=True)
    _, context = make_inputs(tmp_path / "inputs")
    payload = runtime.model_dump(mode="json")
    payload["profile"]["applicability_rules"][0]["predicate"] = {
        "op": "rule_ref",
        "rule_id": payload["profile"]["applicability_rules"][0]["rule_id"],
    }
    from trial_design_workflow.selection import RuntimeProfile
    from trial_design_workflow.standards.models import StandardsProfile
    from trial_design_workflow.standards.profile import ProfileError
    from trial_design_workflow.standards.validation import content_digest

    payload["content"]["profile_content_sha256"] = content_digest(
        StandardsProfile.model_validate(payload["profile"])
    )
    with pytest.raises(ProfileError):
        select_parameters(context, RuntimeProfile.model_validate(payload), allow_draft=True)


def test_legacy_129_candidate_migration_is_visible_and_does_not_generate(tmp_path):
    from pathlib import Path

    from trial_design_workflow.generation import generate_ts

    legacy = (
        Path(__file__).parents[1]
        / "src/trial_design_workflow/assets/standards/legacy-candidates-2025-03-28"
    )
    runtime = load_runtime(legacy, allow_draft=True)
    _, context = make_inputs(tmp_path / "inputs")
    selection = select_parameters(context, runtime, allow_draft=True)
    assert len(selection.decisions) == 129
    assert all(d.decision == "manual_assessment" for d in selection.decisions)
    result = generate_ts(context, selection, runtime, allow_draft=True)
    assert not result.records
    assert any(f.code == "TS_STRUCTURE_METADATA_REQUIRED" for f in result.findings)
