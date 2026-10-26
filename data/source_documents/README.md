# Study inputs and evaluation

This directory is for local copies of public-source study documents used during
development and evaluation.

Protocol PDFs and extracted text are intentionally ignored by Git. The source
registry in `config/studies.json` records the public URL, study role, download
date, file name, and SHA-256 digest needed to reproduce a local input set.

Do not place a sponsor-confidential study document here merely because this
directory is ignored. Only use documents that the project is authorized to
process.

## Redesign scope

The first output is a programmer-review TS domain draft according to SDTMIG
v3.4, including its required variables. It has no regulator-specific submission
context. Step 0 currently tests profile engineering with fictional inputs and
does not extract or approve facts from either study.

| Study | Catalog key | Registry ID | Role |
| --- | --- | --- | --- |
| STEP 8 | `study_a` | NCT04074161 | Development and reviewed reference-set construction |
| LIMIT-JIA | `study_b` | NCT03841357 | Held-out proof-of-concept evaluation |

`config/studies.json` is the source catalog. Its titles and summaries are
metadata, not provider answers or approved Study Facts. The catalog records
source versions, public URLs, expected filenames, page counts and SHA-256 hashes.
Keep these metadata entries even when old run outputs are archived.

## Review and evaluation procedure

1. Use authorized local protocol bytes and verify the catalog hash before a run.
2. Develop extraction and rules with Study A. Record reviewer decisions and
   errors separately from system proposals.
3. Freeze schemas, prompts, rules and thresholds before inspecting Study B output.
4. Preserve the first Study B evaluation. If it drives changes, label later runs
   as post-evaluation regressions.

Previously generated Study A bundles were moved to
`outputs/archive/pre-redesign/`. They remain local historical artifacts and do
not establish accuracy or approval of the redesigned workflow. The cleanup
does not read Study B's protocol body or change its catalog evaluation role.

Store new run bundles in fresh `outputs/` directories. Never commit protocol
PDFs, extracted quotes, local workbooks or archived study output. Report accuracy
and review-burden metrics only when a reviewed reference set exists.
