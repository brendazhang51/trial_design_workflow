# Trial Design Workflow

**From a study protocol to a traceable Trial Summary draft.**

Built for statistical programmers working on the CDISC SDTM Trial Summary (TS)
domain. The project brings protocol review, parameter selection, terminology
mapping and QC into one workflow, with the evidence and reasoning kept alongside
the draft for programmer review.

The end-to-end workflow is being developed in stages. **The v3 Master Lookup is
approved, Study Facts extraction is available as a development workflow, and
parameter selection, TS generation and the new review workbook are next.**

## How the workflow works

[![Trial Design Workflow: an authorized protocol becomes evidence-linked Study Facts, followed by rule-based parameter selection, TS mapping and generation, and QC with Excel review. The approved Master Lookup supplies the selection and mapping rules. Step 1 is in development; Steps 2–4 are planned.](docs/ts-workflow.svg)](docs/ts-workflow.svg)

| Step | What happens | What you get |
| --- | --- | --- |
| **0 · Establish the rules** | Use the approved Master Lookup to define each candidate parameter's meaning, applicability, value source and terminology. | A shared, versioned basis for programming decisions. |
| **1 · Read the protocol** | Extract study facts and retain the exact supporting text and page location. Keep conflicting statements and missing information visible. | Study Facts with evidence and review findings. |
| **2 · Select parameters** | Evaluate the facts against the lookup rules. Record why a parameter applies, does not apply, or needs more information. | A study-specific selection and an audit of every candidate parameter. |
| **3 · Build TS records** | Map supported values using the selected terminology and documented derivations, then assign a stable record order. | Reproducible TS record proposals with traceability. |
| **4 · Check and review** | Check structure, terminology, consistency and evidence. Present unresolved issues first. | A TS draft, an exception list and supporting review material. |

**AI proposes study facts. Versioned rules determine parameter selection and value
mapping. Statistical programmers review the interpretation and the draft.**

## What this looks like in practice

Suppose a protocol states: *“A total of 120 participants are planned for enrollment.”*

The extraction step retains **120 as a planned-enrollment proposal**, together with
that exact quote and its page location. The later selection and mapping steps
assess its use for `PLANSUB` under the lookup's definition and study context.

If another section gives a different number, both statements stay available for
review. If actual enrollment is unavailable, it remains a separate information
request; the planned count does not fill `ACTSUB`.

The same approach applies to study phase, randomization, blinding, interventions,
objectives, durations and other study characteristics: keep the source, apply the
relevant rule, and make uncertainty visible.

## What you will review

The planned review workbook brings the following views together. **This new
workbook is part of Step 4 and is not yet available.**

| Sheet | What it helps you answer |
| --- | --- |
| **Exceptions** | What needs attention, and what information is needed next? |
| **TS_Draft** | What TS records have been proposed for this study? |
| **Parameter_Audit** | Why was each candidate parameter included, excluded or left unresolved? |
| **Study_Facts** | What was extracted, and where are the conflicting or missing facts? |
| **Evidence** | Which exact source statements support the proposals? |
| **Run_Info** | Which documents, standards and rules were used? |

Saved facts, decisions and QC findings will accompany the workbook so the same
inputs can reproduce the same logical results. Workbook edits are review
annotations; they do not automatically approve values or change the saved inputs.

## Where the project stands

| Component | Current status |
| --- | --- |
| **Master Lookup · Step 0** | **Approved v3 baseline.** Covers all 133 candidate parameters in the selected CT release, with 282 exact response mappings and a separate 11-variable TS metadata table. |
| **Study Facts · Step 1** | **Development workflow available.** Prepare a local protocol, validate a saved AI response or run the limited regex extractor, inspect findings, and replay the results. |
| **Parameter selection · Step 2** | Planned. |
| **TS mapping and generation · Step 3** | Planned. |
| **QC and the new Excel review workbook · Step 4** | Planned. |

The lookup covers the full candidate universe for review; **133 candidates does
not mean 133 parameters belong in every study**. Approval of the lookup establishes
the rules baseline; extracted study facts and study-specific values retain their
own review states.

Study A is the development case. Study B remains held out for later evaluation.
Clinical extraction accuracy has not yet been established against a frozen,
human-reviewed reference set.

## Try the current workflow

1. **Explore the approved rules.** Read the [Master Lookup guide](docs/step-0-full-lookup.md).
   After local setup, the readable lookup is in
   `outputs/clinical-ts-v3/review/master_lookup_review.md` (also available as CSV).
2. **Prepare an authorized protocol.** Follow the [Study Facts guide](docs/step-1-study-facts.md)
   to retain the document's page text and prepare an extraction request.
3. **Extract and inspect facts.** Supply a saved response from an explicitly
   authorized AI session, or choose the limited regex fallback. Review the fact
   proposals, exact evidence, conflicts and unsupported-source findings.
4. **Replay the run.** Check that the saved inputs reproduce the same facts before
   using them in further programming work.

The current package does not call a model API or upload your protocol. You choose
and authorize the extraction session separately. Today, the new workflow produces
Study Facts and review findings; it does not yet produce study-specific TS records
or the new Excel workbook.

An [earlier candidate-workbook workflow](docs/history/legacy-workbook.md) remains
available for compatibility. It produces the historical 129-row candidate workbook
and is separate from the staged workflow described above.

## Scope and further reading

The first deliverable is a **TS draft for programmer review**, using SDTM 2.0,
SDTMIG 3.4 and the selected CT 2026-09-25 release. The current scope is TS only,
without a regulator-specific submission profile. Other Trial Design domains,
submission-ready XPT and Define-XML are outside this MVP.

- [Setup and developer notes](docs/development.md)
- [Approved Master Lookup and build instructions](docs/step-0-full-lookup.md)
- [Study Facts extraction and replay](docs/step-1-study-facts.md)
- [Known limitations and remaining work](docs/known-limitations.md)
- [Documentation index](docs/README.md)
