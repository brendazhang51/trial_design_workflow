"""Pure proposal, approval gating, deterministic ordering and structured QC."""

import hashlib
import json
import unicodedata

from .schemas import Decision, Finding, RunInput, RunOutput, Trace, TSRecord


def canonical_json(value: object) -> str:
    return json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":"))


def sha256(content: bytes) -> str:
    return hashlib.sha256(content).hexdigest()


def propose(run: RunInput) -> tuple[Decision, ...]:
    facts = {fact.fact_id: fact for fact in run.facts}
    proposals = []
    for parameter in sorted(run.registry.parameters, key=lambda p: p.code):
        fact = facts.get(parameter.fact_id)
        value = fact.approved_value if fact else None
        term = None
        if parameter.applicability == "exclude":
            state, reason = "exclude", "Explicit exclusion in the selected synthetic rule."
        elif parameter.automation == "unsupported":
            state, reason = "unsupported", "Parameter requires an implementation outside this MVP."
        elif parameter.automation == "external" or parameter.source_requirement == "external":
            state = "needs_external_source"
            reason = "Documented external-source review is not implemented in Milestone 1."
        elif parameter.automation == "manual":
            state, reason = "needs_review", "Parameter requires manual applicability review."
        elif value is None:
            state, reason = "needs_review", "An approved evidence-bearing fact is required."
        else:
            state, reason = (
                "include",
                "Copy the latest human-approved fact under the selected rule.",
            )
            if parameter.response_codelist:
                term = next(
                    (
                        t
                        for t in run.terminology.terms
                        if t.codelist == parameter.response_codelist and t.value == value
                    ),
                    None,
                )
                if term is None:
                    state, reason = (
                        "needs_review",
                        "Value has no exact mapping in the pinned vocabulary.",
                    )
        proposals.append(
            Decision(
                parameter_code=parameter.code,
                state=state,
                rationale=reason,
                rule_id=parameter.rule_id,
                fact_id=parameter.fact_id,
                value=value,
                term=term,
                terminology_artifact_id=run.terminology.artifact.artifact_id if term else None,
            )
        )
    return tuple(proposals)


def proposal_digest(run: RunInput, decision: Decision) -> str:
    """Bind approval to its proposal AND the material context used to interpret it."""
    fact = next((f for f in run.facts if f.fact_id == decision.fact_id), None)
    parameter = next(p for p in run.registry.parameters if p.code == decision.parameter_code)
    rule = next(r for r in run.registry.rules if r.rule_id == decision.rule_id)
    document_ids = {e.document_id for e in fact.evidence} if fact else set()
    context = {
        "study_id": run.study_id,
        "decision": decision.model_dump(mode="json"),
        "fact": fact.model_dump(mode="json") if fact else None,
        "documents": [
            d.model_dump(mode="json")
            for d in sorted(run.documents, key=lambda d: d.artifact.artifact_id)
            if d.artifact.artifact_id in document_ids
        ],
        "parameter": parameter.model_dump(mode="json"),
        "rule": rule.model_dump(mode="json"),
        "registry_artifact": run.registry.artifact.model_dump(mode="json"),
        "rule_artifacts": [
            a.model_dump(mode="json")
            for a in sorted(run.registry.rule_artifacts, key=lambda a: a.artifact_id)
        ],
        "terminology": run.terminology.model_dump(mode="json"),
        "field_limits": run.registry.field_limits,
        "long_text_policy": run.registry.long_text_policy,
    }
    # Vocabulary row ordering is not semantic.
    context["terminology"]["terms"].sort(key=lambda t: (t["codelist"], t["code"]))
    return sha256(canonical_json(context).encode())


def text_findings(record: TSRecord, run: RunInput) -> list[Finding]:
    findings = []
    for field, limit in run.registry.field_limits.items():
        value = getattr(record, field)
        if len(value) > limit:
            findings.append(
                Finding(
                    code="FIELD_LENGTH",
                    severity="error",
                    parameter_code=record.TSPARMCD,
                    message=(
                        f"{field} exceeds engineering limit {limit}; review without splitting."
                    ),
                )
            )
        if any(unicodedata.category(c).startswith("C") for c in value):
            findings.append(
                Finding(
                    code="FIELD_CHARACTER",
                    severity="error",
                    parameter_code=record.TSPARMCD,
                    message=f"{field} contains a control or format character; correct at source.",
                )
            )
    return findings


