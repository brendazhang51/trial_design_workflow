# Step 1 Study Facts v2 — development workflow

Step 1 was authorized for development on 2026-10-26. Work remains on
`step1-study-facts`, version `0.6.0.dev0`; the qualified Step 0 content-review gate
must pass before merge or release. The clinical profile remains draft. This step
creates unapproved facts, not parameter decisions, TS records, or a workbook.

## Contracts and code

All new code lives in the existing `extraction/` package:

| File | Responsibility |
| --- | --- |
| `facts_models.py` | Versioned catalog, request/response, evidence, facts, findings, and manifests |
| `facts.py` | Saved-response/regex provider boundary, grounding, deterministic normalization and reconciliation |
| `facts_cli.py` | Local preparation, extraction, bundle hashing, replay and schema export |
| `evaluation.py` | Metrics against a separately supplied frozen reviewed reference |

`assets/study-fact-catalog-v2.json` is a project-authored extraction catalog with
173 fact keys. It covers each fact and condition key in the provisional parameter
policy catalog, plus protocol metadata and the frozen regex fields. It does not
contain applicability decisions, response codelists, or parameter-to-TS mappings.
The definitions are development proposals, not normative CDISC requirements.

The provider returns raw, literal source values and evidence. The pipeline retains
them as observations and applies only the named `preserve`, `collapse_whitespace`,
or strict `integer` normalizer. It does not infer date precision, convert durations,
map controlled terminology, calculate ratios, or reinterpret actual-study values.
More precise semantic normalization remains review work and later versioned rules.

`StudyFactsProvider` returns a typed `ProviderResponse`; the saved-response adapter
validates JSON and assembly independently serializes/revalidates the models.
The old `FactProvider` and `trial-extract` remain compatibility interfaces.

## Prepare an authorized local protocol

Run from the repository root. Supply the original document's SHA-256 and version;
metadata supplied here does not become a verified protocol fact.

```sh
uv run --locked trial-ts facts prepare \
  --protocol /authorized/path/protocol.pdf \
  --document-id study-a-protocol \
  --document-version 4.0 \
  --expected-sha256 <64-character-original-pdf-sha256> \
  --pages-per-chunk 3 \
  --output outputs/study-a-facts-prepared-01
```

Preparation verifies the original PDF hash, uses strict pypdf parsing, and writes:

- `parsed_document.json`: exact extracted page text and parser findings.
- `fact_catalog.json`: the selected extraction definitions.
- `extraction_request.json`: page-labelled chunks, definitions, prompt/catalog hashes.
- `prompt.txt`: versioned extraction instructions treating document text as untrusted.
- `provider_response.schema.json` and `provider_response.template.json`: response
  schema and an empty template with the correct request fingerprint.
- `regex_rules.json` and `preparation_manifest.json`: frozen fallback rules and file hashes.

These files contain protocol text and must stay local and ignored by Git.
Preparation performs no model call or remote transmission. The saved parser text
is the evidence surface; Unicode character offsets are zero-based `[start,end)`
within that exact page text. Printed page labels are separate parser proposals,
not human-verified numbering. Section/table labels are unverified context.
OCR is not performed. Empty/sparse/scanned pages produce review findings.

## Import a saved Codex/model response

Use the saved prompt, request, response schema and template to prepare proposals
in an explicitly authorized extraction session. This repository does not select
or authorize a remote provider. Copy the filled response to a new local JSON file;
do not edit hashed prepared inputs. The template's `request_sha256` is the hash of
canonical request content without its trailing newline, not the raw file hash.

Each proposal has a catalog fact key, source-backed repeat keys, raw value, unit
when known, status, explanation, and exact evidence spans with document ID/hash,
PDF index, printed-page label, quote and character offsets. Every non-null value,
unit and repeat-key value must occur literally in cited evidence. For example:

```json
{
  "fact_key": "study_title",
  "cardinality_key": {},
  "status": "proposed",
  "raw_value": "Fictional trial",
  "evidence": [{
    "document_id": "synthetic-protocol",
    "document_sha256": "<original document hash>",
    "pdf_page_index": 0,
    "printed_page": null,
    "start": 7,
    "end": 22,
    "quote": "Fictional trial"
  }],
  "explanation": "Explicit title in this fictional example."
}
```

This illustrative proposal is nested in the template's `proposals` array; its
placeholder hash must be replaced and offsets must match the actual saved text.

```sh
uv run --locked trial-ts facts extract \
  --prepared outputs/study-a-facts-prepared-01 \
  --provider saved-response \
  --response outputs/study-a-provider-response-01.json \
  --provider-name <declared-provider-name> \
  --provider-version <declared-version> \
  --model-id <declared-model-id> \
  --output outputs/study-a-facts-01
```

