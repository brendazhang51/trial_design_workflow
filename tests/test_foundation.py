import json

import pytest
from pydantic import ValidationError

from trial_design_workflow.cli import main, run_files
from trial_design_workflow.engine import (
    canonical_json,
    generate,
    proposal_digest,
    propose,
    sha256,
    validate_output,
)
from trial_design_workflow.schemas import Manifest, RunInput, RunOutput, TSRecord


def update(run, change):
    payload = run.model_dump(mode="json")
    change(payload)
    return RunInput.model_validate(payload)


def codes(findings):
    return {f.code for f in findings}


def test_complete_candidate_review_and_approved_generation(run):
    output = generate(run)
    assert len(output.proposals) == len(run.registry.parameters) == 7
    assert {d.state for d in output.proposals} == {
        "include",
        "exclude",
        "needs_review",
        "needs_external_source",
        "unsupported",
    }
    assert [(r.TSSEQ, r.TSPARMCD, r.TSVAL) for r in output.records] == [
        (1, "X_DESIGN", "EXAMPLE PARALLEL"),
        (2, "X_TITLE", "Example Study"),
    ]
    assert codes(output.findings) == {"SYNTHETIC_SCOPE", "EXCLUDED", "UNRESOLVED_PARAMETER"}
    assert validate_output(run, output) == ()
    assert set(output.records[0].model_dump()) == {
        "STUDYID",
        "DOMAIN",
        "TSSEQ",
        "TSPARMCD",
        "TSPARM",
        "TSVAL",
    }
    trace = output.traceability[0]
    assert trace.evidence[0].pdf_page_index == 0
    assert trace.evidence[0].printed_page == "SYN-1"
    assert trace.term.code == "TEST_PARALLEL"
    assert trace.rule.artifact_id == "synthetic-rules-v1"


def test_no_decision_approval_means_no_records(pending_run):
    output = generate(pending_run)
    assert output.records == ()
    assert len(output.proposals) == 7
    assert sum(f.code == "DECISION_REVIEW_REQUIRED" for f in output.findings) == 7


def test_no_fact_approval_never_becomes_verified(run):
    changed = update(run, lambda p: p["facts"][0].update(reviews=[]))
    decision = next(d for d in propose(changed) if d.fact_id == "title")
    assert decision.state == "needs_review"
    assert decision.value is None
    assert "X_TITLE" not in {r.TSPARMCD for r in generate(changed).records}


def test_corrections_preserve_proposal_and_old_review(run):
    def correct(payload):
        fact = payload["facts"][0]
        review = dict(fact["reviews"][-1])
        review.update(
            action="correct",
            approved_value="Corrected synthetic title",
            rationale="Simulated correction",
            reviewed_at="2026-01-02T00:00:00Z",
        )
        fact["reviews"].append(review)

    changed = update(run, correct)
    fact = changed.facts[0]
    assert fact.proposed_value == "Example Study"
    assert fact.approved_value == "Corrected synthetic title"
    assert len(fact.reviews) == 2
    assert "STALE_APPROVAL" in codes(generate(changed).findings)
    assert "X_TITLE" not in {r.TSPARMCD for r in generate(changed).records}


@pytest.mark.parametrize(
    "mutation",
    [
        lambda p: p.update(study_id="CHANGED"),
        lambda p: p["facts"][0]["evidence"][0].update(quote="Different evidence"),
        lambda p: p["documents"][0]["artifact"].update(sha256="f" * 64),
        lambda p: p["registry"]["artifact"].update(version="synthetic-v2"),
        lambda p: p["registry"]["rules"][0].update(description="Different rule"),
        lambda p: p["terminology"]["artifact"].update(version="synthetic-v2"),
    ],
)
def test_approval_is_bound_to_source_and_rule_context(run, mutation):
    changed = update(run, mutation)
    assert "STALE_APPROVAL" in codes(generate(changed).findings)


def test_order_independence(run):
    def shuffle(payload):
        payload["facts"].reverse()
        payload["registry"]["parameters"].reverse()
        payload["registry"]["rules"].reverse()

    changed = update(run, shuffle)
    assert generate(changed) == generate(run)


def test_rejection_revokes_approval(run):
    def reject(payload):
        review = dict(payload["decision_reviews"][-1])
        review.update(action="reject", reviewed_at="2026-01-02T00:00:00Z")
        payload["decision_reviews"].append(review)

    changed = update(run, reject)
    assert "X_UNSUP" in {d.parameter_code for d in generate(changed).proposals}
    assert "DECISION_REVIEW_REQUIRED" in codes(generate(changed).findings)


