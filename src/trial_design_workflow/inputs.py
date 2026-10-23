"""Input: local PDF and public registry adapters produce the same small fact contract."""

import json
import re
from datetime import UTC, datetime
from pathlib import Path
from typing import Literal
from urllib.error import HTTPError, URLError
from urllib.request import Request, urlopen

from pydantic import BaseModel, ConfigDict, Field

from .engine import canonical_json, sha256
from .extraction.core import extract_facts
from .extraction.models import ExtractionRules
from .extraction.pdf import parse_pdf
from .schemas import Artifact, Model, SourceDocument, Text

SourceType = Literal["protocol", "clinicaltrials_gov"]
ASSETS = Path(__file__).parent / "assets"


class Fact(Model):
    field_key: Text
    proposed_value: Text
    source_type: SourceType
    source_locator: Text
    evidence_text: str = ""
    source_id: Text
    context: str = "reported; requires review"
    review_status: Literal["needs_review"] = "needs_review"
    extraction_status: Literal["proposed", "parsed"]


class FactValue(Model):
    proposed_value: Text
    observations: tuple[Fact, ...] = Field(min_length=1)


class StudyField(Model):
    field_key: Text
    result: Literal["agreement", "single_source", "conflict"]
    values: tuple[FactValue, ...] = Field(min_length=1)
    review_status: Literal["needs_review"] = "needs_review"


class StudyInputs(Model):
    input_type: Literal["registry", "protocol", "hybrid"]
    study_id: Text
    nct_id: str | None
    facts: tuple[StudyField, ...]
    protocol_sha256: str | None = None
    payload_sha256: str | None = None
    fetched_at: datetime | None = None
    messages: tuple[str, ...] = ()


# Validate the registry envelope and selected structures, while allowing unrelated API fields.
class APIModel(BaseModel):
    model_config = ConfigDict(extra="ignore", strict=True)


class Identification(APIModel):
    nctId: str = Field(pattern=r"^NCT\d{8}$")
    officialTitle: str | None = None
    briefTitle: str | None = None
    orgStudyIdInfo: dict[str, str] = Field(default_factory=dict)


class Enrollment(APIModel):
    count: int = Field(ge=0)
    type: Literal["ACTUAL", "ESTIMATED"]


class Design(APIModel):
    studyType: str | None = None
    phases: list[str] = Field(default_factory=list)
    enrollmentInfo: Enrollment | None = None
    designInfo: dict = Field(default_factory=dict)


class ProtocolSection(APIModel):
    identificationModule: Identification
    designModule: Design = Field(default_factory=Design)
    statusModule: dict = Field(default_factory=dict)
    sponsorCollaboratorsModule: dict = Field(default_factory=dict)
    conditionsModule: dict = Field(default_factory=dict)
    eligibilityModule: dict = Field(default_factory=dict)
    armsInterventionsModule: dict = Field(default_factory=dict)


class StudyRecord(APIModel):
    protocolSection: ProtocolSection


def validate_nct(nct_id: str) -> str:
    if not re.fullmatch(r"NCT\d{8}", nct_id):
        raise ValueError("NCT ID must match NCT followed by exactly eight digits")
    return nct_id


def fetch_record(nct_id: str) -> bytes:
    """Read exactly one study, with timeout and a bounded response; never fetch PDF content."""
    validate_nct(nct_id)
    request = Request(
        f"https://clinicaltrials.gov/api/v2/studies/{nct_id}",
        headers={"Accept": "application/json", "User-Agent": "trial-ts/0.3"},
    )
    try:
        with urlopen(request, timeout=30) as response:
            content = response.read(20_000_001)
    except HTTPError as exc:
        raise ValueError(f"ClinicalTrials.gov returned HTTP {exc.code}; check the NCT ID") from exc
    except (URLError, TimeoutError, OSError) as exc:
        raise ValueError(
            "ClinicalTrials.gov unavailable; retry or use --registry-json snapshot"
        ) from exc
    if len(content) > 20_000_000:
        raise ValueError("Registry response exceeds the 20 MB input limit")
    return content


