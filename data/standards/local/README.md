# Authorized local standards

Place original, authorized downloads in these subdirectories (keep original filenames):

- `sdtm-2.0/`: SDTM model.
- `sdtmig-3.4/`: implementation guide, accompanying metadata, errata and known issues.
- `ts-codetable/`: TS codetable and applicable CT relationship files.
- `conformance/`: applicable conformance rules.
- `terminology/`: full original CT release packages; release selection requires review.

Actual files below this directory are ignored by Git. Do not redistribute licensed
material by copying it into tracked assets. A downloaded file is not automatically
an approved source: record publisher, version, original URL, retrieval date if known,
license/reuse restrictions, SHA-256 and exact section/table locations before use.
Never invent unknown dates. Do not put protocols or credentials here.

The current 2025-03-28 legacy assets remain immutable. Local new downloads do not
replace them or silently select a new clinical terminology release.

## Received on 2026-10-26

The user supplied these PDFs. They were moved without changing bytes; SHA-256
receipts are in the ignored `outputs/archive/step0-development-2026-10-26/step0-sources-received-2026-10-26.json`.
Versions below were read from the documents, not inferred solely from filenames.

| Directory | Original filename | Observed version |
| --- | --- | --- |
| `sdtm-2.0/` | `SDTM_v2.0.pdf` | SDTM 2.0 Final, 2021-11-29 |
| `sdtmig-3.4/` | `SDTMIG v3.4-FINAL_2022-07-21 (1).pdf` | SDTMIG 3.4 Final, PDF reissued 2022-07-21 |
| `terminology/` | `SDTM Terminology.pdf` | SDTM CT 2026-09-25 |

Additional files supplied on the same date were copied from Downloads with original
names/bytes preserved. Hash receipts are in the ignored
`outputs/archive/step0-development-2026-10-26/step0-additional-sources-2026-10-26.json`:

- `ts-codetable/TS_Codetable_Mapping_2026-09-25.xlsx`.
- `conformance/SDTM_and_SDTMIG_Conformance_Rules_v2.0.xlsx`.
- `sdtmig-3.4/SDTMIG v3.4-FINAL_2022-07-21.pdf`: the cover also identifies the
  2022-07-21 reissue of v3.4 Final. Its bytes/hash differ from the earlier `(1)`
  file, so both are preserved pending comparison; neither overwrites the other.

These sources are now registered by the hash-pinned clinical v3 recipe. Unknown
original download dates remain unknown, and reuse rights require separate review.
CT 2026-09-25 was explicitly selected for this provisional baseline and source
disposition policy. The user approved unchanged clinical v3 on 2026-10-27; the
normal package records the separate content-bound decision. The immutable 2025
profile and original source bytes remain unchanged. See [the current guide](../../../docs/step-0-full-lookup.md).

Source pages and remaining gaps:

1. Received: TS Codetable Mapping 2026-09-25 under `ts-codetable/`.
   Find **TS Codetable** under Supplemental Files
   on the [CDISC terminology page](https://www.cdisc.org/standards/terminology/controlled-terminology).
2. Received: [SDTM and SDTMIG Conformance Rules v2.0](https://www.cdisc.org/standards/foundational/sdtmig/sdtm-and-sdtmig-conformance-rules-v2-0)
   workbook under `conformance/`. Retain any accompanying guide when available.
3. Captured on 2026-10-26: dated local HTML snapshot of errata/known issues from the
   [official IG page](https://www.cdisc.org/standards/foundational/sdtmig/sdtmig-v3-4).
   Stored as `sdtmig-3.4/sdtmig-v3.4-public-page-2026-10-26.html` and hash-pinned
   in the full-catalog build recipes, including v3. Qualified applicability review is
   still required; page capture itself is not signoff.

Helpful additional format: the same 2026-09-25 SDTM CT release in Excel or text
under `terminology/`, for reliable machine parsing; keep the supplied PDF too.
Do not substitute an older relationship/codetable release without applicability review.