def test_unknown_controlled_value_requires_review(run):
    def change(payload):
        fact = payload["facts"][1]
        fact["proposed_value"] = "UNKNOWN"
        fact["reviews"][0]["approved_value"] = "UNKNOWN"

    changed = update(run, change)
    decision = next(d for d in propose(changed) if d.parameter_code == "X_DESIGN")
    assert decision.state == "needs_review"
    assert decision.term is None


@pytest.mark.parametrize(
    "value, expected",
    [
        ("a" * 101, "FIELD_LENGTH"),
        ("bad\x00text", "FIELD_CHARACTER"),
        ("bad\ntext", "FIELD_CHARACTER"),
    ],
)
def test_long_text_and_characters_block_without_splitting(run, value, expected):
    def change(payload):
        fact = payload["facts"][0]
        fact["proposed_value"] = value
        fact["reviews"][0]["approved_value"] = value

    changed = update(run, change)

    # Explicit simulated reapproval of the changed proposal, not auto-approval by generation.
    def reapprove(payload):
        for review in payload["decision_reviews"]:
            decision = next(
                d for d in propose(changed) if d.parameter_code == review["parameter_code"]
            )
            review["proposal_sha256"] = proposal_digest(changed, decision)

    changed = update(changed, reapprove)
    output = generate(changed)
    assert expected in codes(output.findings)
    assert [r.TSPARMCD for r in output.records] == ["X_DESIGN"]
    assert [r.TSSEQ for r in output.records] == [1]


@pytest.mark.parametrize(
    "mutation",
    [
        lambda p: p.update(unexpected="not permitted"),
        lambda p: p["documents"][0].update(synthetic=False),
        lambda p: p["documents"][0]["artifact"].update(sha256="invalid"),
        lambda p: p["facts"][0]["evidence"][0].update(document_id="missing"),
        lambda p: p["facts"][0]["evidence"][0].update(pdf_page_index=-1),
        lambda p: p["facts"][0].update(evidence=[]),
        lambda p: p["facts"][0]["reviews"][0].update(approved_value="unexplained correction"),
        lambda p: p["facts"][0]["reviews"][0].update(reviewed_at="2026-01-01T00:00:00"),
        lambda p: p["registry"]["parameters"].append(p["registry"]["parameters"][0]),
        lambda p: p["registry"]["parameters"][0].update(rule_id="missing-rule"),
        lambda p: p["registry"]["rules"][0].update(provenance="regulatory"),
        lambda p: p["terminology"]["terms"].append(p["terminology"]["terms"][0]),
    ],
)
def test_untrusted_inputs_rejected(run, mutation):
    with pytest.raises(ValidationError):
        update(run, mutation)


@pytest.mark.parametrize("field, value", [("STUDYID", ""), ("TSVAL", "   "), ("TSSEQ", 0)])
def test_invalid_structural_record_rejected(run, field, value):
    payload = generate(run).records[0].model_dump()
    payload[field] = value
    with pytest.raises(ValidationError):
        TSRecord.model_validate(payload)


def test_qc_detects_duplicate_records_and_missing_trace(run):
    original = generate(run)
    payload = original.model_dump(mode="json")
    payload["records"].append(payload["records"][0])
    payload["traceability"] = []
    output = RunOutput.model_validate(payload)
    assert codes(validate_output(run, output)) >= {
        "DUPLICATE_LOGICAL_KEY",
        "DUPLICATE_SEQUENCE",
        "UNSTABLE_ORDER",
        "MISSING_PROVENANCE",
        "REGENERATION_MISMATCH",
        "AUDIT_MISMATCH",
    }


def test_qc_detects_mapping_and_value_edits(run):
    payload = generate(run).model_dump(mode="json")
    payload["records"][0].update(TSPARM="Wrong label", TSVAL="Unverified value")
    output = RunOutput.model_validate(payload)
    assert codes(validate_output(run, output)) >= {
        "PARAMETER_MAPPING",
        "UNVERIFIED_TERMINOLOGY",
        "UNAPPROVED_VALUE",
        "REGENERATION_MISMATCH",
    }


