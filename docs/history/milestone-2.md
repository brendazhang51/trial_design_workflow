# Milestone 2: initial evidence-grounded PDF extraction

Historical milestone record. The PDF extraction baseline and `trial-extract`
remain in use; references below to the Milestone 1 TS approval engine describe
the retired prototype. See [Step 0](../step-0-master-lookup.md) for current work.

This feature reads an authorized local PDF and proposes structured facts for
human review. It is an initial deterministic baseline, not a complete semantic
extractor or an accuracy claim. The only real study used during development is
Study A. Study B's body text remains unexamined by this implementation run.

## Implemented flow

1. Validate an explicit source document identifier, supplied document version,
   expected SHA-256, and a selected versioned extraction-rule file.
2. Verify PDF bytes against the expected hash; parse those exact bytes with
   `pypdf` in strict mode and plain-text extraction mode.
3. Retain every page's extracted text and zero-based PDF page index. Propose
   printed labels only from explicit supported `Page: N of M` markers, retaining
   marker quotes and offsets. Missing, conflicting, and restarted numbering is
   visible in QC. PDF page number in a viewer is `pdf_page_index + 1`.
4. Execute page-local patterns through the `FactProvider` interface. The
   built-in `regex-baseline` provider groups repeated identical normalized values
   and preserves every matching evidence span.
5. Revalidate provider output, reject provider-created approvals, and verify
   each quote and offset against the identified source page.
6. Emit one review entry per configured field. Missing fields are `missing`;
   one candidate is `single_candidate`; different values are
   `conflicting_candidates`. Every entry remains `needs_review`.

`protocol-facts-v1.json` describes engineering extraction heuristics; its rules
are not CDISC or regulatory rules. They propose title, sponsor study identifier,
version, labelled document date, phase, design paragraph, screened count,
randomized count, treatment weeks, and total individual participation weeks.
The source catalog's titles and design summaries are not used as extraction
answers. The explicitly supplied document version is metadata, not approval of
the version mentioned in a matched page.

## Evidence and normalization

Candidates reuse the existing `StudyFact` and `Evidence` contracts. The raw
statement is the first exact matching quote. System-proposed values are separate
from the original wording; review history is initially empty, so approved values
are absent. Evidence preserves document ID, PDF index, optional printed page,
and proposed extraction status. Each corresponding span stores start-inclusive,
end-exclusive character offsets in the exact extracted page string.

Quotes are exact relative to parser-extracted text, not a guarantee that the
parser reproduced the PDF's visual layout perfectly. Review the PDF when layout,
symbols, columns, tables, or footnotes affect interpretation.

Normalizers either collapse whitespace or convert an unambiguous integer string
(including thousands separators). They do not infer dates, map terminology, select
the latest version, fill missing values, or interpret complex blinding designs.
Other future providers may propose semantic normalization, but quote grounding
alone cannot establish semantic correctness; human approval remains necessary.

Cross-page text is not concatenated into synthetic evidence. Page-local matches
may be absent when a block spans pages. Blank and sparse pages produce findings;
automatic OCR is not implemented. Encrypted, corrupt, and unreadable inputs fail
with structured errors rather than producing apparently successful extraction.
Document-specific body/appendix separation is not implemented; conflicting
versions or total-versus-arm counts require review.

## Review artifacts and reproducibility

| Artifact | Contents |
| --- | --- |
| `extraction.json` | Validated full document pages, selected rules, candidates, review queue and findings |
| `facts.json` | Unapproved `StudyFact` proposals, with candidate IDs as fact IDs |
| `review_queue.json` | All targeted fields and candidate references, including missing fields |
| `qc.json` | Structured page and fact findings with severity and resolution status |
| `manifest.json` | Source/rule/code hashes, parser/provider/Python versions, settings, output hashes and logical extraction hash |

No protocol text is printed by the extraction CLI. Local output bundles are
ignored under `outputs/`; local PDFs and extracted text in `data/source_documents/`
are ignored separately. Public accessibility does not imply permission to
redistribute the PDF or its extracted text. Do not commit local review bundles.

All run directories must be new. Timestamps appear only in manifests. Identical
inputs, rules, implementation, and parser environment produce stable logical
extraction artifacts. Code hashes pin implementation details not contained in
the regex file. Archive source assets and the environment lockfile with a run
when preserving it for long-term reproduction.

CLI status codes follow the existing convention: `0` means a bundle completed
without error findings, not that facts are correct or approved; `1` means a bundle
with error findings; `2` means input, parsing, validation or output failure.

## Relationship to Milestone 1

Extraction outputs share the fact/evidence schemas but are not directly valid
TS-generation inputs. Candidate IDs distinguish conflicting values. Selecting
a candidate, assigning its semantic fact key, retaining approval history, and
mapping it to an authoritative TS registry belong to the review/mapping work.
The existing `RunInput` guard still rejects real-study generation until standards
and terminology support is deliberately added. Do not set a real input's
`synthetic` flag to true to bypass it.

## Validation and remaining work

Automated tests generate PDFs from fictional ASCII protocol content at runtime.
They test extraction, exact offsets, numbering, duplicate evidence, multi-line
text, conflicts, missing values, unsupported cross-page blocks, numeric pitfalls,
provider output validation, hash verification, and repeatable bundle output.
No real protocol content is committed as a test fixture.

Study A is a development smoke test only. Finding candidates for ten fields
does not establish field accuracy or coverage of the complete TS domain. A
reviewed reference set is needed for accuracy measurements. Improve section and
table handling, reviewer workflows, broader semantic extraction and authoritative
parameter mapping incrementally; keep Study B held out until the intended
evaluation baseline is frozen.
