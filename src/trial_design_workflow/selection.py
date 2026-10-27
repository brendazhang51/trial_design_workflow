"""Step 2: three-valued applicability evaluation; absence never implies exclusion."""

from pathlib import Path
from typing import Literal, Self

from pydantic import Field, model_validator

from . import __version__
from .schemas import Digest, Model, Text
from .serialization import canonical_json, sha256
from .standards.catalog import ParameterPolicyCatalog
from .standards.models import Predicate, SourceRef, StandardsProfile
from .standards.profile import ProfileError, load_profile, safe_path
from .standards.review import ReviewContent, validate_content
from .standards.validation import content_digest, normalized_payload, validate_profile
from .study_context import (
    ContextFact,
    SourceType,
    StudyContext,
    context_digest,
    digest,
    normalize_context,
)


class ProcessingFinding(Model):
    finding_id: Digest
    code: Text
    severity: Literal["error", "warning", "info"]
    blocking: bool
    status: Literal["open"] = "open"
    parameter: Text | None
    fact_ids: tuple[Text, ...] = ()
    message: Text
    remediation: Text
    authority_refs: tuple[SourceRef, ...] = ()


def issue(code, parameter, message, *, fact_ids=(), refs=(), severity="warning", blocking=True):
    payload = dict(
        code=code,
        parameter=parameter,
        message=message,
        fact_ids=tuple(sorted(fact_ids)),
        authority_refs=tuple(r.model_dump(mode="json") for r in refs),
        severity=severity,
        blocking=blocking,
        remediation="Review the sources and inputs; supply documented corrections and rerun.",
    )
    return ProcessingFinding(finding_id=sha256(canonical_json(payload).encode()), **payload)


class InputDomain(Model):
    fact_key: Text
    values: tuple[Text, ...] = Field(min_length=1)
    source_type: SourceType


class DomainCatalog(Model):
    schema_version: Literal["1"]
    domains: tuple[InputDomain, ...]


class RuntimeProfile(Model):
    profile: StandardsProfile
    content: ReviewContent | None
    policy_source_id: Text | None
    policy_document: str | None

    @model_validator(mode="after")
    def pinned_inputs(self) -> Self:
        if (self.policy_source_id is None) != (self.policy_document is None):
            raise ValueError("policy source and saved bytes must be paired")
        if self.policy_source_id:
            source = next(
                (s for s in self.profile.sources if s.source_id == self.policy_source_id), None
            )
            if source is None or sha256(self.policy_document.encode()) != source.sha256:
                raise ValueError("condition-domain policy is not hash-pinned in this profile")
        if self.content and self.content.profile_content_sha256 != content_digest(self.profile):
            raise ValueError("TS variable metadata must bind to this profile")
        return self

    def domains(self) -> dict[str, InputDomain]:
        rows = []
        if self.policy_source_id == "parameter-policies":
            catalog = ParameterPolicyCatalog.model_validate_json(self.policy_document)
            if {p.code for p in catalog.parameters} != {
                p.tsparmcd for p in self.profile.parameters
            }:
                raise ValueError("policy catalog does not cover this profile")
            rows = [
                InputDomain(
                    fact_key=c.fact_key,
                    values=(c.include_value, c.exclude_value),
                    source_type=c.source_requirement,
                )
                for c in catalog.conditions.values()
                if c.mode == "conditional"
            ]
        elif self.policy_source_id == "condition-input-domains":
            rows = list(DomainCatalog.model_validate_json(self.policy_document).domains)
        elif self.policy_source_id is not None:
            raise ValueError("unsupported condition-domain source")
        domains = {}
        for row in rows:
            if row.fact_key in domains and (
                set(row.values) != set(domains[row.fact_key].values)
                or row.source_type != domains[row.fact_key].source_type
            ):
                raise ValueError("contradictory condition input domains")
            domains[row.fact_key] = row
        return domains


