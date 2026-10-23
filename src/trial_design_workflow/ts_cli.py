"""One public path: Input -> TS Parameter Registry -> Excel Output."""

import argparse
import json
import sys
from pathlib import Path

from pydantic import ValidationError

from .excel import save_workbook, workbook_bytes
from .inputs import ASSETS, collect_inputs
from .ts_registry import build_candidates, load_ct, load_registry


def run(
    *,
    output: Path,
    nct_id: str | None = None,
    protocol: Path | None = None,
    registry_json: Path | None = None,
    registry: Path | None = None,
    ct: Path | None = None,
) -> Path:
    destination = output if output.suffix.lower() == ".xlsx" else output / "TS_Draft.xlsx"
    if destination.exists():
        raise ValueError("Output workbook already exists; use a new output path to preserve edits")
    parameters = load_registry(registry or ASSETS / "ts-parameters-v1.csv")
    terminology = load_ct(ct or ASSETS / "ct-2025-03-28.csv")
    inputs = collect_inputs(nct_id=nct_id, protocol=protocol, registry_json=registry_json)
    candidates = build_candidates(inputs, parameters, terminology)
    save_workbook(destination, workbook_bytes(inputs, parameters, terminology, candidates))
    return destination


def main() -> int:
    parser = argparse.ArgumentParser(
        description="Create a programmer-review TS Excel candidate draft"
    )
    parser.add_argument("--nct-id")
    parser.add_argument("--protocol", type=Path)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument(
        "--registry-json", type=Path, help="Optional offline API snapshot; requires NCT ID"
    )
    parser.add_argument("--registry", type=Path, help="Optional versioned TS parameter CSV")
    parser.add_argument("--ct", type=Path, help="Optional explicitly released CT snapshot CSV")
    args = parser.parse_args()
    try:
        destination = run(**vars(args))
    except ValidationError as exc:
        print(
            json.dumps(
                {
                    "code": "INVALID_INPUT",
                    "errors": [
                        {"location": list(e["loc"]), "message": e["msg"]}
                        for e in exc.errors(include_input=False, include_url=False)
                    ],
                }
            ),
            file=sys.stderr,
        )
        return 2
    except (OSError, ValueError) as exc:
        print(json.dumps({"code": "TS_DRAFT_ERROR", "message": str(exc)}), file=sys.stderr)
        return 2
    print(f"Created {destination}. Review Parameter_Review and Evidence_QC; all records are draft.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
