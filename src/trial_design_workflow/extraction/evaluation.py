"""Offline extraction metrics against a separately supplied, frozen reviewed reference."""

from datetime import datetime
from typing import Literal, Self

from pydantic import Field, model_validator

from ..schemas import Digest, Model, Text
from ..serialization import canonical_json
from .facts import digest_model, evidence_errors
from .facts_models import FactEvidence, FactKey, FactProposal, StudyFactsV2
from .models import ParsedDocument


class ReferenceFact(Model):
    fact_key: FactKey
    cardinality_key: dict[FactKey, Text] = Field(default_factory=dict)
    raw_value: Text
    normalized_value: Text
    unit: Text | None = None
    evidence: tuple[FactEvidence, ...] = Field(min_length=1)


class FrozenReference(Model):
    schema_version: Literal["1"]
    reference_id: Text
    document_sha256: Digest
    synthetic: bool
    reviewer_id: Text
    frozen_at: datetime
    evaluation_role: Literal["development", "held_out", "post_evaluation_regression"]
    fully_reviewed_fact_keys: tuple[FactKey, ...] = Field(min_length=1)
    facts: tuple[ReferenceFact, ...]

    @model_validator(mode="after")
    def reviewed_scope(self) -> Self:
        if self.frozen_at.tzinfo is None:
            raise ValueError("reference freeze timestamp requires a timezone")
        if len(set(self.fully_reviewed_fact_keys)) != len(self.fully_reviewed_fact_keys):
            raise ValueError("duplicate reviewed fact keys")
        values = [canonical_json(f.model_dump(mode="json")) for f in self.facts]
        if len(values) != len(set(values)):
            raise ValueError("duplicate reference facts")
        if any(f.fact_key not in self.fully_reviewed_fact_keys for f in self.facts):
            raise ValueError("reference facts must belong to the fully reviewed scope")
        return self


class ExtractionMetrics(Model):
    expected_identities: int
    predicted_identities: int
    matching_identities: int
    exact_value_identities: int
    precision: float | None
    recall: float | None
    value_accuracy: float | None


class EvaluationReport(Model):
    schema_version: Literal["1"]
    reference_sha256: Digest
    study_facts_sha256: Digest
    reference_id: Text
    synthetic: bool
    evaluation_role: Literal["development", "held_out", "post_evaluation_regression"]
    metrics_by_fact_key: dict[FactKey, ExtractionMetrics]
    evidence_grounding_pass_rate: float | None
    applicability_precision: None = None
    applicability_recall: None = None
    terminology_accuracy: None = None
    auto_acceptance_rate: Literal[0] = 0
    erroneous_auto_acceptance_rate: None = None
    limitations: tuple[Text, ...]


def evaluate(
    facts: StudyFactsV2, reference: FrozenReference, document: ParsedDocument
) -> EvaluationReport:
    facts = StudyFactsV2.model_validate_json(facts.model_dump_json())
    reference = FrozenReference.model_validate_json(reference.model_dump_json())
    if (
        reference.document_sha256 != facts.document_sha256
        or reference.document_sha256 != document.source.artifact.sha256
    ):
        raise ValueError("Reference and extraction document hashes differ")
    if reference.synthetic != document.source.synthetic:
        raise ValueError("Reference and document synthetic flags differ")
    expected, predicted = {}, {}
    for fact in reference.facts:
        check = FactProposal(
            fact_key=fact.fact_key,
            cardinality_key=fact.cardinality_key,
            status="proposed",
            raw_value=fact.raw_value,
            unit=fact.unit,
            evidence=fact.evidence,
            explanation="Separately supplied reviewed evaluation reference.",
        )
        if evidence_errors(check, document):
            raise ValueError("Reference evidence does not match the saved document")
        identity = canonical_json(fact.cardinality_key)
        expected.setdefault(fact.fact_key, {}).setdefault(identity, set()).add(
            (fact.normalized_value, fact.unit)
        )
    for fact in facts.facts:
        for observation in fact.observations:
            if observation.proposal.raw_value is None:
                continue
            if evidence_errors(observation.proposal, document):
                raise ValueError("Study Facts evidence does not match the saved document")
            identity = canonical_json(fact.cardinality_key)
            predicted.setdefault(fact.fact_key, {}).setdefault(identity, set()).add(
                (observation.normalized_proposal, observation.proposal.unit)
            )
    metrics = {}
    for key in sorted(reference.fully_reviewed_fact_keys):
        gold, proposals = expected.get(key, {}), predicted.get(key, {})
        matching = set(gold) & set(proposals)
        exact = sum(gold[k] == proposals[k] for k in matching)
        metrics[key] = ExtractionMetrics(
            expected_identities=len(gold),
            predicted_identities=len(proposals),
            matching_identities=len(matching),
            exact_value_identities=exact,
            precision=len(matching) / len(proposals) if proposals else None,
            recall=len(matching) / len(gold) if gold else None,
            value_accuracy=exact / len(matching) if matching else None,
        )
    grounded = sum(o.proposal.raw_value is not None for f in facts.facts for o in f.observations)
    ungrounded = sum(r.proposal.raw_value is not None for r in facts.rejected_proposals)
    return EvaluationReport(
        schema_version="1",
        reference_sha256=digest_model(reference),
        study_facts_sha256=digest_model(facts),
        reference_id=reference.reference_id,
        synthetic=reference.synthetic,
        evaluation_role=reference.evaluation_role,
        metrics_by_fact_key=metrics,
        evidence_grounding_pass_rate=grounded / (grounded + ungrounded)
        if grounded + ungrounded
        else None,
        limitations=(
            "Precision/recall measure fact/cardinality discovery within the reviewed scope.",
            "Value accuracy compares exact normalized value/unit sets for matching identities.",
            "Evidence pass rate counts validated non-null observations across the run.",
            "Applicability, terminology, approvals and production accuracy are not evaluated.",
            "Review/freeze metadata are supplied declarations; no approvals are imported.",
        ),
    )
