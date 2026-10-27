# Current baseline and open notes

On 2026-10-27 the user explicitly approved unchanged clinical profile v3 for the
normal SDTMIG v3.4 TS programmer-review MVP workflow, superseding the provisional
2026-10-26 acceptance. `config/standards/clinical-review-2026-09-25-v3-approval.json`
binds that decision to profile and review-content hashes. The active package is
`outputs/clinical-ts-v3/`, status `approved_for_mvp`; the Step 0 profile approval
gate is complete. The approving actor is recorded as `repository_user`, without
asserting independent credentials. Items below are implementation work and
per-study exceptions, not a pending reconfirmation of unchanged v3.

| Area | Current handling | Material or work needed |
| --- | --- | --- |
| Applicability policies | All 133 parameters have approved project policies; CT membership does not require study inclusion | Step 2 now evaluates all approved policies with a complete audit; changed policy content still requires a new bound approval |
| Unknown condition inputs | Missing, proposed, conflicting and invalid inputs must remain unknown | The production selector now enforces the pinned closed domains and three-valued logic; human-reviewed condition inputs remain necessary |
| Actual-study facts | Actual enrollment, actual retention/processing and actual dates cannot be supplied from protocol intent | Obtain documented study data/sponsor evidence; retain source requests and review notes until supplied |
| External terminology | TRT/CURTRT and other external contracts retain manual/external handling | Select an authorized dictionary/version and document exact code/value evidence; no automatic external lookup or fabricated identifier |
| TBPRD | Retained in the CT universe and scope audit; no codetable codelist is inferred | A tobacco-profile scope expansion would need an explicit response source and coding policy |
| Decimal/ratio/duration transforms | Step 3 implements named, conservative normalizers and exact finite ratios | Repeating decimals require an explicit rounding policy; non-ISO source representations and source-precision mismatches remain exceptions |
| Long text and TS structure | New generation represents all eleven base variables from the bound metadata; source-backed continuation support is implemented | Approved v3 still blocks long text by its explicit policy; enabling continuation requires a new content-bound profile decision. Step 4 workbook/QC presentation remains pending |
| Standards interpretation | Six authoritative source roles and the public errata snapshot are pinned locally | Approval covers the current pinned v3 content and exception policy; retain exact provenance and local source restrictions, and review future changes separately |
| Real-study example | Supplementary comparison only; it neither approves rules nor supplies a gold set | Review identified differences individually; preserve original workbook and historical CT versions |
| Study Facts development | Step 1 supports saved-response proposals, independent evidence checks, regex fallback, offline replay and a reference-based evaluation harness | Step 0 profile approval is complete; obtain a frozen human-reviewed Study A reference set and review broader extraction coverage before claiming accuracy |
| Registry facts in the new path | The compatibility registry CLI is retained; the new protocol-only path marks registry/external facts unsupported | Optional registry acquisition/reconciliation is not enabled in Study Facts v2; registry dates must remain distinct from SDTM actual dates |
| Workflow delivery | Steps 0–3 engineering paths are implemented; selection and generation consume saved validated inputs offline | Real-study reference-based extraction/applicability/value evaluation and Step 4 remain pending. No workbook approval import is implemented |

For a new unresolved case, retain the affected parameter/fact, exact source
locator, what cannot be determined, required material and next action in structured
exceptions or review notes. Missing information does not authorize exclusion,
approval, a null flavor or a guessed value. Readable export edits are annotations;
revise the versioned catalog/recipe to change executable contracts.

The nine original source differences have dispositions in the v3
`source_resolutions.csv`/`.json`; they are not nine open acquisition blockers.
`source_discrepancies.json` remains the unchanged raw comparison. Build and source
checks alone did not grant approval; the explicit 2026-10-27 user decision now closes the profile approval gate.

Current generated runs remain under `outputs/` locally. Superseded Step 0
experiments, v2.2, evidence extracts, supplementary study comparison and source
receipts are archived under `outputs/archive/step0-development-2026-10-26/`;
pre-redesign work is under `outputs/archive/pre-redesign/`. Byte-identical rebuild
copies may be removed after comparison. Original standards and study files remain
outside the cleanup and outside Git.