def test_cli_roundtrip_hashes_and_stable_regeneration(run, tmp_path):
    input_path = tmp_path / "input.json"
    input_path.write_text(run.model_dump_json())
    first, second = tmp_path / "first", tmp_path / "second"
    assert run_files(input_path, first) == 0
    assert run_files(input_path, second) == 0
    manifest = Manifest.model_validate_json((first / "manifest.json").read_bytes())
    assert manifest.standards_status == "not_loaded"
    assert manifest.inputs[0].sha256 == sha256(input_path.read_bytes())
    for artifact in manifest.outputs:
        assert artifact.sha256 == sha256((first / artifact.path).read_bytes())
        assert (first / artifact.path).read_bytes() == (second / artifact.path).read_bytes()
    records = json.loads((first / "ts_records.json").read_text())
    assert len([TSRecord.model_validate(r) for r in records]) == 2
    assert manifest.logical_records_sha256 == sha256(canonical_json(records).encode())
    assert manifest.generated_at.tzinfo is not None
    with pytest.raises(FileExistsError):
        run_files(input_path, first)


def test_hash_mismatch_prevents_output(run, tmp_path):
    changed = update(run, lambda p: p["documents"][0]["artifact"].update(sha256="0" * 64))
    input_path = tmp_path / "input.json"
    input_path.write_text(changed.model_dump_json())
    with pytest.raises(ValueError, match="Hash mismatch"):
        run_files(input_path, tmp_path / "output")
    assert not (tmp_path / "output").exists()


@pytest.mark.parametrize("kind", ["registry", "terminology"])
def test_embedded_configuration_must_match_pinned_asset(run, tmp_path, kind):
    def change(payload):
        if kind == "registry":
            payload["registry"]["parameters"][0]["label"] = "Unpinned label"
        else:
            payload["terminology"]["terms"][0]["code"] = "UNPINNED_CODE"

    changed = update(run, change)
    input_path = tmp_path / "input.json"
    input_path.write_text(changed.model_dump_json())
    with pytest.raises(ValueError, match="differs from its pinned source artifact"):
        run_files(input_path, tmp_path / "output")
    assert not (tmp_path / "output").exists()


def test_rejected_fact_is_unresolved_even_with_prior_approval(run):
    def reject(payload):
        review = dict(payload["facts"][0]["reviews"][0])
        review.update(
            action="reject",
            approved_value=None,
            reviewed_at="2026-01-02T00:00:00Z",
            rationale="Simulated revocation",
        )
        payload["facts"][0]["reviews"].append(review)

    changed = update(run, reject)
    decision = next(d for d in propose(changed) if d.parameter_code == "X_TITLE")
    assert decision.state == "needs_review"
    assert decision.value is None
    assert "X_TITLE" not in {r.TSPARMCD for r in generate(changed).records}


def test_reject_latest_include_decision_removes_record(run):
    def reject(payload):
        review = next(
            dict(r) for r in payload["decision_reviews"] if r["parameter_code"] == "X_TITLE"
        )
        review.update(action="reject", reviewed_at="2026-01-02T00:00:00Z")
        payload["decision_reviews"].append(review)

    changed = update(run, reject)
    assert [r.TSPARMCD for r in generate(changed).records] == ["X_DESIGN"]


def test_cli_schema_errors_are_structured_and_do_not_echo_values(tmp_path, monkeypatch, capsys):
    input_path = tmp_path / "invalid.json"
    input_path.write_text('{"study_id": "CONFIDENTIAL_TEST_SENTINEL"}')
    monkeypatch.setattr(
        "sys.argv",
        ["trial-design", "--input", str(input_path), "--output", str(tmp_path / "output")],
    )
    assert main() == 2
    stderr = capsys.readouterr().err
    assert "CONFIDENTIAL_TEST_SENTINEL" not in stderr
    assert all(f["code"] == "INVALID_INPUT" for f in json.loads(stderr))
    assert not (tmp_path / "output").exists()


def test_cli_pending_bundle_has_no_records(pending_run, tmp_path):
    input_path = tmp_path / "pending.json"
    input_path.write_text(pending_run.model_dump_json())
    assert run_files(input_path, tmp_path / "output") == 0
    assert json.loads((tmp_path / "output" / "ts_records.json").read_text()) == []
    assert len(json.loads((tmp_path / "output" / "review_queue.json").read_text())) == 7


def test_cli_error_findings_return_nonzero_and_remain_reviewable(run, tmp_path):
    changed = update(run, lambda p: p.update(study_id="x" * 41))

    def reapprove(payload):
        for review in payload["decision_reviews"]:
            decision = next(
                d for d in propose(changed) if d.parameter_code == review["parameter_code"]
            )
            review["proposal_sha256"] = proposal_digest(changed, decision)

    changed = update(changed, reapprove)
    input_path = tmp_path / "input.json"
    input_path.write_text(changed.model_dump_json())
    assert run_files(input_path, tmp_path / "output") == 1
    assert any(
        f["code"] == "FIELD_LENGTH"
        for f in json.loads((tmp_path / "output" / "qc.json").read_text())
    )