def load_runtime(directory: Path, *, allow_draft=False) -> RuntimeProfile:
    profile = load_profile(directory, allow_draft=allow_draft)
    content_path = directory.parent / "content.json"
    content = (
        ReviewContent.model_validate_json(content_path.read_bytes())
        if content_path.exists()
        else None
    )
    source = next(
        (
            s
            for s in profile.sources
            if s.source_id in {"parameter-policies", "condition-input-domains"}
        ),
        None,
    )
    runtime = RuntimeProfile(
        profile=profile,
        content=content,
        policy_source_id=source.source_id if source else None,
        policy_document=safe_path(directory, source.local_filename).read_bytes().decode("utf-8")
        if source
        else None,
    )
    check_runtime(runtime, allow_draft=allow_draft)
    return runtime


def check_runtime(runtime: RuntimeProfile, *, allow_draft=False) -> RuntimeProfile:
    runtime = RuntimeProfile.model_validate_json(runtime.model_dump_json())
    report = validate_profile(runtime.profile, allow_draft=allow_draft)
    if not report.valid:
        raise ProfileError(report)
    runtime.domains()
    if runtime.profile.manifest.scope == "clinical":
        if runtime.content is None:
            raise ValueError(
                "clinical processing requires the bound review content and TS metadata"
            )
        content_report = validate_content(runtime.profile, runtime.content)
        if any(f.blocking and f.code != "DRAFT_PROFILE" for f in content_report.findings):
            raise ProfileError(content_report)
    return runtime


def runtime_digest(runtime: RuntimeProfile) -> str:
    payload = runtime.model_dump(mode="json")
    payload["profile"] = normalized_payload(runtime.profile)
    if payload["content"]:
        payload["content"]["parameters"].sort(key=lambda p: p["tsparmcd"])
        payload["content"]["variables"].sort(key=lambda v: v["order"])
    return sha256(canonical_json(payload).encode())


class PredicateTrace(Model):
    op: Text
    fact_key: Text | None = None
    rule_id: Text | None = None
    result: bool | None
    reason: Text
    fact_ids: tuple[Text, ...] = ()
    fact_hashes: tuple[Digest, ...] = ()
    children: tuple["PredicateTrace", ...] = ()
    collection_review_sha256: Digest | None = None


class ParameterDecision(Model):
    tsparmcd: Text
    decision: Literal["include", "exclude", "manual_assessment", "needs_external_source", "blocked"]
    rule_id: Text
    rule_version: Text
    predicate: PredicateTrace
    rationale: Text
    authority_refs: tuple[SourceRef, ...]
    min_records: int
    max_records: int | None
    repeat_keys: tuple[Text, ...]
    group_keys: tuple[Text, ...]
    input_fact_ids: tuple[Text, ...]
    input_fact_hashes: tuple[Digest, ...]
    missing_prerequisites: tuple[Text, ...]
    exception_codes: tuple[Text, ...]


class ParameterSelection(Model):
    schema_version: Literal["1"]
    algorithm_version: Literal["three-valued-selection-v1"]
    software_version: Text
    profile_id: Text
    profile_version: Text
    profile_content_sha256: Digest
    study_context_sha256: Digest
    runtime_metadata_sha256: Digest
    decisions: tuple[ParameterDecision, ...]
    findings: tuple[ProcessingFinding, ...]

    @model_validator(mode="after")
    def unique(self) -> Self:
        if len({d.tsparmcd for d in self.decisions}) != len(self.decisions):
            raise ValueError("duplicate parameter decisions")
        return self


def reviewed_values(facts: list[ContextFact], required_source: str | None = None):
    if not facts:
        return None, "FACT_MISSING"
    if any(f.status != "reviewed" for f in facts):
        return None, "FACT_NOT_REVIEWED"
    if required_source and any(f.source_type != required_source for f in facts):
        return None, "FACT_SOURCE_MISMATCH"
    values = {(f.reviewed_value, f.null_flavor, f.unit) for f in facts}
    if len(values) != 1:
        return None, "FACT_CONFLICT"
    return next(iter(values))[0], "REVIEWED"


