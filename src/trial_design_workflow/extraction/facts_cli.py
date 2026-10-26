"""Prepare local requests, import saved proposals, and replay facts without network calls."""

import argparse
import json
import platform
import sys
from datetime import UTC, datetime
from pathlib import Path

from pydantic import ValidationError

from .. import __version__
from ..schemas import Artifact, SourceDocument
from ..serialization import canonical_json, sha256
from .facts import (
    PROMPT,
    ProviderFailure,
    RegexFactsProvider,
    SavedResponseProvider,
    assemble_facts,
    digest_model,
    make_request,
)
from .facts_models import (
    ExtractionRequest,
    FactCatalog,
    FactsManifest,
    PreparationManifest,
    ProviderProvenance,
    ProviderResponse,
    StudyFactsV2,
)
from .models import ExtractionRules, ParsedDocument
from .pdf import parse_pdf

ASSETS = Path(__file__).resolve().parent.parent / "assets"
PREPARATION_FILES = {
    "parsed_document.json",
    "fact_catalog.json",
    "extraction_request.json",
    "provider_response.schema.json",
    "provider_response.template.json",
    "prompt.txt",
    "regex_rules.json",
}
RUN_FILES = PREPARATION_FILES | {
    "preparation_manifest.json",
    "provider_response.json",
    "provider.json",
    "study_facts.json",
    "qc_findings.json",
}


def json_bytes(value) -> bytes:
    return (canonical_json(value) + "\n").encode()


def implementation_hashes() -> dict[str, str]:
    package = Path(__file__).resolve().parent.parent
    paths = [
        *Path(__file__).parent.glob("*.py"),
        *(
            package / n
            for n in (
                "schemas.py",
                "serialization.py",
                "__init__.py",
            )
        ),
    ]
    return {p.relative_to(package).as_posix(): sha256(p.read_bytes()) for p in sorted(paths)}


def checked_files(directory: Path, hashes: dict[str, str], required: set[str]) -> dict[str, bytes]:
    if set(hashes) != required:
        raise ValueError("Bundle file inventory is incomplete or unexpected")
    content = {}
    for name, expected in hashes.items():
        if Path(name).name != name or (directory / name).is_symlink():
            raise ValueError("Bundle requires plain files with safe relative names")
        payload = (directory / name).read_bytes()
        if sha256(payload) != expected:
            raise ValueError("Bundle file hash mismatch")
        content[name] = payload
    return content


def write_files(destination: Path, payloads: dict[str, bytes]) -> dict[str, str]:
    destination.mkdir(parents=True, exist_ok=False)
    for name, content in payloads.items():
        with (destination / name).open("xb") as stream:
            stream.write(content)
    return {name: sha256(content) for name, content in sorted(payloads.items())}


def prepare(
    *,
    protocol: Path,
    document_id: str,
    document_version: str,
    expected_sha256: str,
    output: Path,
    catalog: Path,
    pages_per_chunk: int = 3,
    synthetic: bool = False,
) -> Path:
    if output.exists():
        raise ValueError("Output already exists; use a new directory")
    catalog_model = FactCatalog.model_validate_json(catalog.read_bytes())
    source = SourceDocument(
        artifact=Artifact(
            artifact_id=document_id,
            path=protocol.name,
            sha256=expected_sha256,
            version=document_version,
            kind="protocol",
        ),
        synthetic=synthetic,
    )
    document = parse_pdf(protocol.read_bytes(), source)
    request = make_request(document, catalog_model, pages_per_chunk=pages_per_chunk)
    regex_bytes = (ASSETS / "protocol-facts-v1.json").read_bytes()
    frozen = json.loads((ASSETS / "sources.json").read_bytes())
    if sha256(regex_bytes) != frozen["files"]["protocol-facts-v1.json"]:
        raise ValueError("Frozen regex rule hash mismatch")
    payloads = {
        "parsed_document.json": json_bytes(document.model_dump(mode="json")),
        "fact_catalog.json": json_bytes(catalog_model.model_dump(mode="json")),
        "extraction_request.json": json_bytes(request.model_dump(mode="json")),
        "provider_response.schema.json": json_bytes(ProviderResponse.model_json_schema()),
        "provider_response.template.json": json_bytes(
            {
                "schema_version": "2",
                "request_sha256": digest_model(request),
                "proposals": [],
            }
        ),
        "prompt.txt": PROMPT.encode(),
        "regex_rules.json": regex_bytes,
    }
    hashes = write_files(output, payloads)
    manifest = PreparationManifest(
        schema_version="2",
        purpose="local_extraction_preparation",
        document_sha256=expected_sha256,
        files=hashes,
    )
    (output / "preparation_manifest.json").write_bytes(json_bytes(manifest.model_dump(mode="json")))
    return output


