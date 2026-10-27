# Parameter selection and TS generation — development workflow

Version `0.7.0.dev0` adds the deterministic Step 2 and Step 3 development path.
Work is on `step2-3-deterministic-core`. The approved clinical v3 lookup remains
unchanged. New TS records are proposals for programmer review; Step 4's Excel
workbook and full QC presentation remain separate work.

## What you can do

1. Supply saved study facts and an explicit standards selection.
2. Evaluate every candidate parameter, retaining include/exclude/unresolved reasons.
3. Generate supported records from documented, human-reviewed values.
4. Inspect the TS JSON, source/rule trace and structured findings.
5. Replay the saved bundle offline and compare logical hashes.

The commands do not call a model, fetch a registry, approve facts, import workbook
edits, or alter the standards profile. They preserve the compatibility workbook CLI.

## Inputs and human review

There are two fact-input routes:

- **Saved Step 1 proposals:** pass `study_facts.json` from a complete Step 1 bundle
  and supply `--study-id`. Its adjacent manifest and page snapshots are verified.
  These facts remain unreviewed. Unconditional parameters can be selected while
  their values remain unresolved; conditional assessments stay unknown. No study
  identity approval is inferred from `--study-id`, so this route does not emit
  normal TS records by itself.
- **Human-curated structured inputs:** supply a JSON file conforming to
  `CuratedInputs`. It records raw observations, original proposals when available,
  reviewed values, exact citations, reviewer decisions and pinned source files.
  The package validates these declarations but does not authenticate reviewers or
  provide an approval platform. Prepare this file through your existing review
  process; no command turns an AI proposal into a human-reviewed value.

Export the input and output schemas to a new directory:

```sh
uv run --locked trial-ts schemas --output outputs/deterministic-schemas-01
```

A curated input file has `schema_version: "1"`,
`purpose: "human_curated_study_inputs"`, `study_id`, `identity_review`, `sources`,
`facts`, optional `complete_collections`, and optional `source_proposals`.

Each source identifies its exact relative `path`, SHA-256, version, source type
(`protocol`, `study_data`, `sponsor`, `external`) and format (`pdf`, `text`, `json`).
Paths resolve within `--source-root`, or the input file's directory by default.
Original bytes are hash-checked before parsing; PDFs use strict pypdf extraction.
No OCR or source-format guessing is performed.

Each fact records:

- `fact_id`, `fact_key`, source type and source-backed repeat/association keys.
- Separate `raw_value`, `proposed_value`, and `reviewed_value` fields.
- `status`, optional unit or explicitly reviewed null flavor, and exact citations.
- A human `review` containing reviewer ID, timezone-aware review timestamp, action
  and rationale. `approve` preserves the proposed value; `correct` records changes.
- Optional `proposal_id` and `proposal_sha256` references into the unchanged
  `source_proposals` object. Corrections do not replace the original proposal.

Every citation identifies its source/hash, zero-based PDF page index, printed-page
label when available, quote, character offsets and locator. Text/JSON sources use
page index 0. Quotes and raw values are checked against the saved text. Association
keys must occur in evidence; the pipeline does not invent arm or outcome links.
Study identity also needs a reviewed citation containing the supplied identifier.

For terminology supplied through an external source, the optional fact `coding`
contains `source_id` and `record_pointer`. This points to an entry in a pinned,
authorized external JSON snapshot. Each entry has `code`, `value`, `reference`
and `version`; the value must equal the reviewed value and the version must match
the source declaration. This is saved-source validation, not an external lookup
integration or authorization to obtain a dictionary. Manual/unsupported parameter
contracts still remain manual exceptions.

Reviewed-value declarations are trusted review inputs, not independent proof of
clinical interpretation. The programmer must still check context, planned versus
actual semantics, source suitability and the resulting TS draft.

## Step 2: select parameters

```sh
uv run --locked trial-ts select \
  --facts /authorized/path/reviewed_inputs.json \
  --active-profile config/standards/active-profile.json \
  --output outputs/selection-01
```

Use `--profile <profile-directory>` for another explicitly selected profile.
`--allow-draft-standards` is required for a draft/synthetic engineering fixture;
the resulting findings retain that distinction. It is not needed for approved v3.

The result covers every parameter in the selected profile. Each decision records
the rule/version, predicate evaluation, fact IDs and hashes, rationale, expected
cardinality, repeat/group keys, missing prerequisites and source references.
Parameter inclusion and value availability remain separate: an always-included
parameter with no actual-study value stays included and carries an exception.

Evaluation uses true/false/unknown logic. Missing, proposed, conflicting,
wrong-source and out-of-domain values do not become negative assessments, including
under NOT. The v3 catalog's explicit include/exclude input domains are loaded from
its hash-pinned source. A generic comparison without a closed domain cannot infer
a negative result from an arbitrary unequal value. `fact_count` needs an affirmative
human assessment of collection completeness; partial extraction is not a count.

