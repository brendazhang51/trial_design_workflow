# Step 0 content review

This guide describes the reusable content workspace and review exporter. For the
current source-backed 133-parameter baseline, use the
[full lookup guide](step-0-full-lookup.md). The 2025 identity migration remains
immutable and does **not** establish clinical inclusion or response rules.

## Sources and inventory

The current clinical recipe pins authorized local model/IG/CT/codetable/conformance
files and a dated public errata snapshot. CT 2026-09-25 is explicitly selected;
all nine source differences have dispositions in profile v3. Qualified content
review and the [open implementation notes](known-limitations.md) remain separate.

Place authorized original files below `data/standards/local/`; its README lists
the subdirectories. Actual files are ignored, including non-PDF standards files.
Keep original filenames and download packages. Do not commit licensed materials.

The historical PharmaSUG DS11 PDF is not a substitute for standards. A public
landing page/errata snapshot does not replace the full implementation guide.
Regulatory sources are not required for the confirmed programmer-review context;
the clinical profile records regulator catalog/guide as not applicable. Preserve
the legacy profile's original source declarations for replay.

Inventory files after placing them (no source text extraction or automatic
version/license inference):

```sh
uv run --locked trial-ts standards sources-inventory \
  --directory data/standards/local --output outputs/local-standard-candidates.json
```

This records relative filenames, sizes and SHA-256. Unknown metadata stays null.
A candidate hash does not authenticate authority, licensing or release selection.
Source registration still requires publisher/version/URL, license notes and exact
locators in the profile. Do not bundle restricted bytes into tracked assets.

## Create and inspect a content workspace

The following example deliberately initializes the identity-only legacy profile
to demonstrate gap tracking. For a populated clinical review, `stage-clinical`
builds and exports the content in one step using the current recipe.

```sh
uv run --locked trial-ts standards review-init \
  --profile src/trial_design_workflow/assets/standards/legacy-candidates-2025-03-28 \
  --allow-draft-standards --output outputs/step0-content-v1.json

uv run --locked trial-ts standards review-export \
  --profile src/trial_design_workflow/assets/standards/legacy-candidates-2025-03-28 \
  --allow-draft-standards --content outputs/step0-content-v1.json \
  --output outputs/step0-content-review-v1
```

Outputs include:

- `master_lookup_review.md`: one readable section per parameter, priority eight first.
- `master_lookup_review.csv`: one row per parameter, normal display cells with
  expanded predicates, true/false/unknown outcomes, input facts, value source,
  codelist ID/name/release, transform, null policy, cardinality, aliases and provenance.
- `content_gaps.csv` and `content_findings.json`: blocking source/content gaps with actions.
- `source_inventory.csv` and `source_index.json`: selected/missing source roles and
  existing source metadata/hashes. These describe the supplied profile, not newly
  verified downloads or a future clinical release.
- `ts_variable_metadata.csv`: separate ordered columns, labels, type, role, core,
  codelist/format, notes and source locators. Empty until transcribed, with a blocker.
- `content.json`, `review_manifest.json`, `checksums.json`: saved transcription
  workspace, summary and hashes of the export. All destinations are exclusive-create.

The CSV quotes required by the CSV format are normal escaping; strings are no
longer JSON-encoded. Dangerous spreadsheet prefixes are made literal. CSV/Markdown
edits are annotations, not mutations of JSON or approval. No Excel import is added.

## Fill content without disguising gaps

`standards/review.py` defines the additive `ReviewContent` boundary. Export its
JSON Schema with `trial-ts standards content-schema`. It does not change the
schema-v2 profile or the generated legacy schema.

Each parameter has seven separate assertions: definition, inclusion, value source,
response, derivation, exceptions and cardinality. Each contains status (`missing`,
`proposed`, `source_backed`), text, basis (`standard` or `project_policy`), source
IDs/locators and an action for unresolved content. `source_backed` is a transcription
state, not human approval. Historical, sponsor and synthetic sources cannot prove
a clinical standard assertion. Project policies must be identified as policies.

Response metadata separately distinguishes unresolved, selected codelist,
source-backed no-codelist reason, and external dictionary. Selected codelists
require ID/name/release and must match runtime value contracts and terminology.
External responses require an external runtime contract. Unresolved is not N/A.

Start with TITLE, TPHASE, RANDOM, TBLIND, PLANSUB, ACTSUB, TRT and CURTRT. The generated
workspace provides specific research questions, not assumed answers. In particular:
ACTSUB must establish actual-count definition and source; CURTRT needs affirmative
treatment-design review before exclusion. Study type, parameter applicability and
availability of a value are different questions. An applicable parameter with no
value remains an exception. No missing fact authorizes exclusion or a null flavor.

Then extend to every pinned parameter. Keep rules in applicability files, value
contracts in value profiles and transforms/source inputs in derivations. The
content workspace is a transcription aid, not a second execution engine. Build a
new profile version after adding source-backed assets, initialize/rebase content
against that exact profile digest, and copy only still-valid transcriptions.
Changing the profile invalidates the previous binding. The legacy profile is never edited.

Validate both contracts explicitly:

```sh
uv run --locked trial-ts standards validate \
  --profile src/trial_design_workflow/assets/standards/legacy-candidates-2025-03-28 \
  --allow-draft-standards --content outputs/step0-content-v1.json
```

Expected for legacy: exit 1, with actionable content/source errors. Ordinary
`validate --allow-draft-standards` retains its structural-maintenance semantics.
`review-export` may succeed with blockers so reviewers can inspect them; this is
not acceptance. Review summaries always keep `step0_ready=false`: this export
does not record qualified review/signoff. Neither passing source checks nor prose
can approve an immutable profile or implement missing rules.

## Acceptance and remaining work

Engineering tests cover full 129-row coverage, priority questions, stale bindings,
duplicates, source authority, codelist mismatches, placeholder detection, safe CSV,
source inventory hashes, no-overwrite and reproducible exports. They do not prove
the clinical content. Selection rule execution remains Step 2, not this exporter.

The clinical v3 build now supplies the first-eight examples, full parameter
contracts, exact base-variable metadata, selected CT and semantic diff. The legacy
workspace retains its own unresolved gaps rather than inheriting that approval.
Tests cover every proposed condition's include/exclude/unknown contract and
applicable-but-value-missing behavior. Qualified SDTM review remains outstanding;
the user's provisional baseline acceptance does not create a signoff. No Step 1
code is included in this version.
