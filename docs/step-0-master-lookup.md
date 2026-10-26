# Step 0: offline Master Lookup foundation

The implementation contract is
[`trial_design_workflow_lean_ts_mvp_implementation_plan.md`](../trial_design_workflow_lean_ts_mvp_implementation_plan.md).
The baseline is commit `b7825b2f0d06ac7349bb71f3db43f8562240a988`
with 93 passing tests. This increment adds profile maintenance APIs. The existing
`trial-ts --protocol ...`, registry/hybrid workbook behavior and `trial-extract`
remain available until the new stages replace them. The unused Milestone 1
approval engine, `trial-design` CLI and demo were retired in the authorized
cleanup; shared serialization and evidence contracts remain. See
[release notes](changes-0.4.md) and [historical docs](history/).

## Confirmed first product scope — 2026-10-26

The user confirmed that the first deliverable is a Trial Design TS domain draft
according to SDTMIG v3.4, including its required variables, for programmer review.
The first profile has no regulator-specific submission context. TS remains the
only domain in this increment; TA, TE, TV and TI are not added by this decision.

For the first clinical profile, record `submission_context` as
`SDTMIG v3.4 TS programmer-review draft; no regulator-specific submission`.
Select `regulator_catalog` and `regulator_guide` as `not_applicable`, each with
that explicit scope rationale. FDA 2026 documents are not a prerequisite for this
profile. SDTM v2.0, SDTMIG v3.4, errata, terminology and applicable CDISC rule
sources still need exact versioned provenance. The legacy migration profile
continues to describe its original, unresolved context and is not rewritten.

Maintain two separate standards contracts:

- Variable metadata: the exact TS variables, labels, types, core classification,
  codelist/format and implementation notes from the selected guide/model. Include
  all required columns and apply expected/permissible behavior according to the
  pinned source. Variable metadata and source-based QC are remaining Step 0/3
  work; the current parameter profile alone does not establish a full TS schema.
- Parameter metadata: which TSPARMCD records apply, their values, repeatability
  and terminology. Keeping a required column does not mean including every
  parameter or filling unavailable values. Protocol-unavailable actual results
  and external-source requirements remain explicit exceptions.

The later TS workbook must use this source-backed variable structure rather than
the legacy six-column export. Its exact requirements will be transcribed from
the authorized v3.4 source, not inferred from the synthetic fixture or DS11.

## Delivered contracts

`standards/models.py` is the source of truth for the schema-v2 profile. The JSON
Schema export in `schemas/master-lookup-v2.schema.json` is generated from it.
Semantic and cross-file constraints additionally require the Python validator.

A built profile has these independently validated tables:

| File | Contract |
| --- | --- |
| `manifest.json` | Profile/version/scope, all selected standards roles, signoff, output hashes |
| `source_index.json` | Source publisher/version, URL, known dates, license note, local bytes/hash, provenance |
| `master_lookup.csv` | Identity, classification, references to rules/value contracts, cardinality/grouping, automation/review |
| `applicability_rules.json` | Restricted predicate trees and explicit true/false/unknown outcomes |
| `value_profiles.json` | Value type, terminology, null policy, target variables, long-text review policy |
| `derivation_rules.json` | Named transforms, fact inputs and source requirements |
| `grouping_rules.json` | Named grouping keys and provenance; no execution in Step 0 |
| `terminology.csv` | Exact release/codelist/code/value/lifecycle/source |
| `value_maps.csv` | Versioned input aliases to exact pinned response terms |
| `fact_keys.json` | Declared input vocabulary for rule/derivation references |
| `sources/` | Exact staged source bytes retained for offline rebuilding |
| `checksums.json` | Hashes of every packaged file except the checksum inventory itself |

CSV cells are JSON-encoded values, including strings. This deliberately preserves
null, booleans, lists and structured references without ambiguous empty cells or
delimiter conventions. These files are machine assets; the review workbook will
use normal display text in Step 4. No runtime CSV is changed in place.

The manifest explicitly selects SDTM, SDTMIG, errata/known issues, conformance
rules, CT, CT relationships/codetable, regulatory catalog/guide and sponsor rules.
Selections are `pinned`, `missing` or (where permitted) `not_applicable`, always
with a reason. Unknown publication/retrieval dates are stored as null rather than
invented. Actual source files and their declared hashes must be available locally.

