# AGENTS.md

## Implementation contract and current phase

Read `trial_design_workflow_lean_ts_mvp_implementation_plan.md` in full before
implementation. The user has authorized development against that plan. Its
plan-first response requirement has already been satisfied; do not repeatedly
request permission to begin ordinary implementation work.

Execute in order: Step 0 Master Lookup; Step 1 AI Study Facts; Step 2 parameter
selection; Step 3 deterministic mapping and TS generation; Step 4 QC and Excel.
Stop after Step 0 for qualified SDTM content review before merging Step 1.
Create a repository Codex Skill only after all MVP gates and explicit approval.
The README describes the current redesign; `docs/history/` records legacy behavior.

Cleanup authorized on 2026-10-26 retires the unused Milestone 1 approval engine,
`trial-design` entry point and synthetic demo. Shared serialization utilities
live in `serialization.py`; evidence/fact contracts remain in `schemas.py`.
Keep the active regex extraction and compatibility workbook paths until the new
stages replace them. Preserve immutable CT/profile assets. Archive local old
runs under `outputs/archive/pre-redesign/`; never commit those artifacts.

The current phase is Step 0. Build typed profile contracts, offline validation,
reproducible builders, semantic diff, and tests. Preserve the existing public CLI
and immutable 2025-03-28 assets. Missing authoritative inputs remain explicit
blocking findings; do not promote a draft or invent a signoff. Proposed 2026 CT
versions in the plan require source verification and release selection.

Product scope confirmed by the user on 2026-10-26: the first deliverable is an
SDTMIG v3.4 TS domain draft for programmer review within Trial Design. It does
not target a regulator-specific submission. TS remains the sole domain; adding
TA/TE/TV/TI requires an explicit scope expansion. The first clinical profile
marks regulator_catalog and regulator_guide as not_applicable with this reason;
FDA 2026 source acquisition is not an MVP prerequisite. Preserve legacy profiles
unchanged. CDISC model/IG/errata/terminology requirements still apply.

Include every required TS variable specified by the pinned SDTMIG v3.4 source
and support expected/permissible variables according to that source. Variable
requiredness (dataset columns) and parameter applicability (TSPARMCD rows) are
separate contracts and QC checks. A protocol cannot supply every actual-study
or external-source value; retain those exceptions without fabricated values or
automatic null flavors. Record exact variable metadata and source locations
before claiming full TS structure support.

The Master Lookup covers the entire pinned parameter universe for audit, not
automatic inclusion in TS. Keep definitions, applicability rules, value profiles,
derivations, and terminology mappings separate with validated references. AI may
only propose evidence-grounded Study Facts. Selection, mapping, generation, and
QC must replay offline from saved, validated inputs.

The plan permits optional registry facts and preservation of the existing
ClinicalTrials.gov CLI during migration. No registry date may automatically be
treated as an SDTM study-start/end fact in the new path. Remote protocol
transmission still requires explicit provider authorization.

The MVP workbook is a review artifact: edits are annotations, not approvals or
automatic JSON mutations. Do not add an approval platform or workbook approval
import to this MVP. Preserve raw facts and review provenance in structured data;
do not treat proposals as verified. The target sheets are Exceptions, TS_Draft,
Parameter_Audit, Study_Facts, Evidence, and Run_Info, in that order.

## Project mission

Build a small, auditable MVP that converts a clinical study protocol into a
human-reviewable draft of the CDISC SDTM Trial Summary (TS) domain.

The intended workflow is:

1. Extract structured study facts from a protocol with page-level evidence.
2. Evaluate every candidate TS parameter against version-controlled rules.
3. Route missing, ambiguous, or externally sourced information to human review.
4. Generate TS records deterministically from approved structured data.
5. Export an Excel draft together with traceability, QC findings, and a run
   manifest.

The product is a decision-support tool for qualified clinical programming
review. It is not an autonomous regulatory-submission system.

## Current MVP scope

- Domain: SDTM Trial Summary (TS) only.
- Target implementation guide: SDTMIG v3.4, used with its applicable underlying
  SDTM model and explicitly identified errata.
- Inputs: protocol PDF, version-pinned standards and controlled terminology,
  rules configuration, and an optional sponsor Excel template.