def evaluate_predicate(
    predicate: Predicate | None, context: StudyContext, runtime: RuntimeProfile, *, stack=()
) -> PredicateTrace:
    if predicate is None:
        return PredicateTrace(
            op="unconditional", result=True, reason="Versioned unconditional rule"
        )
    rules = {r.rule_id: r for r in runtime.profile.applicability_rules}
    op = predicate.op
    if op in {"all", "any", "not"}:
        children = tuple(
            evaluate_predicate(p, context, runtime, stack=stack) for p in predicate.children
        )
        values = [c.result for c in children]
        if op == "not":
            result = None if values[0] is None else not values[0]
        elif op == "all":
            result = False if False in values else None if None in values else True
        else:
            result = True if True in values else None if None in values else False
        return PredicateTrace(
            op=op, result=result, reason="Three-valued Boolean evaluation", children=children
        )
    if op == "rule_ref":
        if predicate.rule_id in stack or predicate.rule_id not in rules:
            raise ValueError("unknown or circular rule reference")
        rule = rules[predicate.rule_id]
        child = evaluate_predicate(rule.predicate, context, runtime, stack=(*stack, rule.rule_id))
        if rule.predicate is None:
            result = (
                True if rule.on_true == "include" else False if rule.on_true == "exclude" else None
            )
        else:
            result = child.result
        return PredicateTrace(
            op=op,
            rule_id=rule.rule_id,
            result=result,
            reason="Referenced predicate",
            children=(child,),
        )
    facts = sorted(
        [f for f in context.facts if f.fact_key == predicate.fact_key], key=lambda f: f.fact_id
    )
    ids = tuple(f.fact_id for f in facts)
    hashes = tuple(digest(f) for f in facts)
    domain = runtime.domains().get(predicate.fact_key)
    value, reason = reviewed_values(facts, domain.source_type if domain else None)
    result = None
    if op == "fact_count":
        complete = next(
            (c for c in context.complete_collections if c.fact_key == predicate.fact_key), None
        )
        if complete is None:
            reason = "COLLECTION_COMPLETENESS_REQUIRED"
        elif any(f.status != "reviewed" for f in facts):
            reason = "FACT_NOT_REVIEWED"
        elif domain and any(f.source_type != domain.source_type for f in facts):
            reason = "FACT_SOURCE_MISMATCH"
        else:
            keys = [
                canonical_json(f.cardinality_key) for f in facts if f.reviewed_value is not None
            ]
            if any(
                reviewed_values([f for f in facts if canonical_json(f.cardinality_key) == key])[1]
                != "REVIEWED"
                for key in set(keys)
            ):
                reason = "FACT_CONFLICT"
            else:
                result = len(set(keys)) == predicate.value
                reason = "Reviewed complete collection"
    elif reason == "REVIEWED":
        if op == "fact_status":
            result = predicate.value == "reviewed"
        elif op == "fact_present":
            result = value is not None
        elif domain and value not in domain.values:
            reason = "INVALID_CONDITION_DOMAIN"
        elif op == "fact_equals":
            result = value == predicate.value if domain or value == predicate.value else None
            if result is None:
                reason = "CLOSED_DOMAIN_REQUIRED"
        elif op == "fact_in":
            result = value in predicate.values if domain or value in predicate.values else None
            if result is None:
                reason = "CLOSED_DOMAIN_REQUIRED"
    return PredicateTrace(
        op=op,
        fact_key=predicate.fact_key,
        result=result,
        reason=reason,
        fact_ids=ids,
        fact_hashes=hashes,
        collection_review_sha256=digest(complete)
        if op == "fact_count" and complete is not None
        else None,
    )


