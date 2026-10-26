"""Build an offline profile: --spec staged/profile.json --output new-profile-dir."""

import sys

from trial_design_workflow.standards.cli import main

if __name__ == "__main__":
    raise SystemExit(main(["build", *sys.argv[1:]]))