Outputs are `parameter_selection.json`, `study_context.json`,
`runtime_profile.json`, `qc_findings.json` and `run_manifest.json`.

## Step 3: generate records

Use the validated context and runtime snapshot from the selection bundle:

```sh
uv run --locked trial-ts generate \
  --facts outputs/selection-01/study_context.json \
  --runtime-profile outputs/selection-01/runtime_profile.json \
  --selection outputs/selection-01/parameter_selection.json \
  --output outputs/generation-01
```

`--profile` and `--active-profile` remain available instead of `--runtime-profile`.
Generation recomputes selection from the pinned context/rules and rejects an
edited or stale selection file. Only `include` decisions can produce normal rows.
There are no generic blank placeholders or automatically assigned null flavors.
Unresolved values and unsupported transformations become structured findings.

The TS dataset contains only standard fields: `STUDYID`, `DOMAIN`, `TSSEQ`,
`TSGRPID`, `TSPARMCD`, `TSPARM`, `TSVAL`, `TSVALNF`, `TSVALCD`, `TSVCDREF`, and
`TSVCDVER`, with explicitly enabled continuation variables where applicable.
Requiredness, types, labels and source references come from the profile's separate
variable metadata. All eleven base columns are represented, including expected and
permissible fields that are null for a particular record. Group associations use
documented keys; stable sorting precedes sequence and group-ID assignment.
Globally unique sequences are a project ordering convention, stricter than the
pinned source's parameter-level uniqueness requirement.

The bundle adds:

- `ts_records.json`: logical TS rows, without nonstandard review fields.
- `record_trace.json`: raw/reviewed inputs, fact hashes, citations, identity
  evidence, derivation and mapping IDs, dictionary pointers and source references.
- `ts_generation.json`: rows, trace, column/variable metadata and findings together.

Logical outputs have no runtime timestamps. All records remain marked as draft
proposals at bundle level, not as extra variables inside the TS dataset.

## Mapping boundaries

- Controlled terms use exact, versioned maps and active code/label/codelist pairs.
  Unknown spellings or absent aliases remain exceptions; no fuzzy mapping occurs.
- Integer and decimal formatting is explicit. Decimal trailing precision is
  preserved. Ratios require nonnegative integer counts, a positive denominator,
  compatible units and a numerator no greater than the total. A non-terminating
  decimal needs an explicit rounding policy and is blocked rather than rounded.
- Date and duration handling accepts a conservative ISO 8601 subset and preserves
  the source representation. It does not translate English dates/durations, infer
  missing components, convert weeks into months or substitute registry dates.
  Source-format/precision mismatches remain review exceptions.
- Null flavors require a reviewed explicit proposal, a permitted target field,
  a parameter policy and a verified active term in the pinned null-flavor list.
- Long text follows the selected profile. **Approved v3 remains
  `block_for_review`.** The implementation also supports the separately enabled
  `sdtmig34_tsval_continuation` policy, requiring an SDTMIG 3.4 source reference to
  Assumption 4 / section 4.5.3.2. It splits between words into TSVAL, TSVAL1, etc.,
  preserves concatenated source text, and blocks oversized unbroken tokens.
  This implementation caps continuation names at eight characters (through TSVAL999)
  as a project physical-variable policy; larger cases remain exceptions.
  Continuation labels inherit TSVAL's label as a documented project convention.
  Enabling this mode in v3 would change its content and needs a new profile decision;
  no such change is made by this implementation. The 200-character physical-field
  policy is not a claim that JSON/Excel requires a SAS transport limit.
- Illegal characters are blocked. Formula-like text stays literal logical data
  and is flagged in trace/findings for safe Excel presentation in Step 4. These
  commands do not create a workbook or execute source text.

## Replay and review findings

```sh
uv run --locked trial-ts replay \
  --manifest outputs/generation-01/run_manifest.json \
  --output outputs/generation-replay-01
```

The manifest hashes the saved files, records original study/standards source hashes,
and pins interpretation code, software and Python versions. Replay checks the
closed file inventory and reproduces logical selection/generation hashes before
writing a new bundle. It uses the saved validated source text and rule snapshots;
it does not reparse original PDFs, fetch dictionaries or contact providers. Hashes
assume a trusted manifest and are not signatures or reviewer authentication.

Exit 0 means no blocking findings; exit 1 means artifacts were written with open
findings; exit 2 means an input, evidence, integrity or output-path failure prevented
the run. A successful replay is reproducibility evidence, not clinical approval.
Every output directory must be new. All study text and generated bundles stay local
and ignored by Git.

Synthetic tests cover the complete 133-parameter policy matrix as well as separate
coding, precision, repetition, source, null-flavor, security and replay cases.
No reviewed real-study accuracy result is implied. Study B remains held out, and
the frozen Study A reference and Step 4 review workbook are still pending.
