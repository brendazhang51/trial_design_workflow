# Milestone 1: deterministic foundation

Historical description of the pre-redesign prototype. The synthetic approval
engine, `trial-design` command, and example inputs were retired in v0.4.0.
Use [Step 0](../step-0-master-lookup.md) for the current workflow.

Milestone 1 implements the engineering foundation with synthetic fixtures only.
It does not provide an authoritative TS registry. A complete candidate parameter
set must be established from supplied, pinned standards and the intended
submission context before real-study use. SDTM model and errata versions remain
unselected; the manifest explicitly reports `standards_status: not_loaded`.

## Contracts and boundaries

`schemas.py` defines Pydantic models for artifacts, source documents, page-level
evidence, proposed facts, fact review history, registry entries, rules, vocabulary
snapshots, applicability proposals, decision reviews, TS records, traceability,
QC findings, and manifests. Unknown fields and broken internal references are
rejected. Approvals require reviewer identity, timezone-aware timestamps, and
rationale. These are declared audit records; authentication and access control
are future work.

The JSON input explicitly includes a registry and terminology snapshot. Registry
entries identify code, label, fact source, rule, automation level, applicability,
source requirement, derivation, and response codelist. Only synthetic rules are
accepted. The versioned example assets live in `examples/synthetic/` and must not
be relabeled as authoritative standards.

The pure engine has no PDF parser, model provider, workbook logic, or network
dependency. Future extraction adapters must produce schema-validated facts.

## Review and generation

1. Preserve the original `raw_statement`, `proposed_value`, and evidence.
2. Append fact reviews; use `correct` when an approved value differs from the
   original proposal, and `reject` to revoke it. Never replace review history.
3. Generate the review bundle. `review_queue.json` exposes each proposal and its
   context-bound SHA-256 digest.
4. For a decision accepted after human review, append a `decision_reviews`
   entry to a new input JSON with `parameter_code`, `proposal_sha256`, `reviewer`,
   `reviewed_at` (with timezone), `action` (`approve` or `reject`), and `rationale`.
5. Run again in a new output directory and inspect findings and traceability.

A fact approval alone never produces a TS record. The latest decision review
must approve the current proposal digest. Changes to facts, evidence, source
hashes, study identifier, parameter rules, vocabulary, or engineering limits
invalidate affected approvals. Review history is retained in the input snapshot;
the latest effective reviews are also attached to each generated record's
traceability. Append-only storage enforcement and a review UI are later work.

An approved proposal with state `needs_review`, `needs_external_source`, or
`unsupported` still cannot produce a record. Exclusions are retained explicitly.
All registry entries appear in the proposal output even if their facts are absent.

The current generator supports one exact copied value per parameter per study.
It orders included records lexicographically by `TSPARMCD` and assigns contiguous
`TSSEQ` values from 1. Multiple responses, derived values, null flavors, long-text
continuation, and additional TS variables need separately sourced rules and
implementation. Overlong text is blocked for review without splitting.

Terminology matching is exact and case-sensitive against the selected synthetic
snapshot. No guessed codes, fuzzy mappings, or external lookups are performed.
Terminology code and snapshot provenance live in traceability; this foundation
does not claim full TS controlled-term variable support.

## Output artifacts

| File | Review purpose |
| --- | --- |
| `run_input.json` | Validated snapshot with original proposals and full supplied review history |
| `review_queue.json` | Every candidate's applicability proposal and digest for explicit approval |
| `ts_records.json` | Supported standard TS fields only; no review metadata |
| `traceability.json` | Record-to-evidence, effective approvals, rule and term mapping |
| `qc.json` | Structured findings with severity and resolution status |
| `manifest.json` | Software version, input/output hashes, source versions, run timestamp and logical-record hash |

The CLI verifies referenced source-file hashes before generation. Paths resolve
relative to the input JSON unless absolute. The demo builder uses absolute paths
to the checked-out synthetic assets. A run's input snapshot records the selected
registry and vocabulary content; source artifacts themselves must be retained
alongside archived runs. Hashes detect byte changes, not source authority.

The CLI exits with `0` for a completed bundle without error findings (warnings
and unresolved items may still exist), `1` for a completed bundle with QC errors,
and `2` for invalid input, unavailable or changed artifacts, or output errors.
Warnings are never a statement of study completeness. Schema errors are emitted
as structured JSON to stderr without echoing supplied field values.

Manifest timestamps may differ between identical runs. Logical records, proposal
digests, sidecars, and logical-record hashes remain stable. Output files use
canonical JSON with stable key ordering. The manifest does not hash itself.

## QC and validation

Boundary schemas reject missing structural values, blank text, bad identifiers,
invalid page indexes, duplicate registry IDs, unknown references, and ambiguous
vocabulary mappings. The engine blocks unresolved facts, unapproved or stale
decisions, unmatched terminology, configured field-length violations, and control
characters. Field limits are explicitly synthetic engineering limits.

Semantic QC checks duplicate logical keys and sequences, code/label/value mapping,
terminology verification, record ordering, evidence linkage, and agreement with
deterministic regeneration, including traceability and proposal sidecars.
External-source parameters always remain unresolved in this milestone.

Tests cover synthetic generation, review gating, corrections, stale approvals,
schema rejection, source hashes, deterministic regeneration, and artifact
round-tripping. No model calls, real protocols, or external standards are needed.
Excel export and workbook re-opening checks begin in Milestone 3.
