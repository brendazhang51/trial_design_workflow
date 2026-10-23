"""Provider-independent review orchestration and a deterministic regex baseline."""

import re
from typing import Protocol

from ..engine import canonical_json, sha256
from ..schemas import Evidence, StudyFact
from .models import (
    CandidateBatch,
    EvidenceSpan,
    ExtractionFinding,
    ExtractionOutput,
    ExtractionRules,
    FactCandidate,
    FieldReview,
    ParsedDocument,
)


class FactProvider(Protocol):
    """Future model adapters return untrusted proposals through this same boundary."""

    name: str
    version: str

    def propose(self, document: ParsedDocument, rules: ExtractionRules) -> object: ...


def normalize(value: str, method: str) -> str:
    if method == "integer":
        value = value.strip()
        if not re.fullmatch(r"(?:\d{1,3}(?:,\d{3})+|\d+)", value):
            raise ValueError("Integer normalization requires an unambiguous numeric capture")
        return str(int(value.replace(",", "")))
    return " ".join(value.split())


class RuleBasedProvider:
    name = "regex-baseline"
    version = "1"

    def propose(self, document: ParsedDocument, rules: ExtractionRules) -> object:
        candidates = []
        for rule in sorted(rules.rules, key=lambda r: r.field_key):
            grouped: dict[str, dict] = {}
            for page in document.pages:
                matches = {}
                for pattern in rule.patterns:
                    for match in re.finditer(pattern, page.text):
                        value = normalize(match["value"], rule.normalization)
                        if value:
                            matches[(match.start(), match.end(), value)] = match[0]
                for (start, end, value), quote in sorted(matches.items()):
                    group = grouped.setdefault(value, {"evidence": [], "spans": []})
                    group["evidence"].append(
                        Evidence(
                            document_id=document.source.artifact.artifact_id,
                            pdf_page_index=page.pdf_page_index,
                            printed_page=page.printed_page,
                            quote=quote,
                            extraction_status="proposed",
                        )
                    )
                    group["spans"].append(
                        EvidenceSpan(
                            pdf_page_index=page.pdf_page_index,
                            start=start,
                            end=end,
                        )
                    )
            for value, group in sorted(grouped.items()):
                identifier = (
                    rule.field_key
                    + ":"
                    + sha256(
                        canonical_json(
                            {
                                "document": document.source.artifact.sha256,
                                "document_id": document.source.artifact.artifact_id,
                                "field": rule.field_key,
                                "rule": rule.rule_id,
                                "value": value,
                            }
                        ).encode()
                    )[:20]
                )
                candidates.append(
                    FactCandidate(
                        candidate_id=identifier,
                        field_key=rule.field_key,
                        rule_id=rule.rule_id,
                        fact=StudyFact(
                            fact_id=identifier,
                            raw_statement=group["evidence"][0].quote,
                            proposed_value=value,
                            evidence=tuple(group["evidence"]),
                        ),
                        spans=tuple(group["spans"]),
                    )
                )
        return {"candidates": [c.model_dump(mode="json") for c in candidates]}


def extract_facts(
    document: ParsedDocument,
    rules: ExtractionRules,
    provider: FactProvider | None = None,
) -> ExtractionOutput:
    provider = provider or RuleBasedProvider()
    # A provider cannot bypass the schema/grounding boundary by returning model instances.
    raw_batch = provider.propose(document, rules)
    if not isinstance(raw_batch, dict):
        raise ValueError("Extraction provider must return a candidate object")
    batch = CandidateBatch.model_validate_json(canonical_json(raw_batch))
    candidates = tuple(
        sorted(
            batch.candidates,
            key=lambda c: (
                c.field_key,
                c.fact.proposed_value,
                c.candidate_id,
            ),
        )
    )
    reviews, findings = [], list(document.findings)
    findings.append(
        ExtractionFinding(
            code="PAGE_BOUNDARY_LIMIT",
            severity="info",
            message="Patterns operate within each page; inspect cross-page and table content.",
        )
    )
    for rule in sorted(rules.rules, key=lambda r: r.field_key):
        matches = [c for c in candidates if c.field_key == rule.field_key]
        reason = (
            "missing"
            if not matches
            else "single_candidate"
            if len(matches) == 1
            else "conflicting_candidates"
        )
        rationale = {
            "missing": "No match; inspect the protocol. Absence is not non-applicability.",
            "single_candidate": "Candidate requires human verification against source and context.",
            "conflicting_candidates": "Different values found; resolve context/version manually.",
        }[reason]
        reviews.append(
            FieldReview(
                field_key=rule.field_key,
                reason=reason,
                candidate_ids=tuple(c.candidate_id for c in matches),
                rationale=rationale,
            )
        )
        findings.append(
            ExtractionFinding(
                code={
                    "missing": "FACT_MISSING",
                    "single_candidate": "FACT_REVIEW_REQUIRED",
                    "conflicting_candidates": "FACT_CONFLICT",
                }[reason],
                severity="warning",
                field_key=rule.field_key,
                message=rationale,
            )
        )
    return ExtractionOutput(
        schema_version="1",
        document=document,
        rules=rules,
        provider_name=provider.name,
        provider_version=provider.version,
        candidates=candidates,
        review_queue=tuple(reviews),
        findings=tuple(findings),
    )
