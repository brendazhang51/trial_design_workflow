"""User-directed precedence of a pinned CT snapshot; no latest-version fetching."""

from decimal import Decimal, InvalidOperation
from typing import Literal

from ..schemas import Model, Text
from .acquisition import (
    CodetableParameter,
    CodetableSnapshot,
    ExtractedTerm,
    ResponseLink,
    SourceDiscrepancy,
    verify_codetable,
)
from .models import SourceRef, StandardsProfile
from .review import ReviewContent
from .validation import content_digest

POLICY_ID = "selected-ct-authoritative-v1"
POLICY_RULES = (
    "Use the explicitly pinned CT release for parameter identity and response codes/values.",
    "Rebase a codetable parameter concept only on unique TSPARMCD plus exact paired CT label.",
    "Resolve an absent/placeholder response code only by unique exact value in the same codelist.",
    "Canonicalize whitespace only when stripping boundaries matches the same verified CT code.",
    "Canonicalize numeric spreadsheet version cells only against the same verified CT code "
    "and equal decimal representation; never generalize to text version strings.",
    "Omit old code/value pairs absent from the selected codelist; do not replace OTHER by a guess.",
    "Keep CT-only parameters in audit with manual/external response handling, "
    "not invented codelists.",
    "Keep raw source files/discrepancies and record every disposition; do not approve the profile.",
)


class SourceResolution(Model):
    discrepancy: SourceDiscrepancy
    disposition: Literal[
        "ct_identity_selected",
        "ct_code_from_exact_value",
        "ct_value_canonicalized",
        "response_omitted",
        "ct_only_parameter_manual",
        "parameter_omitted",
        "unresolved",
    ]
    raw_concept_code: Text | None = None
    raw_term_code: Text | None = None
    raw_value: str | None = None
    selected_concept_code: Text | None = None
    selected_term_code: Text | None = None
    selected_value: Text | None = None
    codelist: Text | None = None
    authority_refs: tuple[SourceRef, ...]
    rationale: Text


class ReconciliationResult(Model):
    policy_id: Literal["selected-ct-authoritative-v1"]
    selected_release: Text
    effective_snapshot: CodetableSnapshot
    resolutions: tuple[SourceResolution, ...]

    @property
    def unresolved(self) -> tuple[SourceDiscrepancy, ...]:
        return tuple(r.discrepancy for r in self.resolutions if r.disposition == "unresolved")


def term_ref(term: ExtractedTerm) -> SourceRef:
    return SourceRef(source_id="ct", locator=f"{term.codelist}/{term.code}; PDF pages {term.pages}")


def numeric_equivalent(response: ResponseLink, term: ExtractedTerm) -> bool:
    if response.source_value_kind != "numeric":
        return False
    try:
        return Decimal(response.value) == Decimal(term.value)
    except InvalidOperation:
        return False