def generate(run: RunInput) -> RunOutput:
    proposals = propose(run)
    facts = {f.fact_id: f for f in run.facts}
    parameters = {p.code: p for p in run.registry.parameters}
    reviews = {r.parameter_code: r for r in run.decision_reviews}
    rules = {r.rule_id: r for r in run.registry.rules}
    records, traces = [], []
    findings = [
        Finding(
            code="SYNTHETIC_SCOPE",
            severity="warning",
            message=(
                "Synthetic subset only. Authoritative standards and complete parameter "
                "coverage are not loaded."
            ),
        )
    ]
    for decision in proposals:
        code = decision.parameter_code
        review = reviews.get(code)
        digest = proposal_digest(run, decision)
        if review and review.proposal_sha256 != digest:
            findings.append(
                Finding(
                    code="STALE_APPROVAL",
                    severity="error",
                    parameter_code=code,
                    message="Proposal or source context changed; review the proposal again.",
                )
            )
            continue
        if not review or review.action != "approve":
            findings.append(
                Finding(
                    code="DECISION_REVIEW_REQUIRED",
                    severity="warning",
                    parameter_code=code,
                    message="Human approval required; inspect the proposal and source evidence.",
                )
            )
            continue
        if decision.state != "include":
            findings.append(
                Finding(
                    code="EXCLUDED" if decision.state == "exclude" else "UNRESOLVED_PARAMETER",
                    severity="info" if decision.state == "exclude" else "warning",
                    parameter_code=code,
                    message=f"{decision.state}: {decision.rationale}",
                )
            )
            continue
        fact = facts[decision.fact_id]
        record = TSRecord(
            STUDYID=run.study_id,
            TSSEQ=len(records) + 1,
            TSPARMCD=code,
            TSPARM=parameters[code].label,
            TSVAL=decision.value,
        )
        errors = text_findings(record, run)
        if errors:
            findings.extend(errors)
            continue
        records.append(record)
        traces.append(
            Trace(
                sequence=record.TSSEQ,
                parameter_code=code,
                proposal_sha256=digest,
                fact_id=fact.fact_id,
                evidence=fact.evidence,
                fact_review=fact.reviews[-1],
                decision_review=review,
                rule=rules[decision.rule_id],
                term=decision.term,
                terminology_artifact_id=decision.terminology_artifact_id,
            )
        )
    return RunOutput(
        proposals=proposals,
        records=tuple(records),
        traceability=tuple(traces),
        findings=tuple(findings),
    )


def validate_output(run: RunInput, output: RunOutput) -> tuple[Finding, ...]:
    """Independent invariants plus regeneration catch edits to records and sidecars.

    Structural missing/blank values and invalid sequence types are rejected by
    TSRecord.model_validate before this semantic QC boundary.
    """
    findings = []

    def error(code: str, message: str, parameter: str | None = None) -> None:
        findings.append(
            Finding(code=code, severity="error", message=message, parameter_code=parameter)
        )

    keys = [(r.STUDYID, r.TSPARMCD) for r in output.records]
    if len(keys) != len(set(keys)):
        error(
            "DUPLICATE_LOGICAL_KEY", "One record per parameter is supported; remove duplicate keys."
        )
    sequences = [r.TSSEQ for r in output.records]
    if len(sequences) != len(set(sequences)):
        error("DUPLICATE_SEQUENCE", "Duplicate TSSEQ values require regeneration.")
    ordered = sorted(output.records, key=lambda r: r.TSPARMCD)
    if list(output.records) != ordered or sequences != list(range(1, len(sequences) + 1)):
        error("UNSTABLE_ORDER", "Sort by TSPARMCD and assign contiguous TSSEQ from 1.")
    parameters = {p.code: p for p in run.registry.parameters}
    decisions = {d.parameter_code: d for d in propose(run)}
    for record in output.records:
        code = record.TSPARMCD
        findings.extend(text_findings(record, run))
        parameter = parameters.get(code)
        decision = decisions.get(code)
        if not parameter or record.TSPARM != parameter.label:
            error("PARAMETER_MAPPING", "Code/label does not match the pinned registry.", code)
        if not decision or decision.state != "include" or record.TSVAL != decision.value:
            error(
                "UNAPPROVED_VALUE", "Value is unresolved or differs from the approved fact.", code
            )
        if parameter and parameter.response_codelist:
            if not decision or not decision.term or decision.term.value != record.TSVAL:
                error(
                    "UNVERIFIED_TERMINOLOGY",
                    "Value lacks a verified pinned terminology mapping.",
                    code,
                )
        matches = [
            t
            for t in output.traceability
            if t.sequence == record.TSSEQ and t.parameter_code == code
        ]
        if len(matches) != 1:
            error(
                "MISSING_PROVENANCE",
                "Record requires exactly one matching traceability entry.",
                code,
            )
    expected = generate(run)
    if output.records != expected.records:
        error(
            "REGENERATION_MISMATCH", "Records differ from deterministic regeneration; regenerate."
        )
    if output.traceability != expected.traceability or output.proposals != expected.proposals:
        error(
            "AUDIT_MISMATCH",
            "Proposal or traceability content differs from approved input context.",
        )
    return tuple(findings)
