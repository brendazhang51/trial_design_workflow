"""Offline selection/generation commands. JSON input, explicit versions, no workbook mutation."""

import argparse
import json
import platform
import sys
from datetime import UTC, datetime
from pathlib import Path
from typing import Literal

from . import __version__
from .extraction.facts_cli import RUN_FILES, checked_files
from .extraction.facts_models import FactsManifest, StudyFactsV2
from .extraction.models import ParsedDocument
from .generation import TSGeneration, generate_ts
from .schemas import Digest, Model, Text
from .selection import ParameterSelection, RuntimeProfile, load_runtime, select_parameters
from .serialization import canonical_json, sha256
from .standards.approval import resolve_active_profile
from .standards.profile import safe_path
from .study_context import (
    CuratedInputs,
    StudyContext,
    digest,
    from_proposals,
    normalize_context,
    read_curated,
)


class ProcessingManifest(Model):
    schema_version: Literal["1"]
    stage: Literal["select", "generate"]
    generated_at: datetime
    software_version: Text
    python_version: Text
    network_used: Literal[False] = False
    allow_draft_standards: bool
    input_hashes: dict[Text, Digest]
    source_artifact_hashes: dict[Text, Digest]
    implementation_sha256: dict[Text, Digest]
    files: dict[Text, Digest]
    logical_selection_sha256: Digest
    logical_generation_sha256: Digest | None


def json_bytes(value):
    return (canonical_json(value) + "\n").encode()


def implementation_hashes():
    package = Path(__file__).parent
    return {
        p.relative_to(package).as_posix(): sha256(p.read_bytes())
        for p in sorted(package.rglob("*.py"))
        if "__pycache__" not in p.parts
    }


def load_context(path: Path, *, source_root: Path | None = None, study_id: str | None = None):
    content = path.read_bytes()
    payload = json.loads(content)
    purpose = payload.get("purpose")
    if purpose == "human_curated_study_inputs":
        context = read_curated(
            CuratedInputs.model_validate_json(content), source_root or path.parent
        )
    elif purpose == "validated_study_context":
        context = normalize_context(StudyContext.model_validate_json(content))
    elif purpose == "unapproved_study_fact_proposals":
        if not study_id:
            raise ValueError("Step 1 proposals require an explicitly supplied study ID")
        manifest = FactsManifest.model_validate_json(
            (path.parent / "run_manifest.json").read_bytes()
        )
        files = checked_files(path.parent, manifest.files, RUN_FILES)
        if sha256(content) != manifest.files.get(path.name):
            raise ValueError("Step 1 facts are not bound to the saved bundle")
        document = ParsedDocument.model_validate_json(files["parsed_document.json"])
        context = from_proposals(StudyFactsV2.model_validate_json(content), document, study_id)
    else:
        raise ValueError("Unsupported facts contract")
    if study_id and study_id != context.study_id:
        raise ValueError("Study identifier differs from saved inputs")
    return context


def write_bundle(context, runtime, selection, generation, output, *, allow_draft, input_hashes):
    stage = "generate" if generation is not None else "select"
    payloads = {
        "study_context.json": json_bytes(context.model_dump(mode="json")),
        "runtime_profile.json": json_bytes(runtime.model_dump(mode="json")),
        "parameter_selection.json": json_bytes(selection.model_dump(mode="json")),
        "qc_findings.json": json_bytes(
            [
                f.model_dump(mode="json")
                for f in (generation.findings if generation else selection.findings)
            ]
        ),
    }
    if generation is not None:
        payloads.update(
            {
                "ts_generation.json": json_bytes(generation.model_dump(mode="json")),
                "ts_records.json": json_bytes(
                    [r.model_dump(mode="json") for r in generation.records]
                ),
                "record_trace.json": json_bytes(
                    [t.model_dump(mode="json") for t in generation.trace]
                ),
            }
        )
    manifest = ProcessingManifest(
        schema_version="1",
        stage=stage,
        generated_at=datetime.now(UTC),
        software_version=__version__,
        python_version=platform.python_version(),
        allow_draft_standards=allow_draft,
        input_hashes=input_hashes,
        source_artifact_hashes={
            **{"standards:" + s.source_id: s.sha256 for s in runtime.profile.sources},
            **{"study:" + s.source_id: s.sha256 for s in context.sources},
        },
        implementation_sha256=implementation_hashes(),
        files={k: sha256(v) for k, v in sorted(payloads.items())},
        logical_selection_sha256=digest(selection),
        logical_generation_sha256=digest(generation) if generation else None,
    )
    output.mkdir(parents=True, exist_ok=False)
    for name, content in sorted(payloads.items()):
        with (output / name).open("xb") as stream:
            stream.write(content)
    (output / "run_manifest.json").write_bytes(json_bytes(manifest.model_dump(mode="json")))
    findings = generation.findings if generation else selection.findings
    return 1 if any(f.blocking for f in findings) else 0


