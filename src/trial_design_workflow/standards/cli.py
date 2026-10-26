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


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Offline Master Lookup profile maintenance")
    commands = parser.add_subparsers(dest="command", required=True)
    validate = commands.add_parser("validate")
    validate.add_argument("--profile", type=Path, required=True)
    validate.add_argument("--allow-draft-standards", action="store_true")
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
    args = parser.parse_args(argv)
    try:
        if args.command == "validate":
            report = inspect_profile(args.profile, allow_draft=args.allow_draft_standards)
            print(report.model_dump_json(indent=2))
            return 0 if report.valid else 1
        if args.command == "build":
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
