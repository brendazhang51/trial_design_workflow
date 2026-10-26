# Complete parameter-contract draft: catalog v2 / profile 3

All 133 parameters in the supplied CT 2026-09-25 TSPARMCD universe now have an
explicit project inclusion policy, named fact input, source requirement, value
type/transform, cardinality, grouping choice and exception path. There is no
"use manual for every other parameter" fallback. Full coverage is enforced against
the CT universe; a missing, duplicate or extra policy fails the build.

These are **reviewable project proposals**, not qualified signoff or a CDISC
universally required-parameter list. The published definitions, codetable mappings
and IG variable metadata retain their separate CDISC provenance. The earlier
eight-parameter draft and immutable 2025 assets are unchanged.

The user accepted v3 as a provisional development baseline on 2026-10-26, with
later refinement and notes for unavailable processing. See
[known limitations and next actions](known-limitations.md). This does not promote
the manifest to approved or claim that study-specific selection is implemented.

## Build and inspect

```sh
uv run --locked trial-ts standards stage-clinical \
  --spec config/standards/clinical-review-2026-09-25-v3.json \
  --source-root data/standards/local \
  --before src/trial_design_workflow/assets/standards/legacy-candidates-2025-03-28 \
  --output outputs/step0-clinical-review-2026-09-25-v3
```

The output path must be new. The example compares against the bundled legacy
profile, which is available in a clean checkout. To compare source resolution
against the previous clinical draft, use
`--before outputs/archive/step0-development-2026-10-26/step0-clinical-review-2026-09-25-v2.2/profile` instead. The saved
development v3 bundle used that comparison. The choice affects only the diff
artifact. Local licensed inputs are prerequisites and remain ignored by Git.

Review `review/master_lookup_review.csv` or `.md`: all conditions, value-source
details, response types, codelists, transforms, repeat/group keys and sources are
expanded there. `profile/master_lookup.csv` is the machine table of validated
references. `semantic_diff.json` compares the selected prior profile. Source and
bundle checksums allow offline replay without fetching newer standards.

The editable catalog is `config/standards/ts-parameter-policies-v2.json`. The build
recipe pins its exact SHA-256; changing it requires an explicit new pin and profile
revision. The catalog itself is also packaged as a hashed source in the profile,
so condition domains and provenance are not unbound review annotations.

## Policy coverage

| Disposition proposal | Parameters | Behavior |
| --- | ---: | --- |
| Always include in this review profile | 48 | Missing value creates an exception, not exclusion |
| Conditional | 61 | Explicit positive/negative design assessment selects include/exclude; unknown remains review |
| Exclude by profile scope | 24 | Jurisdictional application/workflow and tobacco-specific metadata remain in audit |

Scope exclusion is not a legal assertion about the actual study. No FDA/EMA/PMDA
regulatory obligation or device classification is inferred. This implements the
confirmed non-regulator-specific draft scope without deleting terms from audit.

Source requirements are specific: 64 protocol, 18 study-data, 37 sponsor and 14
external-source contracts. External source here means an authorized saved input,
not a new remote registry/dictionary integration. Unselected dictionaries remain
manual/external exceptions, not invented codes. A project uncoded value policy
does not assert that no terminology could apply in another submission context.

Important distinctions captured in individual policies:

- SSTDTC uses the CT-defined eligible enrolled-subject consent/treatment event;
  SENDTC uses final data collection. Neither automatically consumes registry dates,
  a planned date, database lock or data cutoff.
- LENGTH is per-subject planned observation; PLNTRDUR is planned whole-trial calendar
  duration; PTRTDUR is planned treatment; TRGFUDUR is target follow-up.
- FCNTRY requires the CT definition's IRB-approved planned facility-country evidence.
  A tentative country list or sponsor headquarters is insufficient.
- Actual biospecimen retention and actual ECG processing need study-data evidence;
  protocol intent does not establish actual execution.
- RANDQT derives from planned investigationally exposed subjects divided by planned
  total subjects in the same population, never from arm count alone. The denominator
  must be positive; precision/rounding policy cannot be guessed.
