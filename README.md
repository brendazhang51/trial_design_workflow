# Trial Design Workflow

Version 0.4.0 starts the lookup-first redesign of an auditable SDTM Trial Summary
(TS) workflow. The first deliverable is a programmer-review TS draft according to
SDTMIG v3.4, including its required variables, with no regulator-specific
submission context. TS is the only Trial Design domain currently in scope.

## Current status

Step 0's engineering foundation is implemented: typed standards profiles,
offline validation, reproducible packaging, source hashes, semantic diff, and
an identity-only migration of the existing 2025-03-28 CT assets.

The 129-parameter master is a draft: all applicability and value derivations
remain manual pending authoritative source review. TS variable metadata and
source-backed rules are still to be completed. Steps 1-4 will add Study Facts,
parameter selection, deterministic mapping/generation, and exception-first Excel.
The new profile path does not yet generate study-specific TS records.

- [Implementation plan](trial_design_workflow_lean_ts_mvp_implementation_plan.md)
- [Step 0 commands, contracts and review gates](docs/step-0-master-lookup.md)
- [0.4.0 changes and cleanup](docs/changes-0.4.md)
- [Study inputs and evaluation policy](data/source_documents/README.md)

## Install and test

Python 3.11+ and uv are required. Run commands from the repository root.

```sh
uv sync --extra dev --locked
uv run --locked pytest -q
uv run --locked ruff check .
uv run --locked ruff format --check .
```

Tests use synthetic data and run without network access.

## Try Step 0

Build a small fictional profile into a new output directory:

```sh
uv run trial-ts standards build \
  --spec tests/fixtures/standards/minimal-profile/profile.json \
  --output outputs/step0-check-01

uv run trial-ts standards validate \
  --profile outputs/step0-check-01 --allow-draft-standards
```

The fixture contains `X_TITLE` and `X_MANUAL`. Draft/synthetic blocking warnings
are expected. Exit 0 with draft opt-in means the profile passed its structural
checks; it does not approve the profile for clinical use.

For the complete identity-only 129-parameter migration:

```sh
uv run trial-ts standards validate \
  --profile src/trial_design_workflow/assets/standards/legacy-candidates-2025-03-28 \
  --allow-draft-standards
```

Its `STANDARDS_INPUT_MISSING` findings document the remaining source gaps.

Build the same fixture in another new directory and compare:

```sh
uv run trial-ts standards build \
  --spec tests/fixtures/standards/minimal-profile/profile.json \
  --output outputs/step0-check-02

uv run trial-ts standards diff \
  --before outputs/step0-check-01 --after outputs/step0-check-02 \
  --allow-draft-standards
```

Expected result: `"changes": []`. Existing output directories are never overwritten.

## Where to look

| Location | Purpose |
| --- | --- |
| [129-parameter master](src/trial_design_workflow/assets/standards/legacy-candidates-2025-03-28/master_lookup.csv) | Migrated parameter identities and explicit manual dispositions |
| [Profile manifest](src/trial_design_workflow/assets/standards/legacy-candidates-2025-03-28/manifest.json) | Pinned CT selection, missing sources and draft scope |
| `src/trial_design_workflow/standards/` | Schemas, builder, validator and diff |
| [JSON Schema](schemas/master-lookup-v2.schema.json) | Generated profile contract; Python validation also checks cross-file constraints |
| `tests/fixtures/standards/minimal-profile/` | Fictional local staging inputs |
| `config/studies.json` | Study A/B source metadata, not extraction answers |
| `outputs/` | Ignored local run artifacts and archived prototype runs |

Lookup CSV cells use JSON encoding to preserve types and references. Build a new
profile version through the builder instead of editing hashed packaged files.

## Workflow being built

1. Pin a complete, reviewed Master Lookup and TS variable metadata.
2. Extract protocol Study Facts with exact quotes and page evidence.
3. Evaluate every parameter, preserving include/exclude/unresolved decisions.
4. Generate supported, applicable records deterministically.
5. Present unresolved cases first in Excel, with evidence, QC and a run manifest.

AI may propose Study Facts. Parameter applicability, terminology lookup, record
generation and QC use saved structured inputs and deterministic rules. Missing
facts remain explicit exceptions. Required TS columns and applicable parameter
rows are separate decisions.

The target workbook sheets are `Exceptions`, `TS_Draft`, `Parameter_Audit`,
`Study_Facts`, `Evidence`, and `Run_Info`. These are planned outputs for Step 4;
workbook edits remain review annotations in this MVP.

## Compatibility and retired prototypes

The existing `trial-ts --protocol ...` / registry / hybrid workbook commands
remain available while the new generation path is built. They still emit the
historical 129-row candidate workbook. See the
[historical workbook guide](docs/history/legacy-workbook.md) for usage.

The page-grounded regex extractor and `trial-extract` are retained for Step 1.
The obsolete Milestone 1 approval engine, `trial-design` entry point, its
synthetic demo/assets, and its dedicated tests were removed. The old asset
builder that overwrote the frozen CT snapshots was also removed. Original code
is recoverable from Git commit `b7825b2`; milestone documentation is in
[docs/history](docs/history/).

Local prototype runs have been moved to `outputs/archive/pre-redesign/`;
current Step 0 outputs and downloaded source material remain in place.
Neither archived outputs nor local protocol PDFs are committed.

## Study and standards boundaries

Study A (STEP 8) is the development case. Study B (LIMIT-JIA) remains the held-out
evaluation case until the extraction schema, rules and prompts are frozen.
See the [study README](data/source_documents/README.md) and
[source catalog](config/studies.json).

The first reviewed profile targets SDTM v2.0 / SDTMIG v3.4 with pinned errata
and terminology. FDA catalog/guide selections are not applicable to this first
scope. The authorized CDISC sources and TS rules still require review; DS11
provides historical design context only.

Local protocol content stays out of Git and is not uploaded by the new profile
tools. Remote extraction providers require explicit authorization. The project
does not claim submission readiness or validated production accuracy.