def extract_prepared(
    *,
    prepared: Path,
    output: Path,
    provider: str,
    response: Path | None = None,
    provider_name: str | None = None,
    provider_version: str | None = None,
    model_id: str | None = None,
    temperature: float | None = None,
    seed: int | None = None,
    replay_provenance: ProviderProvenance | None = None,
    expected_logical_sha256: str | None = None,
) -> int:
    if output.exists():
        raise ValueError("Output already exists; use a new directory")
    prep_bytes = (prepared / "preparation_manifest.json").read_bytes()
    prep = PreparationManifest.model_validate_json(prep_bytes)
    payloads = checked_files(prepared, prep.files, PREPARATION_FILES)
    document = ParsedDocument.model_validate_json(payloads["parsed_document.json"])
    catalog = FactCatalog.model_validate_json(payloads["fact_catalog.json"])
    request = ExtractionRequest.model_validate_json(payloads["extraction_request.json"])
    if prep.document_sha256 != document.source.artifact.sha256:
        raise ValueError("Preparation document hash mismatch")
    if payloads["prompt.txt"] != PROMPT.encode():
        raise ValueError("Preparation prompt differs from the installed implementation")
    failed = False
    provider_issues = ()
    if provider == "saved-response":
        if response is None or not provider_name or not provider_version:
            raise ValueError("Saved response requires a file, provider name, and provider version")
        response_bytes = response.read_bytes()
        adapter = SavedResponseProvider(response_bytes)
        metadata = dict(
            name=provider_name,
            version=provider_version,
            model_id=model_id,
            method="saved_response",
            acquisition="user_staged_not_verified",
            temperature=temperature,
            seed=seed,
        )
        try:
            proposals = adapter.propose(document, request)
        except ProviderFailure as exc:
            proposals, failed = None, True
            provider_issues = exc.issues
    elif provider == "regex":
        if response is not None or any(
            v is not None
            for v in (
                provider_name,
                provider_version,
                model_id,
                temperature,
                seed,
            )
        ):
            raise ValueError("Regex provider cannot accept AI response or model settings")
        rules = ExtractionRules.model_validate_json(payloads["regex_rules.json"])
        try:
            proposals = RegexFactsProvider(rules).propose(document, request)
        except (ValueError, KeyError):
            proposals, failed = None, True
        response_bytes = json_bytes(proposals.model_dump(mode="json")) if proposals else b"null\n"
        metadata = dict(
            name="regex-baseline", version="1", method="regex", acquisition="local_deterministic"
        )
    else:
        raise ValueError("Unsupported provider; select saved-response or regex")
    provenance = ProviderProvenance(
        response_sha256=sha256(response_bytes),
        prompt_version=request.prompt_version,
        prompt_sha256=request.prompt_sha256,
        **metadata,
    )
    if replay_provenance is not None and provenance != replay_provenance:
        raise ValueError("Replay provider metadata does not match the saved run")
    facts = assemble_facts(
        document,
        catalog,
        request,
        proposals,
        provenance,
        provider_failed=failed,
        provider_issues=provider_issues,
    )
    if expected_logical_sha256 is not None and digest_model(facts) != expected_logical_sha256:
        raise ValueError("Replay logical hash mismatch")
    payloads.update(
        {
            "preparation_manifest.json": prep_bytes,
            "provider_response.json": response_bytes,
            "provider.json": json_bytes(provenance.model_dump(mode="json")),
            "study_facts.json": json_bytes(facts.model_dump(mode="json")),
            "qc_findings.json": json_bytes([f.model_dump(mode="json") for f in facts.findings]),
        }
    )
    hashes = write_files(output, payloads)
    manifest = FactsManifest(
        schema_version="2",
        software_version=__version__,
        python_version=platform.python_version(),
        generated_at=datetime.now(UTC),
        provider_execution="local_regex" if provider == "regex" else "not_performed",
        parser_name=document.parser_name,
        parser_version=document.parser_version,
        parser_settings={
            "strict": "true",
            "extraction_mode": "plain",
            "ocr": "not_used",
            "snapshot": "saved_extracted_text",
            "offset_unit": "unicode_code_point",
        },
        document_sha256=document.source.artifact.sha256,
        files=hashes,
        implementation_sha256=implementation_hashes(),
        logical_study_facts_sha256=digest_model(facts),
    )
    (output / "run_manifest.json").write_bytes(json_bytes(manifest.model_dump(mode="json")))
    return 1 if any(f.severity == "error" for f in facts.findings) else 0


