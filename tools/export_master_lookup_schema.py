"""Export the Pydantic schema snapshot to a new file; no independent schema logic."""

import argparse
import json
from pathlib import Path

from trial_design_workflow.standards.models import StandardsProfile


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    content = json.dumps(StandardsProfile.model_json_schema(), indent=2, sort_keys=True) + "\n"
    args.output.parent.mkdir(parents=True, exist_ok=True)
    with args.output.open("x") as stream:
        stream.write(content)


if __name__ == "__main__":
    main()