def registry_facts(content: bytes, nct_id: str) -> tuple[Fact, ...]:
    record = StudyRecord.model_validate_json(content)
    section = record.protocolSection
    if section.identificationModule.nctId != nct_id:
        raise ValueError("Registry response NCT ID does not match the requested study")
    root = json.loads(content)["protocolSection"]
    facts = []

    def add(key, path, context="registry report; requires review"):
        value = root
        for part in path.split("."):
            if not isinstance(value, dict):
                raise ValueError(f"Unexpected registry structure at {path}")
            value = value.get(part)
            if value is None:
                return
        if isinstance(value, str):
            proposed = value.strip()
        elif isinstance(value, (int, bool)):
            proposed = str(value)
        elif isinstance(value, list) and all(isinstance(v, str) for v in value):
            proposed = (
                canonical_json(sorted(value)) if len(value) > 1 else (value[0] if value else "")
            )
        else:
            raise ValueError(f"Expected a scalar or string list at {path}")
        if proposed:
            facts.append(
                Fact(
                    field_key=key,
                    proposed_value=proposed,
                    source_type="clinicaltrials_gov",
                    source_id=nct_id,
                    source_locator="protocolSection." + path,
                    context=context,
                    extraction_status="parsed",
                )
            )

    for key, path in (
        ("nct_id", "identificationModule.nctId"),
        ("protocol_title", "identificationModule.officialTitle"),
        ("brief_title", "identificationModule.briefTitle"),
        ("sponsor_study_identifier", "identificationModule.orgStudyIdInfo.id"),
        ("study_type", "designModule.studyType"),
        ("study_phase", "designModule.phases"),
        ("masking", "designModule.designInfo.maskingInfo.masking"),
        ("masking_description", "designModule.designInfo.maskingInfo.maskingDescription"),
        ("allocation", "designModule.designInfo.allocation"),
        ("primary_purpose", "designModule.designInfo.primaryPurpose"),
        ("lead_sponsor", "sponsorCollaboratorsModule.leadSponsor.name"),
        ("overall_status", "statusModule.overallStatus"),
        ("registry_last_update", "statusModule.lastUpdatePostDateStruct.date"),
        ("conditions", "conditionsModule.conditions"),
        ("minimum_age", "eligibilityModule.minimumAge"),
        ("maximum_age", "eligibilityModule.maximumAge"),
        ("sex", "eligibilityModule.sex"),
    ):
        add(key, path)
    if section.designModule.enrollmentInfo:
        kind = section.designModule.enrollmentInfo.type
        add(
            "actual_enrollment" if kind == "ACTUAL" else "planned_enrollment",
            "designModule.enrollmentInfo.count",
            context=f"enrollment type={kind}; whole record scope",
        )
    for key, path in (
        ("study_start_date", "statusModule.startDateStruct"),
        ("study_completion_date", "statusModule.completionDateStruct"),
    ):
        date = root.get("statusModule", {}).get(path.split(".")[-1])
        if date:
            if not isinstance(date, dict) or date.get("type") not in {"ACTUAL", "ESTIMATED"}:
                raise ValueError(f"Missing or unknown date type at {path}")
            add(key, path + ".date", context="date type=" + date["type"])
    return tuple(facts)


def protocol_facts(path: Path) -> tuple[tuple[Fact, ...], str, tuple[str, ...]]:
    content = path.read_bytes()
    digest = sha256(content)
    document_id = "protocol:" + digest[:16]
    source = SourceDocument(
        artifact=Artifact(
            artifact_id=document_id,
            path=path.name,
            sha256=digest,
            version="user_supplied_not_verified",
            kind="protocol",
        ),
        synthetic=False,
    )
    parsed = parse_pdf(content, source)
    rule_bytes = (ASSETS / "protocol-facts-v1.json").read_bytes()
    metadata = json.loads((ASSETS / "sources.json").read_bytes())
    if sha256(rule_bytes) != metadata["files"]["protocol-facts-v1.json"]:
        raise ValueError("Bundled extraction rules changed without versioning")
    rules = ExtractionRules.model_validate_json(rule_bytes)
    extraction = extract_facts(parsed, rules)
    facts = []
    for candidate in extraction.candidates:
        key = {"planned_randomized_count": "planned_enrollment"}.get(
            candidate.field_key, candidate.field_key
        )
        for evidence in candidate.fact.evidence:
            locator = f"{document_id}; pdf_page_index={evidence.pdf_page_index}; "
            locator += (
                f"PDF page={evidence.pdf_page_index + 1}; printed_page={evidence.printed_page}"
            )
            facts.append(
                Fact(
                    field_key=key,
                    proposed_value=candidate.fact.proposed_value,
                    source_type="protocol",
                    source_id=document_id,
                    source_locator=locator,
                    evidence_text=evidence.quote,
                    extraction_status="proposed",
                    context="planned design; section and total-versus-arm scope unverified",
                )
            )
    # Identifier discovery does not rely on filename or catalog answers.
    for page in parsed.pages:
        for match in re.finditer(r"\bNCT\d{8}\b", page.text):
            facts.append(
                Fact(
                    field_key="nct_id",
                    proposed_value=match[0],
                    source_type="protocol",
                    source_id=document_id,
                    source_locator=f"{document_id}; PDF page={page.pdf_page_index + 1}; "
                    f"pdf_page_index={page.pdf_page_index}; printed_page={page.printed_page}",
                    evidence_text=match[0],
                    extraction_status="proposed",
                )
            )
    messages = tuple(
        sorted(
            {
                f"{f.code}"
                + (f" (PDF page {f.pdf_page_index + 1})" if f.pdf_page_index is not None else "")
                + f": {f.message}"
                for f in extraction.findings
                if f.field_key is None
            }
        )
    )
    return tuple(facts), digest, messages