Rules use only `all`, `any`, `not`, `fact_present`, `fact_equals`, `fact_in`,
`fact_count`, `fact_status` and explicit `rule_ref`. Cycles and unknown references
fail validation. Unknown outcomes can only request manual or external assessment.
Step 0 validates these contracts; it does not execute applicability or derivations.
The later evaluator must preserve missing facts as unknown, including under `not`.

## Commands

Run from the repository root with the locked environment:

```sh
uv sync --extra dev --locked

# A small synthetic profile exercises the complete builder and validator offline.
uv run python tools/build_master_lookup.py \
  --spec tests/fixtures/standards/minimal-profile/profile.json \
  --output outputs/step0-synthetic

uv run trial-ts standards validate \
  --profile outputs/step0-synthetic --allow-draft-standards

# Build from a reviewed staging specification and immutable sources/ files.
uv run trial-ts standards build \
  --spec path/to/staging/profile.json --output outputs/new-profile-version

uv run python tools/diff_master_lookup.py \
  --before outputs/step0-synthetic --after outputs/new-profile-version \
  --allow-draft-standards

# Explicit maintenance migration of existing 2025 identities.
uv run trial-ts standards seed-legacy \
  --assets src/trial_design_workflow/assets \
  --staging outputs/step0-legacy-staging --output outputs/step0-legacy
```

`build` and `seed-legacy` only create new directories and never access the network.
The builder selects a fixed version and takes `created_at` from the supplied
specification. Reordering table rows does not alter built bytes. A built package
can be loaded and rebuilt from its own retained sources with identical bytes.

Validation exits 0 when structurally valid under the requested draft policy, 1
for integrity/semantic errors or a disallowed draft, and 2 for command/input
failures. Findings have codes, locations, severity and blocking flags. Draft
opt-in permits maintenance inspection with blocking warnings; it does not grant
clinical eligibility or resolve missing authoritative sources. Future generation
must consume those findings and require the selected clinical profile policy.

## Legacy migration and limitations

The bundled `assets/standards/legacy-candidates-2025-03-28/` is an identity-only
draft. It preserves all 129 original parameter code/label/concept pairs and exact
legacy input bytes. All parameters are `manual_assessment`/`manual`; previous
eleven fact/response suggestions remain non-executable notes and source artifacts.
This explicitly avoids carrying the old registry-date mappings into a new engine.

The master uses `min_records=0`, `max_records=null`, no grouping keys and a manual
value contract for these unresolved cases. These are unimplemented engineering
contracts, not authoritative cardinality or external-source assertions. Every
row carries its unresolved review reason. No null flavor or TS row is authorized.

No sources have been acquired or validated for the plan's proposed 2026 profile.
The existing 2025 CT subset cannot substantiate SDTMIG applicability, requiredness
or complete response mappings. We do not create a misleading 2026 profile directory
or invent requiredness, dates, external identifiers or reviewer signoff. The
SDTM v2.0/SDTMIG v3.4 targets remain explicitly missing-source selections.

The SHA-256 checks detect changes and the content digest binds a declared human
signoff to profile content. They do not authenticate the reviewer or prove the
source interpretation. Historical papers and synthetic sources cannot establish
clinical rule authority. Production approval requires clinical scope, complete
standard selections, a current human signoff, and all semantic/integrity checks.

## Review gate and remaining Step 0 work

The engineering foundation can be reviewed now. Step 0 content acceptance is
pending; no Step 1 AI adapter or repository Skill is added by this change.

- The first context is confirmed above; select the authorized terminology release.
- Stage licensed/authorized SDTM v2.0, SDTMIG v3.4, the errata/known-issue snapshot,
  conformance rules and the applicable CT relationship/codetable source.
- Mark regulatory catalog/guide not applicable for this first profile, with the
  confirmed scope rationale; identify sponsor rules or record their non-applicability.
- Transcribe TS variable metadata from the authorized guide/model and verify
  required columns separately from parameter applicability.
- Review each parameter's applicability, response terminology, cardinality,
  grouping, derivation and exception policy against exact source locations.
- Build the new draft, inspect its semantic diff against the identity-only
  legacy profile and review all missing/unresolved-source findings.
- Record qualified review against the content digest and approve the profile
  only after these source/content gates are met. Do not synthesize a signoff.

Full verification:

```sh
uv run --locked pytest
uv run --locked ruff check .
uv run --locked ruff format --check .
```

Synthetic tests cover malformed input, unknown references, cycles, missing CT
coverage, exact mappings, deprecated terms, signoff invalidation, path traversal,
source tampering, no-overwrite, deterministic builds, CLI compatibility and all
129 legacy identities. Real Study A/B documents are not read by this increment.
