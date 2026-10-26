# 0.4.0 — Step 0 engineering foundation

- Added offline schema-v2 Master Lookup profile maintenance, validation, exact
  source/output hashes, content-bound human signoff metadata and semantic diff.
- Added `trial-ts standards` maintenance commands and standalone tool wrappers.
- Added identity-only legacy profile with all 129 parameters routed to manual
  assessment, retaining original 2025 CT assets without modifying them.
- Added synthetic contract, security, reproducibility and CLI regression tests.
- Updated repository instructions to follow the implementation plan and its gates.
- Updated README and study input/evaluation instructions for the TS review-draft scope.
- Retired the unused Milestone 1 synthetic approval engine, `trial-design` entry
  point, demo inputs and dedicated tests. Retained shared fact/evidence models
  and moved canonical JSON/hashing to `serialization.py` without changing behavior.
- Removed the obsolete `tools/build_ts_assets.py` script that could overwrite
  immutable snapshots. Profile maintenance uses the new offline builder.
- Moved milestone documentation and the legacy workbook guide/diagram to
  `docs/history/`. Original prototype code remains recoverable at `b7825b2`.
- Archived local pre-redesign runs in `outputs/archive/pre-redesign/` without
  deleting study data or committing generated artifacts. Added `.DS_Store` ignore.

Existing workbook commands remain compatible and still use the historical
candidate path. The new profile does not yet generate study-specific TS records.
No dependencies were added. Full Step 0 content acceptance is pending authorized
source acquisition, a reviewed clinical profile, a reviewed migration diff, and
qualified SDTM signoff. See [Step 0 instructions](../step-0-master-lookup.md).

## Verification after cleanup

The pre-cleanup suite passed 149 tests. Retiring the standalone approval prototype
removed its 42 dedicated test cases; three focused shared-contract tests preserve
coverage of the retained utilities and evidence/review models. The remaining
suite passes 110 tests, covering Step 0, extraction, and the compatibility workbook
path. Ruff lint and formatting checks pass. Extraction manifests now hash the
shared serialization module instead of the removed approval engine.
