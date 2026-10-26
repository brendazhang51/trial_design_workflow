# Historical Step 0: first eight source-backed examples

This page describes the earlier eight-parameter v1 increment. For the subsequent
complete 133-parameter policy catalog and profile 3, see
[the full lookup](../step-0-full-lookup.md). The v1 recipe remains reproducible;
local historical runs are archived under `outputs/archive/step0-development-2026-10-26/`.

The supplied SDTM 2.0, SDTMIG 3.4, CT 2026-09-25, TS Codetable and Conformance
Rules are now used to build an independent **draft**. The original 2025 assets and
compatibility CLI are unchanged. No protocol, Study A/B extraction or Step 1 code
is involved.

## Build and review

```sh
uv run --locked trial-ts standards stage-clinical \
  --spec config/standards/clinical-review-2026-09-25.json \
  --source-root data/standards/local \
  --before src/trial_design_workflow/assets/standards/legacy-candidates-2025-03-28 \
  --output outputs/step0-clinical-review-2026-09-25-v1
```

Use a new output directory on every run. The recipe fixes source filenames,
SHA-256, release and build timestamp; no network acquisition or implicit release
upgrade occurs. It selects CT 2026-09-25 for this new draft only, not clinical
approval. Raw supplied files are packaged under the ignored output's `profile/sources/`.
Do not commit this package or assume redistribution rights. Original download
dates/URLs remain unknown rather than fabricated. The pinned IG is the previously
received `(1)` copy; both supplied copies remain unchanged locally.

Read `review/master_lookup_review.md` first. It expands the runtime contracts and
source transcriptions into a normal-text review. The first eight entries are the
vertical examples. `review/master_lookup_review.csv` is the equivalent one-row-per-
parameter view. `profile/master_lookup.csv` remains a machine asset.

The build also saves:

- `semantic_diff.json`: comparison against the immutable legacy profile.
- `ct_term_evidence.json`: exact CT term/code/definition and PDF-page provenance.
- `source_discrepancies.json`: codetable/CT disagreements, never automatic corrections.
- `ts_conformance_index.json`: 16 explicitly TS-scoped v3.4 rules, with sheet rows
  and cited guidance. This is an index, not implemented QC or a complete index of
  all global rules applicable to TS.
- `review/ts_variable_metadata.csv`: 11 ordered base variables with source locators.
- `fact_input_contracts.json`: proposed restrictions for the future Step 2 boundary.
- `bundle_checksums.json`: all bundle file hashes; no timestamp-dependent content.

Rebuilding the same sources/recipe should produce identical bytes. Missing hashes,
unknown layouts, incomplete response pairs, orphan PDF continuations and conflicting
codetable identities within one file fail acquisition. Cross-source disagreements
instead remain explicit findings, with affected mappings excluded.

## Source findings that change the design

In the supplied 2022-07-21 IG PDF, TS is **section 7.4.2, pages 417-424**.
Section 8.4.3 is about SUPP examples; it must not be used as the source locator for
these TS rules. The published online errata page still requires a separately
pinned, dated snapshot/review; no "no errata" claim is made.

The CT PDF has **133** TSPARMCD terms; the codetable has **132**. The new CT universe
adds EMAMDCL, FDAMDCL, MDTSTAGE and PMDAMDCL relative to the 129-term legacy profile.
All terms remain in audit, without automatically including their rows in a study.
50 parameters have a response-codelist association expanded from the codetable,
using 24 identity/response codelists and 492 extracted CT terms. There are 275 exact
verified response mapping pairs in the initial build. No aliases are inferred.
Here `active` records membership in the supplied published snapshot; retirement
history is not separately established from this PDF.

The initial cross-source comparison records nine discrepancies across six parameters:

- BRIND: the codetable concept code does not match the CT parameter identity.
- FDATCHSP: two responses still use `CNEW`.
- INTTYPE: the supplied `OTHER` code/value association does not match CT exactly.
- SDTIGVER: two codetable values contain trailing whitespace.
- SDTMDVER: numeric spreadsheet value `1` differs from CT text `1.0`.
- TBPRD: present in CT but absent from the supplied codetable.