Provider/model identity and optional `--temperature`/`--seed` are supplied
provenance declarations; the package does not verify which model produced the
saved response. No arbitrary provider-settings dictionary or credentials are stored.

The run bundle includes `study_facts.json`, `qc_findings.json`, the exact response
bytes, declared provider metadata, all prepared inputs, and `run_manifest.json`.
The manifest hashes each file and interpretation module, records runtime/parser
versions, and isolates the runtime timestamp from logical facts. Logical fact IDs
and proposal fingerprints are content-derived. No original protocol path or body
is printed in CLI diagnostics. Use the saved findings' codes/locations to inspect errors.

Malformed responses (including unknown fields, approvals, TS variables, missing
evidence or duplicate identical proposals) fail the whole response boundary:
raw bytes are retained, all catalog facts become unsupported, and schema locations
appear in QC. Structurally valid proposals with bad evidence, unknown keys,
unsupported sources, or failed normalization are individually rejected and
retained under `rejected_proposals`. No rejected value becomes a usable fact.

## Conservative statuses and fallback

Every catalog key appears in the facts audit, even if missing or unsupported.
All facts have `review_status=needs_review`. No approval/correction import exists.

- `proposed`: a grounded observation with deterministic text/number normalization;
  semantic interpretation is still unverified.
- `not_found`: no grounded observation, never an exclusion or negative answer.
- `ambiguous`: uncertainty, a rejected sibling observation or incomplete repeat association.
- `conflict`: distinct values or units; all observations and alternatives are retained.
- `unsupported`: a study-data/sponsor/external source or valid provider response is required.

Equal observations retain separate evidence. Different repeat keys remain separate
facts. Repeat IDs must be quoted from source; missing IDs are not invented. A
not-found observation in one chunk cannot erase a value in another. There is no
source precedence, case-folding synonym map or silent conflict resolution.

Exact quote checks do not establish meaning, negation, table alignment, or correct
cross-page interpretation. These remain visible context-review requirements.
Actual study counts/dates cannot be resolved from protocol intent. Registry date
keys remain external/unsupported, separate from actual-study keys. The optional
new registry adapter is not enabled; the existing registry CLI remains available.

Run the local regex fallback explicitly:

```sh
uv run --locked trial-ts facts extract \
  --prepared outputs/study-a-facts-prepared-01 \
  --provider regex --output outputs/study-a-facts-regex-01
```

This uses only the frozen ten-field baseline and reports limited coverage. It is
not AI extraction and does not claim the catalog can be automatically filled.

## Replay, evaluation and schemas

```sh
uv run --locked trial-ts facts replay \
  --bundle outputs/study-a-facts-01 --output outputs/study-a-facts-replay-01
uv run --locked trial-ts facts schemas --output outputs/facts-schemas-01
uv run --locked trial-ts facts evaluate \
  --bundle outputs/study-a-facts-01 \
  --reference /authorized/path/frozen-study-a-reference.json \
  --output outputs/study-a-facts-evaluation-01
```

Replay verifies inventory, hashes and package/Python/implementation versions,
then reconstructs facts from the saved response and page text. It does not fetch
a registry, call a provider or reparse the original PDF. It verifies the logical
hash before writing a successful new bundle. All output directories must be new.
Hashes provide integrity against a trusted manifest, not digital signatures.

Exit codes: `0` means artifacts were written without error-severity findings
(review warnings remain); `1` means a review bundle contains rejected proposals or
provider errors; `2` means an input/integrity/output-path error prevented the run.
Neither `0` nor a successful replay approves facts or the standards profile.

Schema export includes Study Facts v2, provider response v2, catalog v2 and frozen
reference v1. The evaluation reference must identify its reviewer, timezone-aware
freeze time, document hash, synthetic flag, evaluation role, fully reviewed fact
keys, and reference values with exact evidence. This is evaluation input, not an
approval mechanism. The evaluator reports fact/cardinality discovery precision
and recall by key, exact value/unit-set accuracy, and independent observation-validation
pass rate. Undefined denominators are null. Applicability/terminology metrics are
not measured in Step 1; automatic acceptance is zero by design.

## Acceptance evidence and remaining gates

Synthetic tests cover schema overreach, document/quote/offset/page mismatches,
injection text, normalization failure, repeated interventions, table/cross-page
ambiguity, conflicts, scanned pages, invalid responses, hash/version changes,
no-overwrite, network-free replay and reference-based metrics. Existing extraction,
standards and compatibility workbook tests must continue to pass.

A local Study A regex smoke run checks parsing and artifact/replay structure only.
No frozen human-reviewed Study A reference has been supplied, so no clinical
extraction accuracy or AI success rate is claimed. Study B has not been processed
by this development path. Keep it held out until extraction schema, prompts and
thresholds are frozen. Qualified Step 0 content signoff and real reference-based
evaluation remain separate unmet gates. No Step 2–4 code or repository Skill is added.
