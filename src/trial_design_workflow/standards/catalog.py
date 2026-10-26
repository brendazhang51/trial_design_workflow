"""Typed, declarative parameter policies for the complete clinical TS review draft.

This compiles standards assets only. It neither extracts Study Facts nor runs a
study selection engine. All inclusion choices are project proposals, not approval.
"""

from typing import Literal, Self

from pydantic import Field, model_validator

from ..schemas import Model, Text
from .models import StandardsProfile
from .review import ReviewContent
from .validation import content_digest


class ConditionPolicy(Model):
    mode: Literal["always", "conditional", "out_of_scope"]
    explanation: Text
    fact_key: Text | None = None
    include_value: Text | None = None
    exclude_value: Text | None = None
    source_requirement: Literal["protocol", "study_data", "sponsor", "external"] | None = None

    @model_validator(mode="after")
    def shape(self) -> Self:
        operands = (self.fact_key, self.include_value, self.exclude_value, self.source_requirement)
        if self.mode == "conditional":
            if not all(operands) or self.include_value == self.exclude_value:
                raise ValueError(
                    "conditional policies need distinct include/exclude operands and source"
                )
        elif any(operands):
            raise ValueError("unconditional policies cannot declare condition operands")
        return self


class ParameterPolicy(Model):
    code: Text
    condition: Text
    fact: Text
    source: Literal["protocol", "study_data", "sponsor", "external"]
    response: Literal[
        "codetable", "text", "integer", "decimal", "date", "duration", "external", "unresolved"
    ]
    repeat: tuple[Text, ...]
    source_detail: Text
    grouping: tuple[Text, ...] = ()
    additional_facts: tuple[Text, ...] = ()
    transform: Literal["ratio_from_counts"] | None = None
    exception_detail: Text | None = None


class ParameterPolicyCatalog(Model):
    schema_version: Literal["1"]
    version: Literal["2"]
    description: Text
    conditions: dict[Text, ConditionPolicy]
    parameters: tuple[ParameterPolicy, ...] = Field(min_length=1)

    @model_validator(mode="after")
    def references(self) -> Self:
        codes = [p.code for p in self.parameters]
        if len(codes) != len(set(codes)):
            raise ValueError("duplicate parameter policy")
        for parameter in self.parameters:
            if parameter.condition not in self.conditions:
                raise ValueError(f"unknown policy condition: {parameter.condition}")
            if parameter.transform == "ratio_from_counts" and len(parameter.additional_facts) != 2:
                raise ValueError("ratio policy requires explicit numerator and denominator facts")
        return self


