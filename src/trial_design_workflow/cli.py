"""JSON-only Milestone 1 adapter. Existing run directories are never overwritten."""

import argparse
import json
import sys
from datetime import UTC, datetime
from pathlib import Path

from pydantic import ValidationError

from . import __version__
from .engine import canonical_json, generate, proposal_digest, sha256, validate_output
from .schemas import Artifact, Manifest, RunInput


def run_files(input_path: Path, output_path: Path) -> int:
    input_bytes = input_path.read_bytes()
    run = RunInput.model_validate_json(input_bytes)
    artifacts = (
        *(d.artifact for d in run.documents),
        run.registry.artifact,
        *run.registry.rule_artifacts,
        run.terminology.artifact,
    )
    for artifact in artifacts:
        source_path = input_path.parent / artifact.path
        if sha256(source_path.read_bytes()) != artifact.sha256:
            raise ValueError(
                f"Hash mismatch for {artifact.artifact_id}; restore or re-pin the input"
            )
    registry_source = json.loads((input_path.parent / run.registry.artifact.path).read_bytes())
    selected_registry = run.registry.model_dump(mode="json", exclude={"artifact", "rule_artifacts"})
    if registry_source != selected_registry:
        raise ValueError("Selected registry differs from its pinned source artifact")
    terminology_source = json.loads(
        (input_path.parent / run.terminology.artifact.path).read_bytes()
    )
    if terminology_source != {"terms": run.terminology.model_dump(mode="json")["terms"]}:
        raise ValueError("Selected terminology differs from its pinned source artifact")
    output = generate(run)
    qc = validate_output(run, output)
    # mkdir without exist_ok prevents accidental overwrites of prior audit runs.
    output_path.mkdir(parents=True, exist_ok=False)
    payloads = {
        "run_input.json": run.model_dump(mode="json"),
        "review_queue.json": [
            {"proposal": d.model_dump(mode="json"), "proposal_sha256": proposal_digest(run, d)}
            for d in output.proposals
        ],
        "ts_records.json": [r.model_dump(mode="json") for r in output.records],
        "traceability.json": [t.model_dump(mode="json") for t in output.traceability],
        "qc.json": [f.model_dump(mode="json") for f in (*output.findings, *qc)],
    }
    output_artifacts = []
    for name, payload in payloads.items():
        content = (canonical_json(payload) + "\n").encode()
        (output_path / name).write_bytes(content)
        output_artifacts.append(
            Artifact(
                artifact_id=name,
                path=name,
                sha256=sha256(content),
                version=__version__,
                kind="output",
            )
        )
    manifest = Manifest(
        software_version=__version__,
        generated_at=datetime.now(UTC),
        mode="synthetic_test_only",
        standards_status="not_loaded",
        inputs=(
            Artifact(
                artifact_id="run_input",
                path=str(input_path.resolve()),
                sha256=sha256(input_bytes),
                version="1",
                kind="input",
            ),
            *artifacts,
        ),
        outputs=tuple(output_artifacts),
        logical_records_sha256=sha256(canonical_json(payloads["ts_records.json"]).encode()),
    )
    (output_path / "manifest.json").write_text(manifest.model_dump_json(indent=2) + "\n")
    return 1 if any(f.severity == "error" for f in (*output.findings, *qc)) else 0


def main() -> int:
    parser = argparse.ArgumentParser(description="Generate a synthetic TS foundation review bundle")
    parser.add_argument("--input", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    try:
        status = run_files(args.input, args.output)
    except ValidationError as exc:
        # Avoid echoing confidential values that may have been accidentally supplied.
        findings = [
            {
                "code": "INVALID_INPUT",
                "severity": "error",
                "status": "open",
                "location": list(e["loc"]),
                "message": e["msg"],
            }
            for e in exc.errors(include_input=False, include_url=False)
        ]
        print(json.dumps(findings), file=sys.stderr)
        return 2
    except (OSError, ValueError) as exc:
        print(
            json.dumps(
                [
                    {
                        "code": "INPUT_OR_OUTPUT_ERROR",
                        "severity": "error",
                        "status": "open",
                        "message": str(exc),
                    }
                ]
            ),
            file=sys.stderr,
        )
        return 2
    print(f"Review bundle written to {args.output}; inspect qc.json and review_queue.json.")
    return status


if __name__ == "__main__":
    raise SystemExit(main())