def run_stage(
    *,
    stage: str,
    facts: Path,
    output: Path,
    profile: Path | None = None,
    active_profile: Path | None = None,
    runtime_profile: Path | None = None,
    selection: Path | None = None,
    source_root: Path | None = None,
    study_id: str | None = None,
    allow_draft_standards=False,
):
    if stage not in {"select", "generate"}:
        raise ValueError("Unsupported deterministic stage")
    if output.exists():
        raise ValueError("Output already exists")
    if sum(v is not None for v in (profile, active_profile, runtime_profile)) != 1:
        raise ValueError("Select exactly one explicit standards input")
    if active_profile:
        if profile:
            raise ValueError("Select exactly one profile source")
        profile = resolve_active_profile(active_profile, Path.cwd()) / "profile"
    if runtime_profile:
        runtime = RuntimeProfile.model_validate_json(runtime_profile.read_bytes())
    else:
        runtime = load_runtime(profile, allow_draft=allow_draft_standards)
    context = load_context(facts, source_root=source_root, study_id=study_id)
    proposed = select_parameters(context, runtime, allow_draft=allow_draft_standards)
    input_hashes = {"facts": sha256(facts.read_bytes())}
    if runtime_profile:
        input_hashes["runtime_profile"] = sha256(runtime_profile.read_bytes())
    generation = None
    if stage == "generate":
        if selection is None:
            raise ValueError("Generation requires saved parameter selection")
        saved = ParameterSelection.model_validate_json(selection.read_bytes())
        generation = generate_ts(context, saved, runtime, allow_draft=allow_draft_standards)
        input_hashes["selection"] = sha256(selection.read_bytes())
    return write_bundle(
        context,
        runtime,
        proposed,
        generation,
        output,
        allow_draft=allow_draft_standards,
        input_hashes=input_hashes,
    )


def replay(*, manifest: Path, output: Path):
    if output.exists():
        raise ValueError("Output already exists")
    saved = ProcessingManifest.model_validate_json(manifest.read_bytes())
    expected = {
        "study_context.json",
        "runtime_profile.json",
        "parameter_selection.json",
        "qc_findings.json",
    }
    if saved.stage == "generate":
        expected |= {"ts_generation.json", "ts_records.json", "record_trace.json"}
    if set(saved.files) != expected:
        raise ValueError("Invalid stage bundle inventory")
    root = manifest.parent
    actual = {p.relative_to(root).as_posix() for p in root.rglob("*") if p.is_file()}
    if actual != expected | {manifest.name}:
        raise ValueError("Uninventoried stage files")
    for name, expected_hash in saved.files.items():
        if sha256(safe_path(root, name).read_bytes()) != expected_hash:
            raise ValueError("Stage bundle hash mismatch")
    if (
        saved.implementation_sha256 != implementation_hashes()
        or saved.software_version != __version__
        or saved.python_version != platform.python_version()
    ):
        raise ValueError("Replay requires the saved implementation and runtime versions")
    context = normalize_context(
        StudyContext.model_validate_json((root / "study_context.json").read_bytes())
    )
    runtime = RuntimeProfile.model_validate_json((root / "runtime_profile.json").read_bytes())
    source_hashes = {
        **{"standards:" + s.source_id: s.sha256 for s in runtime.profile.sources},
        **{"study:" + s.source_id: s.sha256 for s in context.sources},
    }
    if source_hashes != saved.source_artifact_hashes:
        raise ValueError("Source provenance ledger differs from the saved snapshots")
    selection = select_parameters(context, runtime, allow_draft=saved.allow_draft_standards)
    if digest(selection) != saved.logical_selection_sha256:
        raise ValueError("Selection replay differs")
    generation = None
    if saved.stage == "generate":
        generation = generate_ts(
            context, selection, runtime, allow_draft=saved.allow_draft_standards
        )
        if digest(generation) != saved.logical_generation_sha256:
            raise ValueError("TS replay differs")
    return write_bundle(
        context,
        runtime,
        selection,
        generation,
        output,
        allow_draft=saved.allow_draft_standards,
        input_hashes=saved.input_hashes,
    )


def export_schemas(output: Path):
    models = {
        "curated-study-inputs-v1.schema.json": CuratedInputs,
        "study-context-v1.schema.json": StudyContext,
        "parameter-selection-v1.schema.json": ParameterSelection,
        "ts-generation-v1.schema.json": TSGeneration,
    }
    payloads = {name: json_bytes(model.model_json_schema()) for name, model in models.items()}
    output.mkdir(parents=True, exist_ok=False)
    for name, content in payloads.items():
        with (output / name).open("xb") as stream:
            stream.write(content)
    return 0


def main(stage: str, argv: list[str] | None = None):
    parser = argparse.ArgumentParser(
        description="Offline deterministic " + stage + "; outputs remain draft proposals"
    )
    parser.add_argument("--output", type=Path, required=True)
    if stage == "schemas":
        pass
    elif stage == "replay":
        parser.add_argument("--manifest", type=Path, required=True)
    else:
        parser.add_argument("--facts", type=Path, required=True)
        selected = parser.add_mutually_exclusive_group(required=True)
        selected.add_argument("--profile", type=Path)
        selected.add_argument("--active-profile", type=Path)
        selected.add_argument(
            "--runtime-profile", type=Path, help="Saved validated runtime-profile snapshot"
        )
        parser.add_argument("--source-root", type=Path)
        parser.add_argument("--study-id")
        parser.add_argument("--allow-draft-standards", action="store_true")
        if stage == "generate":
            parser.add_argument("--selection", type=Path, required=True)
    args = vars(parser.parse_args(argv))
    try:
        if stage == "schemas":
            status = export_schemas(**args)
        elif stage == "replay":
            status = replay(**args)
        else:
            status = run_stage(stage=stage, **args)
    except (OSError, ValueError, TypeError, KeyError, IndexError):
        print(
            json.dumps(
                {
                    "code": "DETERMINISTIC_STAGE_INPUT_ERROR",
                    "severity": "error",
                    "message": (
                        "Invalid inputs, evidence, profile, decision, hashes, or output path. "
                        "Inspect saved contracts and use a new output directory."
                    ),
                }
            ),
            file=sys.stderr,
        )
        return 2
    print(
        "Wrote local deterministic-stage artifacts. Review the saved findings and draft proposals."
    )
    return status
