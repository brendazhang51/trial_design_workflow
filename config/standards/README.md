# Standards recipes

The current approved baseline is
[`clinical-review-2026-09-25-v3.json`](clinical-review-2026-09-25-v3.json), profile
version 3. It pins the local sources and
[`ts-parameter-policies-v2.json`](ts-parameter-policies-v2.json) by SHA-256 and opts
into the user-selected `selected_ct_authoritative` source-precedence policy.
The recipe reproduces the historical draft. The user explicitly approved unchanged
v3 on 2026-10-27. The separate
[`clinical-review-2026-09-25-v3-approval.json`](clinical-review-2026-09-25-v3-approval.json)
records that decision against both profile and review-content hashes.
[`active-profile.json`](active-profile.json) pins the recipe/approval hashes and
selects `outputs/clinical-ts-v3/` for the normal workflow. No draft opt-in is needed
for this approved package. `trial-ts standards promote` applies the saved decision
to a newly built v3 draft; source gaps or changed content still block promotion.

Earlier recipes remain for reproducibility:

| Recipe | Purpose |
| --- | --- |
| `clinical-review-2026-09-25.json` | First eight vertical examples; other parameters retain explicit content gaps |
| `clinical-review-2026-09-25-v2.json` | Full catalog / profile 2.2 with strict source-difference blocking |
| `clinical-review-2026-09-25-v3.json` | Full catalog / profile 3 with nine recorded CT-based dispositions |

Do not delete these versioned inputs as unused examples or edit the frozen 2025
assets. A policy change requires a new recipe/profile revision and updated hash;
old generated packages remain unchanged. Package version 0.5.0 and profile version
3 identify different things.

See [build and review instructions](../../docs/step-0-full-lookup.md) and
[open notes](../../docs/known-limitations.md). Authorized standard bytes and
generated packages are local prerequisites, excluded from Git.
