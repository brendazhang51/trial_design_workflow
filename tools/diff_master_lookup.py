"""Compare profiles: --before old-dir --after new-dir [--allow-draft-standards]."""

import sys

from trial_design_workflow.standards.cli import main

if __name__ == "__main__":
    raise SystemExit(main(["diff", *sys.argv[1:]]))
