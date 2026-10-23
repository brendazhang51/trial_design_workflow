"""Local PDF-to-fact review bundles. No TS generation, approvals or network calls."""

import argparse
import json
import platform
import sys
from datetime import UTC, datetime
from pathlib import Path

from pydantic import ValidationError

from .. import __version__
from ..engine import canonical_json, sha256
from ..schemas import Artifact, SourceDocument
from .core import extract_facts
from .models import ExtractionManifest, ExtractionRules
from .pdf import parse_pdf


def extract_files(
    pdf_path: Path,
    rules_path: Path,
    output_path: Path,
    *,
    document_id: str,
    document_version: str,
    expected_sha256: str,
    synthetic: bool,
) -> int:
    # Pin input bytes before parsing so hashing and extraction use identical content.
    pdf_bytes, rule_bytes = pdf_path.read_bytes(), rules_path.read_bytes()
    rules = ExtractionRules.model_validate_json(rule_bytes)
    source = SourceDocument(
        artifact=Artifact(
            artifact_id=document_id,
            path=str(pdf_path.resolve()),
            sha256=expected_sha256,
            version=document_version,
            kind="protocol",
        ),
        synthetic=synthetic,
    )
    document = parse_pdf(pdf_bytes, source)
    output = extract_facts(document, rules)
    output_path.mkdir(parents=True, exist_ok=False)
    payloads = {
        "extraction.json": output.model_dump(mode="json"),
        "facts.json": [c.fact.model_dump(mode="json") for c in output.candidates],
        "review_queue.json": [r.model_dump(mode="json") for r in output.review_queue],
        "qc.json": [f.model_dump(mode="json") for f in output.findings],
    }
    outputs = []
    for name, payload in payloads.items():
        content = (canonical_json(payload) + "\n").encode()
        (output_path / name).write_bytes(content)
        outputs.append(
            Artifact(
                artifact_id=name, path=name, sha256=sha256(content), version="1", kind="output"
            )
        )
    inputs = [
        source.artifact,
        Artifact(
            artifact_id="extraction-rules",
            path=str(rules_path.resolve()),
            sha256=sha256(rule_bytes),
            version=rules.version,
            kind="rule",
        ),
    ]
    # Hash executable interpretation code as well as the declarative extraction rules.
    package = Path(__file__).parent.parent
    for path in sorted(
        [
            *Path(__file__).parent.glob("*.py"),
            package / "schemas.py",
            package / "engine.py",
            package / "__init__.py",
        ]
    ):
        name = path.relative_to(package).as_posix()
        inputs.append(
            Artifact(
                artifact_id="implementation:" + name,
                path=str(path.resolve()),
                sha256=sha256(path.read_bytes()),
                version=__version__,
                kind="input",
            )
        )
    manifest = ExtractionManifest(
        schema_version="1",
        software_version=__version__,
        generated_at=datetime.now(UTC),
        purpose="fact_proposals_for_human_review",
        standards_status="not_loaded",
        parser_name=document.parser_name,
        parser_version=document.parser_version,
        parser_settings={
            "strict": "true",
            "extraction_mode": "plain",
            "ocr": "not_used",
            "model_provider": "not_used",
            "cross_page": rules.cross_page_policy,
        },
        provider_name=output.provider_name,
        provider_version=output.provider_version,
        python_version=platform.python_version(),
        inputs=tuple(inputs),
        outputs=tuple(outputs),
        logical_extraction_sha256=sha256(canonical_json(payloads["extraction.json"]).encode()),
    )
    (output_path / "manifest.json").write_text(manifest.model_dump_json(indent=2) + "\n")
    return 1 if any(f.severity == "error" for f in output.findings) else 0


def main() -> int:
    parser = argparse.ArgumentParser(
        description="Extract unapproved, evidence-grounded protocol facts"
    )
    parser.add_argument("--pdf", type=Path, required=True)
    parser.add_argument("--rules", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--document-id", required=True)
    parser.add_argument(
        "--document-version",
        required=True,
        help="Supplied source metadata, not an extracted or verified protocol fact",
    )
    parser.add_argument("--expected-sha256", required=True)
    parser.add_argument("--synthetic", action="store_true")
    args = parser.parse_args()
    try:
        status = extract_files(
            args.pdf,
            args.rules,
            args.output,
            document_id=args.document_id,
            document_version=args.document_version,
            expected_sha256=args.expected_sha256,
            synthetic=args.synthetic,
        )
    except ValidationError as exc:
        findings = [
            {
                "code": "INVALID_EXTRACTION_INPUT",
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
                        "code": "EXTRACTION_ERROR",
                        "severity": "error",
                        "status": "open",
                        "message": str(exc),
                    }
                ]
            ),
            file=sys.stderr,
        )
        return 2
    print(f"Fact review bundle written to {args.output}; all candidates require human review.")
    return status


if __name__ == "__main__":
    raise SystemExit(main())
