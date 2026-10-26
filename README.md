# Trial Design Workflow

An auditable workflow for converting clinical study protocols into human-reviewable
SDTM Trial Summary (TS) drafts. Version **0.5.0** implements **Step 0: Master Lookup**;
Steps 1–4 remain pending. The scope is TS only, targeting an SDTMIG v3.4 programmer-review
draft without a regulator-specific submission context.

## Start here

| Task | Location |
| --- | --- |
| Review all current parameter contracts | Local `outputs/step0-clinical-review-2026-09-25-v3/review/master_lookup_review.csv` |
| Edit proposed parameter policies | [ts-parameter-policies-v2.json](config/standards/ts-parameter-policies-v2.json) |
| Build and review the current profile | [v3 guide](docs/step-0-full-lookup.md) |
| Check unresolved issues | [Known limitations](docs/known-limitations.md) |
| Work on the Python package | [src/trial_design_workflow/](src/trial_design_workflow/) |
| Find other documentation | [Documentation index](docs/README.md) |

The current v3 profile pins SDTM 2.0 / SDTMIG 3.4 / CT 2026-09-25. It contains
133 proposed parameter policies, 282 exact response mappings, and a separate
11-variable TS metadata table. The user accepted it as a provisional development
baseline. It remains a **draft**, without qualified SDTM content signoff.
Passing engineering checks does not approve its content; Step 0 content review
is still required before merging Step 1.

## Repository layout

```text
config/       Maintained configuration: parameter policies, build recipes, study catalog
src/          Python package and bundled immutable standards assets
schemas/      Generated JSON Schema for external validation
tests/        Automated tests and synthetic fixtures
tools/        Wrappers for building, validating, comparing, and exporting schemas
data/         Local original inputs: protocols and authorized standards
outputs/      Local artifacts: current v3 review bundle; older runs under archive/
docs/         Current documentation; historical guides and release notes under history/
```

Actual study inputs, local standards, and generated runs under `data/` and `outputs/`
are excluded from Git; placement guides are tracked. The 2025 CT and legacy profile
under `src/trial_design_workflow/assets/` are immutable replay assets, including
snapshots that appear duplicated. [Earlier build recipes](config/standards/README.md)
also remain available for replay.

The package has two business subpackages: `standards/` implements Step 0, and
`extraction/` handles existing PDF/regex extraction. `inputs.py`, `ts_registry.py`,
`excel.py`, and `ts_cli.py` support the compatibility workflow until later stages
replace them.

The IDE hides `.venv`, caches, and `outputs/archive` by default; these files remain
on disk. Adjust `files.exclude` in [.vscode/settings.json](.vscode/settings.json)
to show them. The previous v2.2 review bundle now lives at
`outputs/archive/step0-development-2026-10-26/step0-clinical-review-2026-09-25-v2.2/`.
The archive's `repository-cleanup-2026-10-26.json` records file moves and SHA-256 hashes.

## Install and verify

Python 3.11+ and uv are required. Run from the repository root:

```sh
uv sync --extra dev --locked
uv run --locked pytest -q
uv run --locked ruff check .
uv run --locked ruff format --check .
```

Tests use synthetic data and require no network access. Try Step 0 with a fictional profile:

```sh
uv run --locked trial-ts standards build \
  --spec tests/fixtures/standards/minimal-profile/profile.json \
  --output outputs/step0-check-01
uv run --locked trial-ts standards validate \
  --profile outputs/step0-check-01 --allow-draft-standards
```

Draft/synthetic warnings are expected; validation does not approve clinical use.
Output directories must be new. Building the real v3 profile requires
[authorized local standards](data/standards/local/README.md); commands are in the
[v3 build guide](docs/step-0-full-lookup.md#build-and-inspect). Do not edit hashed
outputs directly. Policy changes require a new recipe/profile revision and updated hashes.

## Workflow boundaries

The planned workflow is Master Lookup → page-grounded Study Facts → parameter
selection → deterministic mapping and TS generation → QC and Excel. AI may propose
facts; selection, mapping, generation, and QC must replay offline. Missing values,
external-source requirements, and unresolved reviews remain explicit exceptions,
without guessed values or automatic null flavors.

The planned workbook sheets are `Exceptions`, `TS_Draft`, `Parameter_Audit`,
`Study_Facts`, `Evidence`, and `Run_Info`. Workbook edits are annotations; they do
not approve proposals or mutate JSON artifacts.

The existing `trial-ts --protocol ...` / registry / hybrid commands still produce
the historical 129-row candidate workbook; see the
[compatibility guide](docs/history/legacy-workbook.md). The regex-based
`trial-extract` path remains available. The old `trial-design` approval prototype
has been retired.

Study A is the development case; Study B remains held out. See the
[study input policy](data/source_documents/README.md). Protocol content is not
uploaded by default, and remote processing requires explicit authorization.
The project makes no submission-readiness or validated production-accuracy claim.
The [implementation contract](trial_design_workflow_lean_ts_mvp_implementation_plan.md)
defines the full development sequence and acceptance gates.