def replay(*, bundle: Path, output: Path) -> int:
    manifest = FactsManifest.model_validate_json((bundle / "run_manifest.json").read_bytes())
    payloads = checked_files(bundle, manifest.files, RUN_FILES)
    if manifest.implementation_sha256 != implementation_hashes():
        raise ValueError(
            "Replay requires the exact saved implementation; use the original checkout"
        )
    if (
        manifest.python_version != platform.python_version()
        or manifest.software_version != __version__
    ):
        raise ValueError("Replay requires the saved Python and package versions")
    provenance = ProviderProvenance.model_validate_json(payloads["provider.json"])
    result = extract_prepared(
        prepared=bundle,
        output=output,
        provider="regex" if provenance.method == "regex" else "saved-response",
        response=bundle / "provider_response.json"
        if provenance.method == "saved_response"
        else None,
        provider_name=provenance.name if provenance.method == "saved_response" else None,
        provider_version=provenance.version if provenance.method == "saved_response" else None,
        model_id=provenance.model_id,
        temperature=provenance.temperature,
        seed=provenance.seed,
        replay_provenance=provenance,
        expected_logical_sha256=manifest.logical_study_facts_sha256,
    )
    return result


def evaluate_bundle(*, bundle: Path, reference: Path, output: Path) -> int:
    from .evaluation import FrozenReference, evaluate

    manifest = FactsManifest.model_validate_json((bundle / "run_manifest.json").read_bytes())
    payloads = checked_files(bundle, manifest.files, RUN_FILES)
    report = evaluate(
        StudyFactsV2.model_validate_json(payloads["study_facts.json"]),
        FrozenReference.model_validate_json(reference.read_bytes()),
        ParsedDocument.model_validate_json(payloads["parsed_document.json"]),
    )
    write_files(output, {"evaluation_report.json": json_bytes(report.model_dump(mode="json"))})
    return 0


def export_schemas(*, output: Path) -> int:
    from .evaluation import FrozenReference

    models = {
        "study-facts-v2.schema.json": StudyFactsV2,
        "provider-response-v2.schema.json": ProviderResponse,
        "study-fact-catalog-v2.schema.json": FactCatalog,
        "facts-reference-v1.schema.json": FrozenReference,
    }
    write_files(
        output, {name: json_bytes(model.model_json_schema()) for name, model in models.items()}
    )
    return 0


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        description="Local Study Facts v2 proposals; no approvals or network calls"
    )
    commands = parser.add_subparsers(dest="command", required=True)
    prep = commands.add_parser("prepare", help="Save page-labelled extraction inputs locally")
    prep.add_argument("--protocol", type=Path, required=True)
    prep.add_argument("--document-id", required=True)
    prep.add_argument("--document-version", required=True)
    prep.add_argument("--expected-sha256", required=True)
    prep.add_argument("--catalog", type=Path, default=ASSETS / "study-fact-catalog-v2.json")
    prep.add_argument("--pages-per-chunk", type=int, default=3)
    prep.add_argument("--synthetic", action="store_true")
    extract = commands.add_parser(
        "extract", help="Validate a saved response or run the regex fallback"
    )
    extract.add_argument("--prepared", type=Path, required=True)
    extract.add_argument("--provider", choices=["saved-response", "regex"], required=True)
    extract.add_argument("--response", type=Path)
    extract.add_argument("--provider-name")
    extract.add_argument("--provider-version")
    extract.add_argument("--model-id")
    extract.add_argument("--temperature", type=float)
    extract.add_argument("--seed", type=int)
    repeat = commands.add_parser("replay", help="Verify a saved bundle and reproduce facts offline")
    repeat.add_argument("--bundle", type=Path, required=True)
    assess = commands.add_parser("evaluate", help="Compare against a frozen reviewed reference")
    assess.add_argument("--bundle", type=Path, required=True)
    assess.add_argument("--reference", type=Path, required=True)
    schemas = commands.add_parser("schemas", help="Export the generated boundary JSON Schemas")
    for command in (prep, extract, repeat, assess, schemas):
        command.add_argument("--output", type=Path, required=True)
    args = vars(parser.parse_args(argv))
    command = args.pop("command")
    try:
        if command == "prepare":
            prepare(**args)
            status = 0
        elif command == "extract":
            status = extract_prepared(**args)
        elif command == "replay":
            status = replay(**args)
        elif command == "evaluate":
            status = evaluate_bundle(**args)
        else:
            status = export_schemas(**args)
    except (OSError, ValueError, ValidationError):
        # Do not print exception messages/validation inputs: they may contain protocol text.
        print(
            json.dumps(
                {
                    "code": "FACTS_INPUT_ERROR",
                    "severity": "error",
                    "status": "open",
                    "message": (
                        "Invalid/unavailable input, hash/version mismatch, or existing output. "
                        "Check saved inputs and use a new output directory."
                    ),
                }
            ),
            file=sys.stderr,
        )
        return 2
    print("Local Study Facts artifacts written; all proposals require human review.")
    return status