- Multiple objectives/outcomes retain objective, outcome, time and analysis identities.
  Dose/regimen, contacts, cutoffs, citations and URL pairs have explicit grouping keys.
  Missing association keys are review exceptions, not fabricated IDs.

Decimal quantities and ratios, ISO 8601 durations and sponsor input are additive
typed profile contracts. Step 0 does not implement their study-level normalizers,
selection, mapping execution or TS generation; those remain later stages.

## Closed condition inputs

Each condition defines its exact fact key, source, include value and exclude value.
Y/N is used for boolean design assessments; INTERVENTIONAL/OBSERVATIONAL matches
the study-type factual vocabulary; reviewed TRT/CURTRT presence uses present/absent.
Only those two explicit alternatives may drive a conditional branch.

Missing, proposed, conflicting, invalid, or unsupported third values must be
unknown, including under NOT. An arbitrary value unequal to the include value
must not automatically exclude. The future Step 2 boundary must enforce these
documented input domains and review prerequisites before running the predicates.
The hashed catalog carries the contract; `fact_input_contracts.json` is its readable
run-bundle projection. There is no approval import or study selection engine here.

RANDOM=N still includes RANDOM with a negative response. It can exclude RANDQT or
STRATFCT after validated negative randomization assessment. Healthy subjects alone
do not exclude INDIC, and ADDON alone does not determine CURTRT. Planned specimen
collection alone does not establish actual BRDNAIND applicability.

## Remaining source findings and human gate

The public CDISC SDTMIG v3.4 page, including errata/known issues, was downloaded on
2026-10-26 and is pinned as local HTML. Its download is a recorded maintenance
acquisition; ordinary builds only use the stored bytes. Capturing the page is not
a claim that its corrections have received qualified applicability review.

The user selected the pinned 2026-09-25 CT to handle the nine source differences.
Profile v3 opts into `selected_ct_authoritative`; existing recipes retain the
strict behavior, and v2.2 and legacy assets are unchanged. This selects the saved
release, without fetching a newer release or repairing a historical study workbook.

The nine raw findings remain unchanged in `source_discrepancies.json`.
`source_resolutions.csv` and `.json` record all nine dispositions, exact CT source
locations and the user-authorized precedence policy. There are zero untreated
source differences in `unresolved_source_discrepancies.json`.

| Parameter | Disposition under the selected CT |
| --- | --- |
| BRIND (two findings) | Use C164620; exact parameter code and paired label agree; verify response pairs separately |
| FDATCHSP (two) | Replace CNEW with published C228251 and C228252 using unique exact values in C160926 |
| INTTYPE | Omit the OTHER/C17649 association absent from C99078; unmatched study values still require review |
| SDTIGVER (two) | Use canonical 3.1.1 and 3.1.2 for the same verified codes |
| SDTMDVER | Use CT value 1.0 for C189636; the original Excel cell is numeric, not an approved text alias |
| TBPRD | Retain the CT parameter with explicit manual/external handling; infer no response codelist |

The result contains 133 parameters and 282 exact response mappings. Handling TBPRD
does not supply an external dictionary or authorize automatic coding. The original
findings' messages describe the raw comparison; their current dispositions are in
the separate resolution artifacts.

Content validation now reports only the draft-review gate:

```sh
uv run --locked trial-ts standards validate \
  --profile outputs/step0-clinical-review-2026-09-25-v3/profile \
  --content outputs/step0-clinical-review-2026-09-25-v3/content.json \
  --allow-draft-standards
```

Expected exit: 0 with this explicit draft opt-in; the blocking `DRAFT_PROFILE`
warning remains and `review_manifest.json` still reports `step0_ready: false`.
Passing validation does not approve the profile. Qualified review of the complete
project policies,
source disagreements, exception handling and standards applicability is still
required. Do not merge Step 1 or create the Skill before the Step 0 gate passes.

Tests use synthetic standards, cover each parameter's positive/negative/unknown
condition contract, specific clinical edge cases, coverage/hash/authority failures,
repeat grouping and immutable legacy compatibility. The test-only contract
interpreter is not a delivered runtime selection engine. Full-source maintenance
builds and byte comparisons are separate from the network-free unit suite.
