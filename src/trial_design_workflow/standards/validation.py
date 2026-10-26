"""Cross-asset integrity and approval gates. No network or rule execution."""

from collections.abc import Iterable

from ..serialization import canonical_json, sha256
from .models import Predicate, ProfileFinding, SourceRef, StandardsProfile, ValidationReport


def content_digest(profile: StandardsProfile) -> str:
    """Bind signoff to logical content, excluding packaging hashes and signoff itself."""
    payload = normalized_payload(profile)
    for key in ("status", "signoff", "output_hashes"):
        payload["manifest"].pop(key)
    return sha256(canonical_json(payload).encode())


def normalized_payload(profile: StandardsProfile) -> dict:
    payload = profile.model_dump(mode="json")
    keys = {
        "sources": lambda r: r["source_id"],
        "parameters": lambda r: r["tsparmcd"],
        "applicability_rules": lambda r: r["rule_id"],
        "value_profiles": lambda r: r["value_profile_id"],
        "derivations": lambda r: r["derivation_id"],
        "grouping_rules": lambda r: r["rule_id"],
        "terminology": lambda r: (r["codelist"], r["code"]),
        "value_maps": lambda r: (r["value_map_id"], r["input_value"]),
    }
    for name, key in keys.items():
        payload[name].sort(key=key)
    payload["fact_keys"].sort()
    return payload


def predicates(root: Predicate | None) -> Iterable[Predicate]:
    if root is not None:
        yield root
        for child in root.children:
            yield from predicates(child)