def reconcile(facts: tuple[Fact, ...]) -> tuple[StudyField, ...]:
    """Compare whitespace/case only; no source wins and every original value is retained."""
    grouped: dict[str, dict[str, list[Fact]]] = {}
    for fact in facts:
        normalized = " ".join(fact.proposed_value.split()).casefold()
        grouped.setdefault(fact.field_key, {}).setdefault(normalized, []).append(fact)
    fields = []
    for key, groups in sorted(grouped.items()):
        values = []
        for _, observations in sorted(groups.items()):
            unique = {canonical_json(f.model_dump(mode="json")): f for f in observations}
            ordered = tuple(unique[k] for k in sorted(unique))
            values.append(
                FactValue(
                    proposed_value=min(f.proposed_value for f in ordered),
                    observations=ordered,
                )
            )
        sources = {f.source_type for group in values for f in group.observations}
        result = (
            "conflict" if len(values) > 1 else "agreement" if len(sources) == 2 else "single_source"
        )
        fields.append(StudyField(field_key=key, result=result, values=tuple(values)))
    return tuple(fields)


def collect_inputs(
    *,
    nct_id: str | None = None,
    protocol: Path | None = None,
    registry_json: Path | None = None,
) -> StudyInputs:
    if not nct_id and not protocol:
        raise ValueError("Provide --nct-id, --protocol, or both")
    if registry_json and not nct_id:
        raise ValueError("--registry-json requires --nct-id to verify study identity")
    facts, messages = [], []
    digest = payload_digest = fetched = None
    if nct_id:
        validate_nct(nct_id)
        content = registry_json.read_bytes() if registry_json else fetch_record(nct_id)
        facts.extend(registry_facts(content, nct_id))
        payload_digest = sha256(content)
        fetched = None if registry_json else datetime.now(UTC)
        if registry_json:
            messages.append(
                "REGISTRY_SNAPSHOT: supplied snapshot; original fetch time not provided"
            )
    if protocol:
        observations, digest, notes = protocol_facts(protocol)
        pdf_ids = {f.proposed_value for f in observations if f.field_key == "nct_id"}
        if nct_id and pdf_ids and pdf_ids != {nct_id}:
            raise ValueError(
                "Protocol NCT identity conflicts with requested registry study; do not merge"
            )
        if nct_id and not pdf_ids:
            messages.append("IDENTITY_UNVERIFIED: no NCT ID found in protocol; verify study match")
        facts.extend(observations)
        messages.extend(notes)
    fields = reconcile(tuple(facts))
    if nct_id:
        study_id = nct_id
    else:
        identifiers = next((f for f in fields if f.field_key == "sponsor_study_identifier"), None)
        study_id = (
            identifiers.values[0].proposed_value
            if identifiers and identifiers.result != "conflict"
            else "LOCAL-" + digest[:12]
        )
        if study_id.startswith("LOCAL-"):
            messages.append("LOCAL_STUDYID: technical ID derived from protocol SHA-256; review")
    return StudyInputs(
        input_type="hybrid" if nct_id and protocol else "registry" if nct_id else "protocol",
        study_id=study_id,
        nct_id=nct_id,
        facts=fields,
        protocol_sha256=digest,
        payload_sha256=payload_digest,
        fetched_at=fetched,
        messages=tuple(sorted(set(messages))),
    )
