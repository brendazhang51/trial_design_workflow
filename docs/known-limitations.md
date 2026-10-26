# Current baseline and open notes

On 2026-10-26 the user accepted clinical profile v3 as a provisional development
baseline, with later refinement and notes where processing is unavailable. This
records that working decision; it is not a qualified signoff or promotion to
`approved_for_mvp`. The profile and review manifest remain draft/review-only.

| Area | Current handling | Material or work needed |
| --- | --- | --- |
| Applicability policies | All 133 parameters have explicit project proposals; CT membership does not require study inclusion | Review the 48 baseline, 61 conditional and 24 scope-exclusion policies against study context and cited standards |
| Unknown condition inputs | Missing, proposed, conflicting and invalid inputs must remain unknown | Step 2 must enforce the catalog's exact input domains before evaluating predicates; its test interpreter is not a runtime selector |
| Actual-study facts | Actual enrollment, actual retention/processing and actual dates cannot be supplied from protocol intent | Obtain documented study data/sponsor evidence; retain source requests and review notes until supplied |
| External terminology | TRT/CURTRT and other external contracts retain manual/external handling | Select an authorized dictionary/version and document exact code/value evidence; no automatic external lookup or fabricated identifier |
| TBPRD | Retained in the CT universe and scope audit; no codetable codelist is inferred | A tobacco-profile scope expansion would need an explicit response source and coding policy |
| Decimal/ratio/duration transforms | Step 0 declares contracts only | Step 3 must implement named normalizers, denominator checks, units and precision rules without guessing rounding |
| Long text and TS structure | Eleven base-variable metadata rows are transcribed; runtime generation is still the compatibility path | Step 3 must implement the pinned IG's TSVAL1–TSVALn behavior and full TS structure, followed by Step 4 QC |
| Standards interpretation | Six authoritative source roles and the public errata snapshot are pinned locally | Review transcriptions, applicability of errata, response associations, source rights and the full exception policy before promotion |
| Real-study example | Supplementary comparison only; it neither approves rules nor supplies a gold set | Review identified differences individually; preserve original workbook and historical CT versions |
| Workflow delivery | Step 0 maintenance/review is implemented | Step 1 Study Facts, Step 2 selection, Step 3 generation and Step 4 review workbook remain separate implementation phases |

For a new unresolved case, retain the affected parameter/fact, exact source
locator, what cannot be determined, required material and next action in structured
exceptions or review notes. Missing information does not authorize exclusion,
approval, a null flavor or a guessed value. Readable export edits are annotations;
revise the versioned catalog/recipe to change executable contracts.

The nine original source differences have dispositions in the v3
`source_resolutions.csv`/`.json`; they are not nine open acquisition blockers.
`source_discrepancies.json` remains the unchanged raw comparison. Build and source
checks passing do not close the content-review note above.

Current generated runs remain under `outputs/` locally. Superseded Step 0
experiments, v2.2, evidence extracts, supplementary study comparison and source
receipts are archived under `outputs/archive/step0-development-2026-10-26/`;
pre-redesign work is under `outputs/archive/pre-redesign/`. Byte-identical rebuild
copies may be removed after comparison. Original standards and study files remain
outside the cleanup and outside Git.