def validate_profile(
    profile: StandardsProfile,
    *,
    allow_draft: bool = False,
) -> ValidationReport:
    findings: list[ProfileFinding] = []

    def finding(code: str, location: str, message: str, *, warning: bool = False) -> None:
        findings.append(
            ProfileFinding(
                code=code,
                severity="warning" if warning else "error",
                blocking=True,
                location=location,
                message=message,
            )
        )

    def unique(rows: Iterable, key, name: str) -> None:
        seen = set()
        for row in rows:
            identity = key(row)
            if identity in seen:
                finding("DUPLICATE_IDENTIFIER", name, f"Duplicate identifier: {identity}")
            seen.add(identity)

    for name, key in (
        ("sources", lambda r: r.source_id),
        ("parameters", lambda r: r.tsparmcd),
        ("applicability_rules", lambda r: r.rule_id),
        ("value_profiles", lambda r: r.value_profile_id),
        ("derivations", lambda r: r.derivation_id),
        ("grouping_rules", lambda r: r.rule_id),
        ("terminology", lambda r: (r.codelist, r.code)),
        ("terminology", lambda r: (r.codelist, r.value)),
        ("value_maps", lambda r: (r.value_map_id, r.input_value)),
    ):
        unique(getattr(profile, name), key, name)
    unique(profile.fact_keys, lambda k: k, "fact_keys")
    unique(profile.sources, lambda s: s.local_filename, "sources.local_filename")

    manifest = profile.manifest
    if manifest.status == "draft":
        finding(
            "DRAFT_PROFILE",
            "manifest.status",
            "Draft requires explicit opt-in and review.",
            warning=allow_draft,
        )
    if manifest.scope != "clinical":
        finding(
            "NON_CLINICAL_PROFILE",
            "manifest.scope",
            "Legacy/synthetic profile is not approved for clinical generation.",
            warning=True,
        )

    sources = {s.source_id: s for s in profile.sources}

    def refs(references: tuple[SourceRef, ...], location: str, *, normative: bool) -> None:
        for ref in references:
            source = sources.get(ref.source_id)
            if source is None:
                finding("UNKNOWN_SOURCE", location, f"Unknown source: {ref.source_id}")
            elif normative and manifest.scope == "clinical":
                if source.normative_level == 5 or source.provenance in {"historical", "synthetic"}:
                    finding(
                        "NON_NORMATIVE_RULE",
                        location,
                        "Historical/synthetic sources cannot establish clinical rules.",
                    )

    for role, selected in manifest.standards.items():
        if selected.status == "missing":
            finding(
                "STANDARDS_INPUT_MISSING",
                f"manifest.standards.{role}",
                selected.reason,
                warning=manifest.status == "draft" and allow_draft,
            )
        elif selected.status == "pinned":
            source = sources.get(selected.source_id)
            if source is None:
                finding("UNKNOWN_SOURCE", f"manifest.standards.{role}", "Unknown selected source.")
            elif selected.version != source.version:
                finding(
                    "SOURCE_VERSION_MISMATCH",
                    f"manifest.standards.{role}",
                    "Selected version differs from source version.",
                )
            elif manifest.scope == "clinical" and (
                source.provenance == "synthetic" or source.normative_level == 5
            ):
                finding(
                    "NON_NORMATIVE_STANDARD",
                    f"manifest.standards.{role}",
                    "Clinical standards require an authoritative source.",
                )

    def fact_reference(key: str | None, location: str) -> None:
        if key is not None and key not in profile.fact_keys:
            finding("UNKNOWN_FACT_KEY", location, f"Unknown fact key: {key}")

    rules = {r.rule_id: r for r in profile.applicability_rules}
    graph: dict[str, set[str]] = {}
    for rule in profile.applicability_rules:
        refs(rule.authority_refs, rule.rule_id, normative=True)
        graph[rule.rule_id] = set()
        for predicate in predicates(rule.predicate):
            fact_reference(predicate.fact_key, rule.rule_id)
            if predicate.rule_id:
                graph[rule.rule_id].add(predicate.rule_id)
                if predicate.rule_id not in rules:
                    finding("UNKNOWN_RULE", rule.rule_id, "Unknown referenced applicability rule.")
    visiting, visited = set(), set()

    def visit(rule_id: str) -> None:
        if rule_id in visiting:
            finding("RULE_CYCLE", rule_id, "Circular applicability rule reference.")
            return
        if rule_id in visited:
            return
        visiting.add(rule_id)
        for target in sorted(graph.get(rule_id, ())):
            visit(target)
        visiting.remove(rule_id)
        visited.add(rule_id)

    for rule_id in sorted(graph):
        visit(rule_id)

    terms = {(t.codelist, t.code): t for t in profile.terminology}
    codelists = {t.codelist for t in profile.terminology}
    ct_release = manifest.standards["ct"].version
    for term in profile.terminology:
        if term.source_id != manifest.standards["ct"].source_id:
            finding(
                "CT_SOURCE_MISMATCH",
                "terminology",
                "CT terms must reference the explicitly selected snapshot source.",
            )
        if term.release != ct_release:
            finding("CT_RELEASE_MISMATCH", "terminology", "Term release differs from selected CT.")
        refs(
            (SourceRef(source_id=term.source_id, locator=term.codelist),),
            "terminology",
            normative=False,
        )

    values = {v.value_profile_id: v for v in profile.value_profiles}
    for value_profile in profile.value_profiles:
        refs(value_profile.authority_refs, value_profile.value_profile_id, normative=True)
        if value_profile.response_codelist and value_profile.response_codelist not in codelists:
            finding(
                "UNKNOWN_CODELIST",
                value_profile.value_profile_id,
                "Response codelist is absent from the pinned snapshot.",
            )
        for flavor in value_profile.allowed_null_flavors:
            if not any(
                t.codelist == "NULLFLAVOR" and t.value == flavor and t.status == "active"
                for t in profile.terminology
            ):
                finding(
                    "UNVERIFIED_NULL_FLAVOR",
                    value_profile.value_profile_id,
                    "Null flavor has no active pinned terminology term.",
                )

    for derivation in (*profile.derivations, *profile.grouping_rules):
        refs(derivation.authority_refs, "derivations", normative=True)
        for key in derivation.fact_keys:
            fact_reference(key, "derivations")

    map_ids = {m.value_map_id for m in profile.value_maps}
    for mapping in profile.value_maps:
        refs(mapping.authority_refs, mapping.value_map_id, normative=True)
        term = terms.get((mapping.codelist, mapping.term_code))
        if not term or (term.value, term.release, term.status) != (
            mapping.submission_value,
            mapping.release,
            "active",
        ):
            finding(
                "INVALID_VALUE_MAPPING",
                mapping.value_map_id,
                "Mapping must match an exact active pinned code/value/release.",
            )

    derivations = {d.derivation_id: d for d in profile.derivations}
    grouping = {g.rule_id for g in profile.grouping_rules}
    active_codes = {
        t.value for t in profile.terminology if t.codelist == "C66738" and t.status == "active"
    }
    master_codes = {p.tsparmcd for p in profile.parameters if p.parameter_status == "active"}
    if active_codes != master_codes or not active_codes:
        finding(
            "PARAMETER_COVERAGE",
            "parameters",
            f"Active master/CT mismatch: missing={sorted(active_codes - master_codes)}, "
            f"extra={sorted(master_codes - active_codes)}",
        )
    for parameter in profile.parameters:
        code = parameter.tsparmcd
        refs(parameter.authority_refs, code, normative=False)
        fact_reference(parameter.fact_key, code)
        if parameter.ct_release != ct_release:
            finding("CT_RELEASE_MISMATCH", code, "Parameter release differs from selected CT.")
        term = terms.get(("C66738", parameter.concept_code))
        label = terms.get(("C67152", parameter.concept_code))
        if parameter.parameter_status != "not_in_selected_release":
            if not term or not label or term.value != code or label.value != parameter.tsparm:
                finding("PARAMETER_IDENTITY", code, "Code/name/concept does not match pinned CT.")
            elif term.status != parameter.parameter_status or label.status != term.status:
                finding("PARAMETER_STATUS", code, "Parameter lifecycle differs from pinned CT.")
        elif term is not None:
            finding("PARAMETER_STATUS", code, "Parameter marked absent exists in pinned CT.")
        rule = rules.get(parameter.applicability_rule_id)
        derivation = derivations.get(parameter.derivation_id)
        value_profile = values.get(parameter.value_profile_id)
        for target, present in (
            ("applicability rule", rule),
            ("derivation", derivation),
            ("value profile", value_profile),
        ):
            if present is None:
                finding("UNKNOWN_REFERENCE", code, f"Unknown {target} reference.")
        if parameter.tsgrpid_rule_id and parameter.tsgrpid_rule_id not in grouping:
            finding("UNKNOWN_REFERENCE", code, "Unknown grouping rule reference.")
        if parameter.value_map_id and parameter.value_map_id not in map_ids:
            finding("UNKNOWN_REFERENCE", code, "Unknown value map reference.")
        if (
            parameter.parameter_status != "active"
            and rule
            and (rule.on_true == "include" or rule.on_false == "include")
        ):
            finding("INACTIVE_PARAMETER_INCLUDED", code, "Inactive parameter cannot be included.")
        if parameter.automation_level == "deterministic" and derivation and value_profile:
            if derivation.transform == "manual" or value_profile.value_type == "manual":
                finding("AUTOMATION_CONTRACT", code, "Deterministic parameter has a manual value.")
        if parameter.value_map_id and value_profile:
            if any(
                m.codelist != value_profile.response_codelist
                for m in profile.value_maps
                if m.value_map_id == parameter.value_map_id
            ):
                finding("INVALID_VALUE_MAPPING", code, "Value map uses a different codelist.")

    if manifest.signoff and manifest.signoff.content_sha256 != content_digest(profile):
        finding("STALE_PROFILE_SIGNOFF", "manifest.signoff", "Profile changed after review.")
    return ValidationReport(
        profile_id=manifest.profile_id,
        findings=tuple(
            sorted(
                findings,
                key=lambda f: (f.code, f.location, f.message),
            )
        ),
    )