def trace_leaves(trace: PredicateTrace):
    if trace.fact_key:
        yield trace
    for child in trace.children:
        yield from trace_leaves(child)


def select_parameters(
    context: StudyContext, runtime: RuntimeProfile, *, allow_draft=False
) -> ParameterSelection:
    context = normalize_context(StudyContext.model_validate_json(context.model_dump_json()))
    runtime = check_runtime(runtime, allow_draft=allow_draft)
    profile = runtime.profile
    rules = {r.rule_id: r for r in profile.applicability_rules}
    derivations = {d.derivation_id: d for d in profile.derivations}
    groups = {g.rule_id: g for g in profile.grouping_rules}
    decisions, findings = [], []
    for p in sorted(profile.parameters, key=lambda p: p.tsparmcd):
        rule = rules[p.applicability_rule_id]
        trace = evaluate_predicate(rule.predicate, context, runtime, stack=(rule.rule_id,))
        decision = (
            rule.on_unknown
            if trace.result is None
            else rule.on_true
            if trace.result
            else rule.on_false
        )
        leaves = list(trace_leaves(trace))
        codes = {leaf.reason for leaf in leaves if leaf.result is None}
        missing = {leaf.fact_key for leaf in leaves if leaf.result is None}
        if p.parameter_status != "active" or p.automation_level == "unsupported":
            decision = "blocked"
            codes.add("PARAMETER_UNSUPPORTED")
        needed = set(derivations[p.derivation_id].fact_keys)
        relevant = [
            f
            for f in context.facts
            if f.fact_key in needed or f.fact_id in {i for leaf in leaves for i in leaf.fact_ids}
        ]
        if decision == "include":
            for key in sorted(needed):
                matching = [f for f in relevant if f.fact_key == key]
                if not matching or any(f.status != "reviewed" for f in matching):
                    missing.add(key)
                    codes.add("VALUE_SOURCE_MISSING" if not matching else "VALUE_NOT_REVIEWED")
        if decision in {"manual_assessment", "needs_external_source", "blocked"}:
            codes.add("APPLICABILITY_" + decision.upper())
        for code in sorted(codes):
            findings.append(
                issue(
                    code,
                    p.tsparmcd,
                    "Applicability or value prerequisites require review.",
                    fact_ids=tuple(f.fact_id for f in relevant),
                    refs=rule.authority_refs,
                )
            )
        relevant = sorted(relevant, key=lambda f: f.fact_id)
        decisions.append(
            ParameterDecision(
                tsparmcd=p.tsparmcd,
                decision=decision,
                rule_id=rule.rule_id,
                rule_version=rule.version,
                predicate=trace,
                rationale=rule.explanation + " Evaluated outcome: " + decision + ".",
                authority_refs=rule.authority_refs,
                min_records=p.min_records,
                max_records=p.max_records,
                repeat_keys=p.repeat_key,
                group_keys=groups[p.tsgrpid_rule_id].fact_keys if p.tsgrpid_rule_id else (),
                input_fact_ids=tuple(f.fact_id for f in relevant),
                input_fact_hashes=tuple(digest(f) for f in relevant),
                missing_prerequisites=tuple(sorted(missing)),
                exception_codes=tuple(sorted(codes)),
            )
        )
    for f in validate_profile(profile, allow_draft=allow_draft).findings:
        findings.append(issue(f.code, None, f.message, severity=f.severity, blocking=f.blocking))
    return ParameterSelection(
        schema_version="1",
        algorithm_version="three-valued-selection-v1",
        software_version=__version__,
        profile_id=profile.manifest.profile_id,
        profile_version=profile.manifest.profile_version,
        profile_content_sha256=content_digest(profile),
        study_context_sha256=context_digest(context),
        runtime_metadata_sha256=runtime_digest(runtime),
        decisions=tuple(decisions),
        findings=tuple(sorted(findings, key=lambda f: f.finding_id)),
    )