Even cosmetic differences stay explicit in this first exact-comparison build.
No CNEW identifier is minted. CT establishes the parameter universe and identity;
conflicting codetable associations are not silently rewritten. Invalid response
pairs are excluded from executable maps, while the original workbook is retained.

## First eight parameter proposals

IG Assumption 2 permits recipients to define parameter inclusion requirements.
Since this draft has no regulator-specific recipient, the policies below are
**proposed project choices**, with separate source references; they are not CDISC
universally mandatory parameter requirements. A qualified reviewer must assess
these choices before any profile promotion.

| Parameter | Inclusion proposal | Value source | Response contract |
| --- | --- | --- | --- |
| TITLE | Include descriptive row; missing value is an exception | Protocol title | Text; no TSVALCD, per IG Assumptions 7/9 |
| TPHASE | Include descriptive row; missing phase never implies N/A | Protocol phase | C66737, Trial Phase Response |
| RANDOM | Include whether randomized or not | Protocol randomization | C66742, No Yes Response |
| TBLIND | Include including open-label designs | Protocol masking | C66735, Trial Blinding Schema Response |
| PLANSUB | Include descriptive row; missing count is an exception | Protocol planned enrollment | Numeric count; no TSVALCD |
| ACTSUB | Applicable independently of actual-count availability | Documented actual study data | Numeric enrolled count; do not use planned enrollment or assume registry equivalence |
| TRT | Include on reviewer-established present; exclude only on reviewed absent | Protocol investigational intervention(s), not drug-only | Coded values remain manual/external; no dictionary selected |
| CURTRT | Include on reviewer-established present; exclude only on reviewed absent | Protocol-specified standard-of-care background treatment(s) | Coded values remain manual/external; do not infer from ADDON alone |

TRT/CURTRT applicability inputs accept exactly `present`/`absent` following human
design review. Missing, proposed, invalid or conflicting inputs must be unknown.
The saved fact-input contract must be enforced by the later Step 2 boundary before
evaluating its predicate; no study evaluator or approval-import workflow is added
in Step 0. An IG UNII example is not a mandate to add FDA SRS/UNII integration.

Cardinality for the six descriptive parameters is a proposed single-value project
policy; source conflicts/cohort differences require review. TRT/CURTRT repeat by
intervention key with unresolved grouping. No automated null flavor or long-text
splitting is enabled.

## Variables and remaining gates

The guide marks STUDYID, DOMAIN, TSSEQ, TSPARMCD and TSPARM as required; TSGRPID
and TSVALNF as permissible; TSVAL, TSVALCD, TSVCDREF and TSVCDVER as expected.
The guide's TSSEQ uniqueness is **within a parameter**. Duplicate TSSEQ values
across different TSPARMCD are not intrinsically an error. Future QC must check the
correct key. TSVAL1-TSVALn is a conditional continuation series, not additional
fixed required columns. The metadata is captured; full runtime structure, splitting
and QC support are still future work.

All 133 definitions have CT provenance. The other 125 parameters still need
qualified applicability, value-source, derivation and cardinality adjudication;
they remain visible with parameter-specific actions. A blank codetable response
cell alone does not prove that a parameter is numeric, free text or uncoded.

Validate content with:

```sh
uv run --locked trial-ts standards validate \
  --profile outputs/step0-clinical-review-2026-09-25-v1/profile \
  --content outputs/step0-clinical-review-2026-09-25-v1/content.json \
  --allow-draft-standards
```

Expected: exit 1 while source/content findings remain. Structural validation with
draft opt-in may exit 0; that is not content approval. Remaining gates include
errata capture, source discrepancy resolution, full parameter policy review and
qualified signoff. Stop within Step 0; do not merge Step 1 or create the Skill.
