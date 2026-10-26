"""Contracts retained after retirement of the synthetic approval application."""

from datetime import UTC, datetime

import pytest
from pydantic import ValidationError

from trial_design_workflow.schemas import Artifact, Evidence, FactReview, SourceDocument, StudyFact
from trial_design_workflow.serialization import canonical_json, sha256


def test_serialization_preserves_existing_canonical_format_and_hash():
    assert canonical_json({"z": "α", "a": [1, None]}) == '{"a":[1,null],"z":"α"}'
    assert canonical_json({"z": 2, "a": 1}) == canonical_json({"a": 1, "z": 2})
    assert sha256(b"abc") == "ba7816bf8f01cfea414140de5dae2223b00361a396177a9cb410ff61f20015ad"


def test_fact_correction_preserves_raw_proposal_and_review_history():
    approved = FactReview(
        reviewer="SIMULATED",
        reviewed_at=datetime(2026, 1, 1, tzinfo=UTC),
        action="approve",
        approved_value="Proposed",
        rationale="Fixture only",
    )
    corrected = FactReview(
        reviewer="SIMULATED",
        reviewed_at=datetime(2026, 1, 2, tzinfo=UTC),
        action="correct",
        approved_value="Corrected",
        rationale="Fixture only",
    )
    fact = StudyFact(
        fact_id="title",
        raw_statement="Original statement",
        proposed_value="Proposed",
        evidence=(
            Evidence(
                document_id="synthetic",
                pdf_page_index=0,
                printed_page="SYN-1",
                quote="Original statement",
                extraction_status="proposed",
            ),
        ),
        reviews=(approved, corrected),
    )
    assert fact.raw_statement == "Original statement"
    assert fact.proposed_value == "Proposed"
    assert fact.approved_value == "Corrected"
    assert len(fact.reviews) == 2
    with pytest.raises(ValidationError, match="chronological"):
        StudyFact.model_validate({**fact.model_dump(), "reviews": [corrected, approved]})


def test_source_document_rejects_non_protocol_artifacts():
    artifact = Artifact(
        artifact_id="test", path="test", sha256="0" * 64, version="synthetic-v1", kind="terminology"
    )
    with pytest.raises(ValidationError, match="protocol artifacts"):
        SourceDocument(artifact=artifact, synthetic=True)