- Outputs: structured study facts, parameter decisions, TS Excel draft,
  traceability, QC report, and run manifest.
- Study A is the development case. Study B is the held-out proof-of-concept
  evaluation case until its results are used to change rules or prompts.

Out of scope for the first MVP unless the user explicitly expands scope:

- TA, TE, TV, TI, or other SDTM domains.
- New external registry integrations beyond the optional existing adapter.
- FDA SRS/UNII lookup or unverified substance coding.
- Fully automated Pinnacle 21 execution.
- Automatic production of submission-ready XPT or Define-XML.
- Claims of regulatory compliance or broad clinical-domain generalization.

## Non-negotiable principles

### Do not fabricate

- Never invent protocol facts, controlled terms, NCI codes, UNII identifiers,
  dictionary versions, dates, countries, enrollment counts, or regulatory
  requirements.
- If information cannot be established from an authorized source, represent it
  explicitly as `needs_review`, `needs_external_source`, or the equivalent
  typed status.
- Do not silently convert an unknown value into a null flavor. Null-flavor use
  must be supported by a versioned rule and recorded in the decision trail.

### Evidence before automation

- Every extracted fact must retain source evidence: document identifier,
  source page, exact source quote, and extraction/review status.
- Distinguish PDF page index from printed document page number when both exist.
- Every generated TS record must be traceable either to protocol evidence or to
  a documented, versioned derivation rule.
- Evidence and review metadata belong in sidecar artifacts or workbook review
  sheets; do not add non-standard variables to the TS dataset itself.

### Separate interpretation from generation

- LLM-backed components may propose semantic extraction and normalization.
- Controlled terminology lookup, sequence assignment, validation, long-text
  behavior, and workbook generation must be deterministic.
- Never generate the final workbook directly from free-form model output.
- The deterministic pipeline must consume schema-validated structured data.
- Keep all model-provider code behind an interface so non-LLM and test
  implementations remain possible.

### Version all authoritative inputs

- Pin and record the exact SDTM/SDTMIG, errata, controlled terminology release,
  regulatory guidance, sponsor rules, template, prompt, and model settings used
  by a run.
- Store SHA-256 hashes for protocol files and other material input artifacts.
- Do not overwrite a terminology snapshot in place. Add a new version and make
  the selected release explicit.
- Keep CDISC rules, regulatory expectations, sponsor conventions, and
  study-specific decisions separate and label their provenance.

## Core data model expectations

Use typed, schema-validated models for at least:

- source documents and source evidence;
- extracted and normalized study facts;
- fact review status and reviewer decisions;
- TS parameter registry entries;
- applicability decisions and their rationale;
- proposed and approved TS records;
- terminology mappings and release provenance;
- QC findings with severity and resolution status;
- run manifests and artifact hashes.

Preserve these distinctions:

1. Raw protocol statement.
2. System-proposed normalized value.
3. Human-approved value.

Do not use a single field in a way that collapses those three states.

## Parameter registry rules

The registry is a first-class product artifact, not incidental configuration.

- Start from the complete candidate parameter set required by the selected
  standards and applicable submission context, not only parameters observed in
  historical sponsor workbooks.
- Separately mark which parameters the MVP can automate.
- Unsupported parameters must still appear in applicability review; they must
  not disappear silently.
- Each registry entry should identify the parameter, label, response codelist
  when applicable, applicability logic, value derivation, source requirements,
  automation level, and authoritative rule provenance.
- Do not encode a regulatory assertion unless its authoritative source and
  version are available in the repository or explicitly supplied for the task.

## Decision and review behavior

Use explicit states such as:

- `include`
- `exclude`
- `needs_review`
- `needs_external_source`
- `unsupported`

An applicability decision must include a rationale and rule reference. An
included parameter must additionally include its value source or derivation.
Exclusion is an auditable decision, not absence from output.

Human approval is required before a proposed fact or parameter decision is
treated as verified. Preserve both the original proposal and the approval or
correction; do not destroy the audit trail.

## Determinism and reproducibility

- Given identical approved structured inputs, rules, terminology snapshot, and
  template, the logical TS records must be identical across runs.
