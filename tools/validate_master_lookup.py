"""Validate a profile: --profile profile-dir [--allow-draft-standards]."""

import sys

from trial_design_workflow.standards.cli import main

if __name__ == "__main__":
    raise SystemExit(main(["validate", *sys.argv[1:]]))
