# Approved clinical TS baseline: catalog v2 / profile 3

All 133 parameters in the supplied CT 2026-09-25 TSPARMCD universe now have an
explicit project inclusion policy, named fact input, source requirement, value
type/transform, cardinality, grouping choice and exception path. There is no
"use manual for every other parameter" fallback. Full coverage is enforced against
the CT universe; a missing, duplicate or extra policy fails the build.

On **2026-10-27 the user explicitly approved unchanged v3** for the normal MVP
workflow. The profile is `approved_for_mvp`, with the decision bound to the exact
profile and review-content hashes. This supersedes the provisional 2026-10-26
acceptance. No further confirmation of unchanged v3 is pending.

The approval covers this project's non-regulator-specific TS programmer-review
scope. It does not turn every CT parameter into a universal requirement, approve
study-specific facts, or establish submission readiness. The approving actor is
recorded as `repository_user`; no independent credentials are inferred.
See [the approval record](../config/standards/clinical-review-2026-09-25-v3-approval.json),
[active selection](../config/standards/active-profile.json) and
[remaining implementation notes](known-limitations.md).

## Build and inspect

```sh
uv run --locked trial-ts standards stage-clinical \
  --spec config/standards/clinical-review-2026-09-25-v3.json \
  --source-root data/standards/local \
  --before src/trial_design_workflow/assets/standards/legacy-candidates-2025-03-28 \
  --output outputs/step0-clinical-review-2026-09-25-v3
```

The command above reproduces the historical draft. Apply the saved approval to
produce the normal workflow package, preserving the original draft bytes:

```sh
uv run --locked trial-ts standards promote \
  --bundle outputs/step0-clinical-review-2026-09-25-v3 \
  --approval config/standards/clinical-review-2026-09-25-v3-approval.json \
  --output outputs/clinical-ts-v3
uv run --locked trial-ts standards validate \
  --active-profile config/standards/active-profile.json
```

`promote` verifies both content fingerprints and all source/content gates before
recording the already supplied decision; it does not infer an approval from tests.
The normal package lives in `outputs/clinical-ts-v3/`. Its readable CSV/Markdown
and review manifest show the approved status; original policy wording remains
as authored, with its historical proposal language identified as such.
The profile ID retains its historical `review-draft` suffix for exact content
binding; the manifest status, not that identifier's wording, controls eligibility.

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

## Source provenance and recorded approval

The public CDISC SDTMIG v3.4 page, including errata/known issues, was downloaded on
2026-10-26 and is pinned as local HTML. Its download is a recorded maintenance
acquisition; ordinary builds only use the stored bytes. Capturing the page was not itself approval. The subsequent 2026-10-27 decision covers the
pinned v3 content and current source interpretation.

The user selected the pinned 2026-09-25 CT to handle the nine source differences.
The v3 build recipe opts into `selected_ct_authoritative`; existing recipes retain the
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

The normal approved package validates without draft opt-in:

```sh
uv run --locked trial-ts standards validate \
  --profile outputs/clinical-ts-v3/profile \
  --content outputs/clinical-ts-v3/content.json
```

Expected exit: 0 with no findings. The approved review manifest records
`profile_status: approved_for_mvp`, `content_checks_passed: true`,
`blocking_findings: 0`, and `step0_ready: true`. Exporting alone does not create
approval; these states require the existing valid content-bound signoff and no
remaining content/integrity blockers. The original draft package is unchanged
and still needs draft opt-in when inspected for historical replay.

A policy or content change invalidates the prior binding and needs a new decision.
Later-stage code, study-data/external inputs, and reference-based extraction
evaluation remain separate work. Repository Skill packaging still requires all
MVP gates and its own explicit authorization.

Tests use synthetic standards, cover each parameter's positive/negative/unknown
condition contract, specific clinical edge cases, coverage/hash/authority failures,
repeat grouping and immutable legacy compatibility. The test-only contract
interpreter is not a delivered runtime selection engine. Full-source maintenance
builds and byte comparisons are separate from the network-free unit suite.
