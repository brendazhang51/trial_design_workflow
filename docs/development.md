# Setup and developer notes

For the project purpose, user workflow and current delivery status, start with the
[repository README](../README.md). This page covers local setup and implementation.

## Environment

Python 3.11+ and uv are required. Run from the repository root:

```sh
uv sync --extra dev --locked
uv run --locked pytest -q
uv run --locked ruff check .
uv run --locked ruff format --check .
```

Automated tests use synthetic inputs and run without network access. Real study
documents, licensed local standards and generated bundles are excluded from Git.

## Prepare the approved standards package

Follow the [v3 build and promotion instructions](step-0-full-lookup.md#build-and-inspect)
to build from authorized local standards and apply the saved user approval. Then:

```sh
uv run --locked trial-ts standards validate \
  --active-profile config/standards/active-profile.json
```

The active selection pins the recipe and approval record. The normal local bundle
is `outputs/clinical-ts-v3/`. No draft opt-in is needed for that approved package.
The historical profile ID retains its `review-draft` suffix for exact content
binding; the manifest status and approval record determine its current state.

For a fictional engineering example that needs no clinical standards files:

```sh
uv run --locked trial-ts standards build \
  --spec tests/fixtures/standards/minimal-profile/profile.json \
  --output outputs/step0-check-01
uv run --locked trial-ts standards validate \
  --profile outputs/step0-check-01 --allow-draft-standards
```

Synthetic/draft warnings are expected. Output directories must be new. Do not edit
hashed packages in place; changed rules need a versioned revision and approval.

## Repository layout

| Location | Purpose |
| --- | --- |
| `config/` | Parameter policies, standards recipes and selections, and study source metadata |
| `src/trial_design_workflow/` | Python package; `standards/` maintains profiles and `extraction/` handles facts |
| `schemas/` | Generated JSON Schema snapshots |
| `tests/` | Automated tests and synthetic fixtures |
| `tools/` | Build, validation, diff and schema-export wrappers |
| `data/` | Authorized local study documents and original standards |
| `outputs/` | Local run bundles and archived experiments |
| `docs/` | Current guides; `history/` preserves earlier designs and releases |

Immutable 2025 CT/profile snapshots and earlier recipes remain for replay.
The compatibility modules (`inputs.py`, `ts_registry.py`, `excel.py`, `ts_cli.py`)
remain in use until later stages replace their behavior. Do not delete apparently
duplicated standards snapshots or original sources as a cleanup shortcut.

The IDE hides the virtual environment, caches and `outputs/archive` by default.
Adjust `files.exclude` in [.vscode/settings.json](../.vscode/settings.json) to show them.

## Stage interfaces and constraints

- [Step 0 contracts and maintenance CLI](step-0-master-lookup.md)
- [Step 1 provider boundary, evidence checks and CLI](step-1-study-facts.md)
- [Steps 2–3 structured inputs, selection and generation](steps-2-3.md)
- [Legacy workbook commands](history/legacy-workbook.md)
- [Implementation contract and acceptance gates](../trial_design_workflow_lean_ts_mvp_implementation_plan.md)

Step 1 development is preserved on `step1-study-facts`. Deterministic Steps 2–3
are on `step2-3-deterministic-core`, version `0.7.0.dev0`. The approved v3
lookup does not approve study facts or complete the remaining MVP gates. Remote
protocol transmission still requires explicit provider authorization.
