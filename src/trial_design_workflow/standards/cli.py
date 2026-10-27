"""Additive maintenance CLI; normal workbook generation remains compatible."""

import argparse
import json
import sys
from pathlib import Path

from pydantic import ValidationError

from .legacy import build_legacy_profile
from .models import StandardsProfile
from .profile import (
    ProfileError,
    build_profile,
    inspect_profile,
    load_profile,
    semantic_diff,
)
from .review import ReviewContent, export_review, initialize_content, validate_content


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Offline Master Lookup profile maintenance")
    commands = parser.add_subparsers(dest="command", required=True)
    validate = commands.add_parser("validate")
    selected = validate.add_mutually_exclusive_group(required=True)
    selected.add_argument("--profile", type=Path)
    selected.add_argument(
        "--active-profile", type=Path, help="Explicit hash-pinned active selection"
    )
    validate.add_argument("--allow-draft-standards", action="store_true")
    validate.add_argument("--content", type=Path, help="Also enforce content-readiness gates")
    build = commands.add_parser("build")
    build.add_argument(
        "--spec",
        type=Path,
        required=True,
        help="Schema-v2 profile JSON with sources relative to the spec directory",
    )
    build.add_argument("--output", type=Path, required=True)
    diff = commands.add_parser("diff")
    diff.add_argument("--before", type=Path, required=True)
    diff.add_argument("--after", type=Path, required=True)
    diff.add_argument("--allow-draft-standards", action="store_true")
    seed = commands.add_parser("seed-legacy")
    seed.add_argument("--assets", type=Path, required=True)
    seed.add_argument("--staging", type=Path, required=True)
    seed.add_argument("--output", type=Path, required=True)
    commands.add_parser("schema")
    commands.add_parser("content-schema")
    promote = commands.add_parser("promote")
    promote.add_argument("--bundle", type=Path, required=True)
    promote.add_argument("--approval", type=Path, required=True)
    promote.add_argument("--output", type=Path, required=True)
    for name in ("review-init", "review-export"):
        review = commands.add_parser(name)
        review.add_argument("--profile", type=Path, required=True)
        review.add_argument("--allow-draft-standards", action="store_true")
        review.add_argument("--output", type=Path, required=True)
        if name == "review-export":
            review.add_argument("--content", type=Path, required=True)
    inventory = commands.add_parser("sources-inventory")
    inventory.add_argument("--directory", type=Path, required=True)
    inventory.add_argument("--output", type=Path, required=True)
    clinical = commands.add_parser("stage-clinical")
    clinical.add_argument("--spec", type=Path, required=True)
    clinical.add_argument("--source-root", type=Path, required=True)
    clinical.add_argument("--output", type=Path, required=True)
    clinical.add_argument(
        "--before", type=Path, help="Optional immutable profile for semantic diff"
    )
    args = parser.parse_args(argv)
    try:
        if args.command == "promote":
            from .approval import promote_bundle

            destination = promote_bundle(args.bundle, args.approval, args.output)
            print(json.dumps({"output": str(destination), "status": "approved_for_mvp"}))
            return 0
        if args.command == "validate":
            if args.active_profile:
                from .approval import resolve_active_profile

                bundle = resolve_active_profile(args.active_profile, Path.cwd())
                args.profile = bundle / "profile"
                args.content = bundle / "content.json"
            report = inspect_profile(args.profile, allow_draft=args.allow_draft_standards)
            if args.content and report.valid:
                profile = load_profile(args.profile, allow_draft=args.allow_draft_standards)
                content = ReviewContent.model_validate_json(args.content.read_bytes())
                report = validate_content(profile, content)
            print(report.model_dump_json(indent=2))
            return 0 if report.valid else 1
        if args.command in {"review-init", "review-export"}:
            profile = load_profile(args.profile, allow_draft=args.allow_draft_standards)
            if args.command == "review-init":
                content = initialize_content(profile)
                args.output.parent.mkdir(parents=True, exist_ok=True)
                with args.output.open("x") as stream:
                    stream.write(content.model_dump_json(indent=2) + "\n")
            else:
                content = ReviewContent.model_validate_json(args.content.read_bytes())
                export_review(profile, content, args.output)
            print(json.dumps({"output": str(args.output), "review_only": True}))
        elif args.command == "sources-inventory":
            from .review import inventory_sources

            payload = inventory_sources(args.directory)
            args.output.parent.mkdir(parents=True, exist_ok=True)
            with args.output.open("x") as stream:
                stream.write(json.dumps(payload, indent=2, ensure_ascii=False) + "\n")
            print(json.dumps({"output": str(args.output), "selected_for_clinical_use": False}))
        elif args.command == "stage-clinical":
            from .clinical import ClinicalBuildSpec, build_clinical_review

            spec = ClinicalBuildSpec.model_validate_json(args.spec.read_bytes())
            before = load_profile(args.before, allow_draft=True) if args.before else None
            destination = build_clinical_review(
                spec, args.source_root, args.output, before, policy_root=args.spec.parent
            )
            print(json.dumps({"output": str(destination), "status": "draft", "review_only": True}))
        elif args.command == "content-schema":
            print(json.dumps(ReviewContent.model_json_schema(), indent=2, sort_keys=True))
        elif args.command == "build":
            profile = StandardsProfile.model_validate_json(args.spec.read_bytes())
            destination = build_profile(profile, args.spec.parent, args.output)
            print(json.dumps({"profile": str(destination), "status": profile.manifest.status}))
        elif args.command == "diff":
            before = load_profile(args.before, allow_draft=args.allow_draft_standards)
            after = load_profile(args.after, allow_draft=args.allow_draft_standards)
            print(json.dumps(semantic_diff(before, after), indent=2, ensure_ascii=False))
        elif args.command == "seed-legacy":
            destination = build_legacy_profile(args.assets, args.staging, args.output)
            print(json.dumps({"profile": str(destination), "status": "draft"}))
        else:
            print(json.dumps(StandardsProfile.model_json_schema(), indent=2, sort_keys=True))
    except ProfileError as exc:
        print(exc.report.model_dump_json(indent=2), file=sys.stderr)
        return 1
    except (OSError, ValueError, KeyError, TypeError, ValidationError) as exc:
        print(
            json.dumps(
                {
                    "code": "STANDARDS_COMMAND_ERROR",
                    "error_type": type(exc).__name__,
                    "message": "Check the profile specification, hashes and new output path.",
                }
            ),
            file=sys.stderr,
        )
        return 2
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