def reconcile_codetable(
    snapshot: CodetableSnapshot, terms: tuple[ExtractedTerm, ...]
) -> ReconciliationResult:
    """Produce a derived snapshot, retaining the untouched original as source evidence."""
    lookup = {(t.codelist, t.code): t for t in terms}
    if len(lookup) != len(terms):
        raise ValueError("Duplicate CT concept in codelist")
    identities = {t.value: t for t in terms if t.codelist == "C66738"}
    if len(identities) != sum(t.codelist == "C66738" for t in terms):
        raise ValueError("Ambiguous CT parameter identity")
    identities_changed, responses_changed = {}, {}
    effective = []
    for parameter in snapshot.parameters:
        identity = identities.get(parameter.tsparmcd)
        label = lookup.get(("C67152", identity.code)) if identity else None
        if not identity:
            continue
        # Matching labels establish that a changed concept is still the named parameter.
        identity_safe = label is not None and label.value == parameter.tsparm
        if identity_safe and identity.code != parameter.concept_code:
            identities_changed[parameter.tsparmcd] = (identity, label)
        responses = []
        for response in parameter.responses:
            members = [t for t in terms if t.codelist == response.codelist]
            term = lookup.get((response.codelist, response.term_code))
            exact_values = [
                t for t in terms if t.codelist == response.codelist and t.value == response.value
            ]
            replacement, disposition, rationale = (
                None,
                "unresolved",
                "Source conflict needs review.",
            )
            if term and term.value == response.value:
                responses.append(response)
                continue
            if term and (
                response.value.strip() == term.value or numeric_equivalent(response, term)
            ):
                replacement, disposition = term, "ct_value_canonicalized"
                rationale = "Selected CT supplies the canonical label for the same verified code; "
                rationale += "only source-cell formatting is normalized."
            elif not term and len(exact_values) == 1:
                replacement, disposition = exact_values[0], "ct_code_from_exact_value"
                rationale = "Unique exact value in this selected CT codelist supplies a published "
                rationale += "code; no code or semantic alias is invented."
            elif members and not term and not exact_values and response.term_code != "CNEW":
                disposition = "response_omitted"
                rationale = (
                    "Neither this code nor this value is published in the selected codelist. "
                )
                rationale += "Omit the old association; an unknown study value still needs review."
            pages = tuple(sorted({page for member in members for page in member.pages}))
            references = (
                (term_ref(replacement),)
                if replacement
                else (
                    (
                        SourceRef(
                            source_id="ct",
                            locator=f"{response.codelist} published members; PDF pages {pages}",
                        ),
                    )
                    if members
                    else ()
                )
            )
            responses_changed[(parameter.tsparmcd, response.locator)] = dict(
                disposition=disposition,
                raw_term_code=response.term_code,
                raw_value=response.value,
                selected_term_code=replacement.code if replacement else None,
                selected_value=replacement.value if replacement else None,
                codelist=response.codelist,
                authority_refs=references,
                rationale=rationale,
            )
            if replacement:
                responses.append(
                    response.model_copy(
                        update={"term_code": replacement.code, "value": replacement.value}
                    )
                )
            elif disposition == "unresolved":
                responses.append(response)
        effective.append(
            CodetableParameter(
                concept_code=identity.code if identity_safe else parameter.concept_code,
                tsparmcd=parameter.tsparmcd,
                tsparm=label.value if identity_safe else parameter.tsparm,
                locators=parameter.locators,
                responses=tuple(responses),
            )
        )
    decisions = []
    raw_parameters = {p.tsparmcd: p for p in snapshot.parameters}
    for discrepancy in verify_codetable(snapshot, terms):
        code = discrepancy.tsparmcd
        decision = dict(
            discrepancy=discrepancy,
            disposition="unresolved",
            authority_refs=(),
            rationale="No safe resolution from the selected CT; qualified review needed.",
        )
        if discrepancy.code == "CODETABLE_IDENTITY_MISMATCH" and code in identities_changed:
            identity, label = identities_changed[code]
            decision.update(
                disposition="ct_identity_selected",
                raw_concept_code=raw_parameters[code].concept_code,
                selected_concept_code=identity.code,
                selected_value=label.value,
                authority_refs=(term_ref(identity), term_ref(label)),
                rationale="Unique parameter code and exact paired label agree; the selected CT "
                "determines its concept identity. Verified response associations remain traceable.",
            )
        elif discrepancy.code == "CODETABLE_CT_MISMATCH":
            decision.update(responses_changed.get((code, discrepancy.locator), {}))
        elif discrepancy.code == "CODETABLE_UNIVERSE_MISMATCH":
            if code in identities:
                identity = identities[code]
                decision.update(
                    disposition="ct_only_parameter_manual",
                    selected_concept_code=identity.code,
                    selected_value=code,
                    authority_refs=(term_ref(identity),),
                    rationale="Keep this selected CT parameter in the master. No response codelist "
                    "is inferred from its absence in the codetable; "
                    "use explicit manual/external handling.",
                )
            else:
                decision.update(
                    disposition="parameter_omitted",
                    rationale="Codetable-only parameter is not in the selected CT universe; omit "
                    "it from the new master without declaring it retired in every context.",
                )
        decisions.append(SourceResolution.model_validate(decision))
    return ReconciliationResult(
        policy_id=POLICY_ID,
        selected_release=snapshot.release,
        effective_snapshot=CodetableSnapshot(release=snapshot.release, parameters=tuple(effective)),
        resolutions=tuple(decisions),
    )


def annotate_reconciliation(
    profile: StandardsProfile,
    content: ReviewContent,
    result: ReconciliationResult,
    terms: tuple[ExtractedTerm, ...],
) -> tuple[StandardsProfile, ReviewContent]:
    payload = profile.model_dump(mode="json")
    review = content.model_dump(mode="json")
    lookup = {(t.codelist, t.code): t for t in terms}
    policy_ref = {"source_id": "source-precedence", "locator": POLICY_ID}
    for mapping in payload["value_maps"]:
        selected = lookup[(mapping["codelist"], mapping["term_code"])]
        if selected.value != mapping["submission_value"]:
            raise ValueError("Canonical mapping must exactly match selected CT")
        mapping["authority_refs"] += [term_ref(selected).model_dump(), policy_ref]
    affected = {
        r.discrepancy.tsparmcd
        for r in result.resolutions
        if r.disposition not in {"unresolved", "parameter_omitted"}
    }
    unresolved = {r.tsparmcd for r in result.unresolved}
    manual = {
        r.discrepancy.tsparmcd
        for r in result.resolutions
        if r.disposition == "ct_only_parameter_manual"
    }
    for row in review["parameters"]:
        code = row["tsparmcd"]
        if code not in affected or code in unresolved:
            continue
        relevant = [r for r in result.resolutions if r.discrepancy.tsparmcd == code]
        refs = [ref.model_dump() for r in relevant for ref in r.authority_refs] + [policy_ref]
        parameter = next(p for p in payload["parameters"] if p["tsparmcd"] == code)
        value = next(
            v
            for v in payload["value_profiles"]
            if v["value_profile_id"] == parameter["value_profile_id"]
        )
        if code in manual and value["value_type"] != "external":
            # A source disposition cannot manufacture an unconfigured manual value contract.
            continue
        row["response"] = dict(
            status="source_backed",
            basis="project_policy",
            source_refs=refs,
            action_required=None,
            text=(
                "Selected CT retains this parameter; "
                "no codetable response association is supplied. "
                "The catalog's explicit manual/external response policy remains in force, "
                "including "
                "its scope exclusion. No dictionary or code has been invented."
            )
            if code in manual
            else (
                f"Canonical response codes/values follow pinned CT {result.selected_release}. "
                "The codetable supplies the association context; source formatting/placeholder "
                "differences are reconciled under the recorded user-directed precedence policy. "
                "Omitted responses are not silently remapped; unknown study values need review."
            ),
        )
        value["authority_refs"] += refs
    compiled = StandardsProfile.model_validate(payload)
    review["profile_content_sha256"] = content_digest(compiled)
    return compiled, ReviewContent.model_validate(review)
