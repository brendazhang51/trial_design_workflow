# Trial Design Workflow

An auditable, human-in-the-loop workflow for producing a draft CDISC SDTM
Trial Summary (TS) domain from a clinical study protocol.

> **Status:** Milestone 1 engineering foundation. Typed contracts, a synthetic
> registry, approval-gated deterministic generation, JSON review bundles, and
> structured QC are implemented. Authoritative standards and complete TS
> parameter coverage are not yet loaded. Outputs are synthetic test drafts.

## Run the synthetic example

Install Python 3.11+ and [uv](https://docs.astral.sh/uv/), then run:

```sh
uv sync --extra dev --locked
uv run python examples/synthetic_demo.py --output outputs/pending-input.json
uv run trial-design --input outputs/pending-input.json --output outputs/pending-run
```

This example contains simulated fact reviews but no parameter approvals, so it
produces no TS records. Inspect `review_queue.json` and `qc.json` to see every
candidate parameter and its review requirements.

To exercise the generation path with explicitly simulated decision approvals:

```sh
uv run python examples/synthetic_demo.py --approved-demo --output outputs/approved-input.json
uv run trial-design --input outputs/approved-input.json --output outputs/approved-run
uv run pytest
uv run ruff check .
uv run ruff format --check .
```

The approved fixture produces two synthetic records plus visible unresolved and
excluded parameters. Its `X_*` parameter identifiers and `TEST_*` terminology
codes are engineering examples, not authoritative CDISC terms. All reviewer
actions in the example are simulated. Use a new output directory for each run;
existing run directories are never overwritten.

See [Milestone 1 contracts and review guide](docs/milestone-1.md) for supported
behavior, artifact contents, review instructions, and limitations.

## Purpose

This project is intended to help qualified clinical programmers turn protocol
content into a reviewable TS draft while preserving the evidence and decisions
behind every proposed record.

The workflow is designed to:

1. Extract structured study facts with page-level protocol evidence.
2. Evaluate candidate TS parameters against explicit, version-controlled rules.
3. Route missing, ambiguous, unsupported, or externally sourced information to
   human review.
4. Generate logical TS records deterministically from approved structured data.
5. Export an Excel draft with traceability, QC findings, and a run manifest.

This is a decision-support tool. Its outputs require qualified human review and
must not be treated as submission-ready solely because they were produced by
the workflow.

## MVP scope

The initial MVP is deliberately narrow:

- **Domain:** SDTM Trial Summary (TS) only
- **Target implementation guide:** SDTMIG v3.4, together with its applicable
  underlying SDTM model and explicitly selected errata
- **Inputs:** protocol PDF, version-pinned standards and controlled terminology,
  rules configuration, and an optional sponsor Excel template
- **Outputs:** structured study facts, applicability decisions, TS Excel draft,
  traceability, QC findings, and a run manifest
- **Evaluation:** Study A is the development case; Study B remains held out until
  its results are used to change code, rules, or prompts

The first MVP does not include other Trial Design domains, external registry
lookups, automated Pinnacle 21 execution, XPT generation, or Define-XML.

## Design principles

- **No fabrication:** unknown or unverified information remains explicitly
  unresolved rather than being guessed.
- **Evidence before automation:** extracted facts retain the source document,
  PDF page index, printed page number when available, exact quote, and review
  status.
- **Human approval:** proposed values and decisions are not considered verified
  until reviewed; corrections do not erase the original proposal.
- **Separation of concerns:** probabilistic extraction may propose facts, while
  terminology lookup, rule evaluation, ordering, validation, and workbook
  generation remain deterministic.
- **Versioned authority:** standards, errata, terminology, rules, templates,
  prompts, and model settings are pinned and recorded with provenance.
- **Reproducibility:** identical approved inputs and authoritative assets produce
  identical logical TS records.
- **Structured QC:** errors and review requirements are emitted as actionable,
  machine-readable findings.

## Planned artifacts

Each run is expected to produce or retain:

- evidence-bearing extracted study facts;
- proposed values separately from human-approved values;
- the full candidate TS parameter applicability review, including exclusions
  and unsupported parameters;
- proposed and approved TS records;
- terminology mappings with release provenance;
- structured QC findings and their resolution status;
- an Excel review workbook; and
- a manifest containing selected versions and SHA-256 hashes of material inputs
  and outputs.

Review metadata belongs in sidecar artifacts or workbook review sheets, not in
non-standard variables added to the TS dataset.

## Milestone plan

### Milestone 1: deterministic foundation

- Define typed, validated schemas.
- Define versioned parameter-registry and rule interfaces.
- Generate TS records deterministically from approved synthetic inputs.
- Implement structured QC checks.
- Add synthetic fixtures and automated tests without requiring an LLM.

### Milestone 2: protocol extraction

- Parse protocol content into evidence-bearing proposed facts.
- Validate all extraction output at the model boundary.
- Preserve raw statements, normalized proposals, and review states separately.

### Milestone 3: review and export

- Evaluate applicability and terminology mappings.
- Add explicit reviewer decisions and approval history.
- Export and programmatically re-open the Excel review workbook.

### Milestone 4: evaluation

- Measure extraction, applicability, value, and terminology performance against
  reviewed reference data.
- Track auto-acceptance and erroneous auto-acceptance separately.
- Preserve Study B's original held-out run before any evaluation-driven changes.

## Proposed repository layout

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

Directories will be added as working features require them; the project avoids
creating placeholder structure with no implementation.

## Development expectations

- Python 3.11 or newer, unless repository configuration later pins another
  supported version.
- Pydantic for boundary schemas, `openpyxl` for Excel generation, and `pytest`
  for tests.
- Pure, independently testable business logic for terminology lookup, decision
  evaluation, record ordering, and QC.
- Synthetic protocol content in committed tests; real protocols remain outside
  the repository unless their inclusion is explicitly authorized.
- No hidden defaults for standards or controlled-terminology versions.
- No confidential protocol text, secrets, credentials, or identifiable study
  data in logs or commits.

## Standards and regulatory sources

Authoritative standards, terminology snapshots, errata, and regulatory sources
have not yet been added to this repository. Until they are present and pinned,
the project must not encode or claim specific regulatory requirements from
memory alone.

## Contributing

Before making changes, inspect the current tests and configuration and preserve
unrelated work. Behavioral changes should add or update tests, retain
provenance, and expose unresolved information to reviewers instead of silently
omitting it.