def compile_catalog(
    profile: StandardsProfile, content: ReviewContent, catalog: ParameterPolicyCatalog
) -> tuple[StandardsProfile, ReviewContent]:
    """Join every policy to a CT identity; unknown/extra/unclassified rows fail closed."""
    policies = {p.code: p for p in catalog.parameters}
    if set(policies) != {p.tsparmcd for p in profile.parameters}:
        raise ValueError("policy catalog must cover exactly the pinned CT parameter universe")
    payload = profile.model_dump(mode="json")
    review = content.model_dump(mode="json")
    review["content_version"] = "2"
    rows = {r["tsparmcd"]: r for r in review["parameters"]}
    rules = {r["rule_id"]: r for r in payload["applicability_rules"]}
    values = {v["value_profile_id"]: v for v in payload["value_profiles"]}
    derivations = {d["derivation_id"]: d for d in payload["derivations"]}
    groups = {}
    facts = set(payload["fact_keys"])
    ig = {"source_id": "sdtmig", "locator": "7.4.2 Assumptions 2, 7-9, 12-18; pp. 418-419"}

    def assertion(text: str, refs: list[dict]) -> dict:
        return dict(
            status="source_backed",
            basis="project_policy",
            text=text,
            source_refs=refs,
            action_required=None,
        )

    for parameter in payload["parameters"]:
        code = parameter["tsparmcd"]
        policy = policies[code]
        condition = catalog.conditions[policy.condition]
        refs = [{"source_id": "parameter-policies", "locator": f"parameters[{code}]"}, ig]
        refs += parameter["authority_refs"]
        row = rows[code]
        rule = rules[parameter["applicability_rule_id"]]
        mode = condition.mode
        predicate = None
        if mode == "conditional":
            predicate = dict(
                op="fact_equals", fact_key=condition.fact_key, value=condition.include_value
            )
            facts.add(condition.fact_key)
        rule.update(
            predicate=predicate,
            on_true="exclude" if mode == "out_of_scope" else "include",
            on_false="include" if mode == "always" else "exclude",
            on_unknown="manual_assessment",
            explanation=f"{code}: {condition.explanation} "
            "Value availability is checked separately.",
            version="2",
            authority_refs=refs,
        )
        parameter.update(
            base_disposition={
                "always": "always",
                "conditional": "conditional",
                "out_of_scope": "out_of_scope",
            }[mode],
            min_records=1 if mode == "always" else 0,
            max_records=None if policy.repeat else 1,
            repeat_key=list(policy.repeat),
            fact_key=None if policy.transform == "ratio_from_counts" else policy.fact,
            automation_level="manual"
            if policy.response in {"external", "unresolved"}
            else "propose_only",
            review_reason=f"Proposed project policy v2 for {code}; qualified review pending. "
            + (
                "Excluded by this profile's scope; not a claim about the study's legal status."
                if mode == "out_of_scope"
                else "No proposal or scope decision is verified by AI."
            ),
            evidence_requirements=policy.source_detail,
        )
        inputs = list(
            dict.fromkeys(
                (
                    *((policy.fact,) if policy.transform is None else ()),
                    *policy.additional_facts,
                    *policy.repeat,
                    *policy.grouping,
                )
            )
        )
        facts.update(inputs)
        transform = (
            policy.transform
            or {
                "codetable": "map_exact_ct",
                "text": "copy_text",
                "integer": "format_integer",
                "decimal": "format_decimal",
                "date": "preserve_iso8601_precision",
                "duration": "preserve_iso8601_duration",
                "external": "manual",
                "unresolved": "manual",
            }[policy.response]
        )
        value = values[parameter["value_profile_id"]]
        has_codelist = value["response_codelist"] is not None
        unresolved = (
            policy.response == "unresolved" or policy.response == "codetable" and not has_codelist
        )
        if unresolved:
            transform = "manual"
        elif policy.response != "codetable" and has_codelist:
            raise ValueError(f"policy contradicts supplied response-codelist association: {code}")
        value.update(
            value_type="manual"
            if unresolved
            else "controlled"
            if has_codelist
            else policy.response,
            external_source_required=policy.response == "external",
            target_fields=["TSVAL", "TSVALCD", "TSVCDREF", "TSVCDVER"]
            if has_codelist or policy.response == "external"
            else ["TSVAL"],
            authority_refs=[
                *[r for r in value["authority_refs"] if r["source_id"] != "project-policy"],
                *refs,
            ],
        )
        derivations[parameter["derivation_id"]].update(
            version="2",
            fact_keys=inputs,
            transform=transform,
            source_requirement=policy.source,
            authority_refs=refs,
        )
        if policy.grouping:
            group_id = "group-" + "-".join(policy.grouping) + "-v2"
            groups.setdefault(
                group_id,
                dict(rule_id=group_id, fact_keys=list(policy.grouping), authority_refs=refs),
            )
            parameter["tsgrpid_rule_id"] = group_id
        else:
            parameter["tsgrpid_rule_id"] = None
        if mode == "conditional":
            inclusion = (
                f"Include {code} when validated, reviewed {condition.fact_key} is "
                f"{condition.include_value}; exclude only when it is {condition.exclude_value}. "
                "Missing, invalid, proposed or conflicting assessments are unknown and "
                "require review; do not coerce an arbitrary unequal value to false."
            )
        elif mode == "out_of_scope":
            inclusion = f"Exclude {code} in this profile. {condition.explanation}"
        else:
            inclusion = f"Include {code} in this project review draft. {condition.explanation}"
        row["inclusion"] = assertion(
            inclusion + " This is a proposed project policy, not a CDISC required-parameter claim.",
            refs,
        )
        row["value_source"] = assertion(
            f"{policy.source}: {policy.source_detail} Input fact: {policy.fact}.", refs
        )
        row["derivation"] = assertion(
            f"{policy.fact}: {transform}; inputs: {', '.join(inputs)}. "
            + (
                "Numerator and denominator must refer to the same planned population; denominator "
                "must be positive, 0 <= numerator <= denominator; "
                "no arm-count shortcut or rounding "
                "without a declared precision policy."
                if transform == "ratio_from_counts"
                else "Preserve source precision and explicit units; "
                "do not convert planned observations "
                "to actual values, invent dictionary versions or guess aliases."
            ),
            refs,
        )
        row["cardinality"] = assertion(
            (
                f"One record per distinct ({', '.join(policy.repeat)}); no arbitrary upper bound. "
                if policy.repeat
                else "One value in this project profile; multiple conflicting "
                "observations require review rather than silent collapse. "
            )
            + (
                f"Related records share ({', '.join(policy.grouping)}). Group keys must be "
                "documented; missing or ambiguous associations require review."
                if policy.grouping
                else "No cross-parameter grouping is authorized by this policy."
            ),
            refs,
        )
        row["exceptions"] = assertion(
            f"{code}: {policy.exception_detail or policy.source_detail} "
            "Missing evidence or values, "
            "conflicts, invalid CT or unavailable external coding remain exceptions. "
            "Missing value is not non-applicability; no automatic null flavor. "
            "All generated records remain proposals pending qualified review.",
            refs,
        )
        # Keep existing source disagreements visible; policy prose must not erase them.
        response_gap = row["response"]["status"] != "source_backed" and bool(
            row["response"]["source_refs"]
        )
        if policy.response == "external":
            row.update(
                codelist_status="external",
                codelist_id=None,
                codelist_name=None,
                terminology_release=None,
                no_codelist_reason=None,
            )
            if not response_gap:
                row["response"] = assertion(
                    "External coding/format reference requires a documented authorized source and "
                    "version. No dictionary is selected or code invented by this profile; "
                    "unsupported coding stays a manual/external exception. " + policy.source_detail,
                    refs,
                )
        elif not has_codelist and not unresolved:
            row.update(
                codelist_status="not_applicable",
                codelist_id=None,
                codelist_name=None,
                terminology_release=None,
                no_codelist_reason=f"Project draft uses uncoded {policy.response}, grounded in "
                f"the {code} definition and IG Assumptions 7/9; this does not assert that "
                "no terminology could ever apply in another submission context.",
            )
            if not response_gap:
                row["response"] = assertion(
                    row["no_codelist_reason"] + " " + policy.source_detail, refs
                )
        elif unresolved and not response_gap:
            row["response"] = dict(
                status="proposed",
                basis="project_policy",
                text=policy.source_detail,
                source_refs=refs,
                action_required="Resolve this specific response contract "
                "against the pinned sources; do not infer a codelist from a blank mapping cell.",
            )
    payload["fact_keys"] = sorted(facts)
    payload["grouping_rules"] = list(groups.values())
    compiled = StandardsProfile.model_validate(payload)
    review["profile_content_sha256"] = content_digest(compiled)
    return compiled, ReviewContent.model_validate(review)