- Use stable, documented ordering before assigning `TSSEQ`.
- Do not depend on filesystem enumeration order, hash iteration order, current
  time, or random values for record content.
- Runtime timestamps may appear in manifests, but they must not alter logical
  TS output.
- Long-text behavior must follow a cited rule for the selected standards
  version. Do not invent a generic splitting algorithm and call it compliant.

## QC expectations

QC must be structured and machine-readable. At minimum, design checks for:

- missing required structural values;
- duplicate logical keys and duplicate sequence values;
- invalid or unverified controlled terminology;
- inconsistent code/label/value mappings;
- field length and character problems;
- missing evidence or derivation provenance;
- unresolved review states included in generated records;
- use of external-source values without source documentation;
- deterministic ordering and stable regeneration.

Pinnacle 21 success, if later added, is supporting evidence only. It does not
prove that study-specific parameters are complete or that the protocol was
interpreted correctly.

## Evaluation discipline

- Use synthetic fixtures for automated tests and keep real protocols out of the
  repository unless the user explicitly authorizes their inclusion.
- Treat two real studies as a proof of concept, not evidence of general
  production accuracy.
- If Study B causes changes to rules, prompts, or code, label the original run
  as the held-out evaluation and subsequent runs as post-evaluation regression
  runs.
- Report extraction accuracy, applicability precision/recall, value accuracy,
  terminology accuracy, auto-acceptance rate, and erroneous auto-acceptance
  rate separately when reviewed reference data exists.
- The target of automating roughly 80% of routine work is a development goal,
  not a validated accuracy claim.

## Engineering conventions

- Target Python 3.11 or newer unless repository configuration says otherwise.
- Prefer Pydantic for boundary schemas, `openpyxl` for workbook generation, and
  `pytest` for tests.
- Keep business logic independent from CLI, workbook formatting, PDF parsing,
  and model-provider adapters.
- Prefer small pure functions for terminology lookup, decision evaluation,
  ordering, and validation.
- Avoid hidden defaults for standards versions or terminology releases.
- Validate all external and model-produced data at module boundaries.
- Use clear domain names rather than generic containers such as `data` or
  `result` when a more specific type is available.
- Do not log confidential protocol text unnecessarily. Never commit secrets,
  tokens, credentials, or identifiable study data.

## Suggested repository shape

Use this as guidance rather than creating empty directories prematurely:

```text
src/trial_design_workflow/
  schemas/
  standards/
  extraction/
  decisions/
  terminology/
  generation/
  qc/
  manifests/
  cli.py
config/
  rules/
  registries/
  terminology/
tests/
  fixtures/
docs/
```

## Development order

Follow Steps 0-4 and their acceptance gates in the implementation contract.
Run the locked baseline before changes and the tests, Ruff lint, and formatting
checks after each phase. Track unmet human/source gates separately from passing
engineering tests. Do not describe a partial standards draft as an approved
or complete Step 0 deliverable.

Do not introduce external registries or additional Trial Design domains merely
because they may be useful later.

## Working practices for coding agents

Before changing code:

- Read this file and any more specific `AGENTS.md` in the target subtree.
- Inspect existing configuration and tests before proposing new structure.
- State any standards assumption that is not already captured by versioned
  repository evidence.
- Preserve unrelated user changes in the working tree.

When changing code:

- Keep the change within the requested milestone.
- Add or update tests for behavioral changes.
- Use synthetic protocol content in committed tests.
- Treat model output as untrusted input.
- Do not make a regulatory claim based only on memory or model knowledge.

Before declaring work complete:

- Run the relevant tests and static checks configured by the repository.
- Verify generated artifacts structurally and, for Excel outputs, reopen the
  workbook programmatically.
- Confirm that unresolved facts are visible to reviewers rather than silently
  omitted or converted into apparently verified records.
- Summarize assumptions, test results, unresolved risks, and files changed.

## Definition of done for an MVP feature

A feature is done only when:

- its input and output contracts are typed and validated;
- deterministic behavior is covered by tests;
- relevant source and rule provenance are retained;
- ambiguous or unavailable information follows an explicit review path;
- errors produce actionable structured findings;
- documentation explains how to run and review the feature;
- no output is described as submission-ready without separate qualified review.
