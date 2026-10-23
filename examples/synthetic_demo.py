"""Create a synthetic input bundle; all reviewer actions here are simulated fixtures.

Run with --approved-demo to simulate decision approvals, never for real studies.
The actual generation CLI never approves facts or decisions automatically.
"""

import argparse
import json
from datetime import UTC, datetime
from pathlib import Path

from trial_design_workflow.engine import proposal_digest, propose, sha256
from trial_design_workflow.schemas import (
    Artifact,
    DecisionReview,
    Evidence,
    FactReview,
    Registry,
    RunInput,
    SourceDocument,
    StudyFact,
    Terminology,
)

ASSETS = Path(__file__).parent / "synthetic"
REVIEW_TIME = datetime(2026, 1, 1, tzinfo=UTC)


def artifact(name: str, kind: str, artifact_id: str) -> Artifact:
    path = (ASSETS / name).resolve()
    return Artifact(
        artifact_id=artifact_id,
        path=str(path),
        sha256=sha256(path.read_bytes()),
        version="synthetic-v1",
        kind=kind,
    )


def synthetic_input(approved: bool = False) -> RunInput:
    registry = Registry.model_validate(
        {
            **json.loads((ASSETS / "registry-v1.json").read_text()),
            "artifact": artifact("registry-v1.json", "registry", "synthetic-registry-v1"),
            "rule_artifacts": [artifact("rules-v1.md", "rule", "synthetic-rules-v1")],
        }
    )
    terminology = Terminology.model_validate(
        {
            **json.loads((ASSETS / "terms-v1.json").read_text()),
            "synthetic": True,
            "artifact": artifact("terms-v1.json", "terminology", "synthetic-terms-v1"),
        }
    )
    facts = []
    for fact_id, value, sentence in (
        ("title", "Example Study", "The fictional study title is Example Study."),
        ("design", "EXAMPLE PARALLEL", "The fictional design category is EXAMPLE PARALLEL."),
    ):
        facts.append(
            StudyFact(
                fact_id=fact_id,
                raw_statement=sentence,
                proposed_value=value,
                evidence=(
                    Evidence(
                        document_id="synthetic-protocol-v1",
                        pdf_page_index=0,
                        printed_page="SYN-1",
                        quote=sentence,
                        extraction_status="reviewed",
                    ),
                ),
                reviews=(
                    FactReview(
                        reviewer="SIMULATED_FIXTURE_REVIEWER",
                        reviewed_at=REVIEW_TIME,
                        action="approve",
                        approved_value=value,
                        rationale="Simulated fact review for engineering tests only.",
                    ),
                ),
            )
        )
    run = RunInput(
        study_id="SYNTHETIC-001",
        facts=tuple(facts),
        registry=registry,
        terminology=terminology,
        documents=(
            SourceDocument(
                artifact=artifact("protocol-v1.txt", "protocol", "synthetic-protocol-v1"),
                synthetic=True,
            ),
        ),
    )
    if approved:
        payload = run.model_dump(mode="json")
        payload["decision_reviews"] = [
            DecisionReview(
                parameter_code=d.parameter_code,
                proposal_sha256=proposal_digest(run, d),
                reviewer="SIMULATED_FIXTURE_REVIEWER",
                reviewed_at=REVIEW_TIME,
                action="approve",
                rationale="Simulated decision approval for engineering tests only.",
            ).model_dump(mode="json")
            for d in propose(run)
        ]
        run = RunInput.model_validate(payload)
    return run


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--approved-demo", action="store_true")
    args = parser.parse_args()
    args.output.parent.mkdir(parents=True, exist_ok=True)
    with args.output.open("x") as target:
        target.write(synthetic_input(args.approved_demo).model_dump_json(indent=2) + "\n")


if __name__ == "__main__":
    main()
