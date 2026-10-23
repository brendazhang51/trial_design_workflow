"""Only synthetic protocol text and in-memory PDFs are used in automated tests."""

import io
import json
from pathlib import Path

import pytest
from pydantic import ValidationError
from pypdf import PdfWriter
from pypdf.generic import DecodedStreamObject, DictionaryObject, NameObject

from trial_design_workflow.engine import canonical_json, sha256
from trial_design_workflow.extraction.cli import extract_files, main
from trial_design_workflow.extraction.core import RuleBasedProvider, extract_facts
from trial_design_workflow.extraction.models import (
    ExtractionManifest,
    ExtractionOutput,
    ExtractionRules,
)
from trial_design_workflow.extraction.pdf import parse_page, parse_pdf
from trial_design_workflow.schemas import Artifact, SourceDocument

RULES_PATH = Path(__file__).parents[1] / "config/extraction/protocol-facts-v1.json"


def pdf_bytes(texts, *, encrypt=False):
    """Minimal ASCII PDF fixture generator; avoids committing real or binary protocols."""
    writer = PdfWriter()
    for text in texts:
        page = writer.add_blank_page(width=612, height=792)
        font = DictionaryObject(
            {
                NameObject("/Type"): NameObject("/Font"),
                NameObject("/Subtype"): NameObject("/Type1"),
                NameObject("/BaseFont"): NameObject("/Helvetica"),
            }
        )
        page[NameObject("/Resources")] = DictionaryObject(
            {NameObject("/Font"): DictionaryObject({NameObject("/F1"): writer._add_object(font)})}
        )
        lines = ["BT /F1 10 Tf 40 760 Td"]
        for line in text.splitlines():
            escaped = line.replace("\\", "\\\\").replace("(", "\\(").replace(")", "\\)")
            lines.append(f"({escaped}) Tj 0 -14 Td")
        lines.append("ET")
        stream = DecodedStreamObject()
        stream.set_data("\n".join(lines).encode("ascii"))
        page[NameObject("/Contents")] = writer._add_object(stream)
    if encrypt:
        writer.encrypt("synthetic-test-password")
    target = io.BytesIO()
    writer.write(target)
    return target.getvalue()


@pytest.fixture
def rules():
    return ExtractionRules.model_validate_json(RULES_PATH.read_bytes())


@pytest.fixture
def synthetic_pdf():
    return pdf_bytes(
        [
            "Synthetic cover\nOfficial title of study: A fictional multi-line\nstudy title\n"
            "Document date: 11 January 2025\nSponsor trial ID: SYN-101\n",
            "Protocol\nDate: 11 January 2025\nTrial ID: SYN-101 Version: 2.0\nPage: 1 of 2\n"
            "Protocol title:\nA fictional multi-line\nstudy title\n"
            "Substance names: fictional product\n"
            "Trial phase: 2b\nOverall design:\n"
            "An open-label active comparison with blinded placebo\n"
            "comparisons. This is a fictional example.\nKey Inclusion criteria:\nAdults only.\n"
            "Number of subjects:\n"
            "Approximately 240 subjects will be screened to achieve 180 subjects\n"
            "randomly assigned to trial product.\nA 12 week treatment period is planned.\n"
            "The total trial duration for the individual subject will be approximately 16 weeks.\n",
            "Protocol\nPage: 2 of 2\nTrial ID: SYN-101 Version: 2.0\n"
            "The planned treatment period remains unchanged in this fictional appendix.\n",
        ]
    )


def source(content, *, synthetic=True):
    return SourceDocument(
        artifact=Artifact(
            artifact_id="synthetic-protocol",
            path="synthetic.pdf",
            sha256=sha256(content),
            version="supplied-version-2",
            kind="protocol",
        ),
        synthetic=synthetic,
    )


def test_pdf_page_evidence_and_separate_numbering(synthetic_pdf):
    document = parse_pdf(synthetic_pdf, source(synthetic_pdf))
    assert [p.pdf_page_index for p in document.pages] == [0, 1, 2]
    assert [p.printed_page for p in document.pages] == [None, "1", "2"]
    assert document.pages[0].page_number_status == "needs_review"
    assert document.pages[1].printed_markers[0].quote.strip() == "Page: 1 of 2"


def test_extraction_proposes_grounded_unapproved_facts(synthetic_pdf, rules):
    output = extract_facts(parse_pdf(synthetic_pdf, source(synthetic_pdf)), rules)
    facts = {c.field_key: c.fact.proposed_value for c in output.candidates}
    assert facts == {
        "protocol_title": "A fictional multi-line study title",
        "sponsor_study_identifier": "SYN-101",
        "protocol_version": "2.0",
        "document_date": "11 January 2025",
        "study_phase": "2b",
        "overall_design": "An open-label active comparison with blinded placebo comparisons. "
        "This is a fictional example.",
        "planned_screened_count": "240",
        "planned_randomized_count": "180",
        "treatment_duration_weeks": "12",
        "participation_duration_weeks": "16",
    }
    assert len(output.review_queue) == len(rules.rules) == 10
    assert all(r.state == "needs_review" for r in output.review_queue)
    for candidate in output.candidates:
        assert candidate.fact.reviews == ()
        assert candidate.fact.approved_value is None
        for evidence, span in zip(candidate.fact.evidence, candidate.spans, strict=True):
            assert evidence.extraction_status == "proposed"
            assert (
                output.document.pages[span.pdf_page_index].text[span.start : span.end]
                == evidence.quote
            )
    title = next(c for c in output.candidates if c.field_key == "protocol_title")
    assert len(title.fact.evidence) == 2


def test_date_and_version_conflicts_are_not_resolved_automatically(rules):
    content = pdf_bytes(
        [
            "Page: 1 of 2\nDate: 11 January 2025\nVersion: 2.0\n",
            "Page: 2 of 2\nDate: 12 January 2025\nVersion: 1.0\n",
        ]
    )
    output = extract_facts(parse_pdf(content, source(content)), rules)
    review = {r.field_key: r for r in output.review_queue}
    assert review["document_date"].reason == "conflicting_candidates"
    assert review["protocol_version"].reason == "conflicting_candidates"
    assert review["planned_randomized_count"].reason == "missing"
    assert review["planned_randomized_count"].candidate_ids == ()


def test_page_number_ambiguity_and_resets(rules):
    page, findings = parse_page("Page: 1 of 10\nPage: 2 of 10\n", 0)
    assert page.printed_page is None
    assert page.page_number_status == "ambiguous"
    assert "AMBIGUOUS_PRINTED_PAGE" in {f.code for f in findings}
    content = pdf_bytes(
        [
            "Page: 1 of 1\nSynthetic main protocol body.\n",
            "Page: 1 of 1\nSynthetic numbered appendix.\n",
        ]
    )
    document = parse_pdf(content, source(content))
    assert "PRINTED_PAGE_RESET" in {f.code for f in document.findings}


def test_blank_and_sparse_pages_are_visible(rules):
    content = pdf_bytes(["", "Synthetic scan placeholder"])
    document = parse_pdf(content, source(content))
    assert {f.code for f in document.findings} >= {"EMPTY_PAGE_TEXT", "LOW_PAGE_TEXT"}
    assert all(r.reason == "missing" for r in extract_facts(document, rules).review_queue)


def test_no_silent_cross_page_joining(rules):
    content = pdf_bytes(
        [
            "Page: 1 of 2\nOverall design:\nA fictional study whose design continues",
            "Page: 2 of 2\non the next page.\nKey Inclusion criteria:\nAdults.\n",
        ]
    )
    output = extract_facts(parse_pdf(content, source(content)), rules)
    assert (
        next(r for r in output.review_queue if r.field_key == "overall_design").reason == "missing"
    )
    assert "PAGE_BOUNDARY_LIMIT" in {f.code for f in output.findings}


def test_untrusted_provider_cannot_invent_quote_or_approve(synthetic_pdf, rules):
    document = parse_pdf(synthetic_pdf, source(synthetic_pdf))
    baseline = RuleBasedProvider().propose(document, rules)

    class FakeProvider:
        name, version = "untrusted-test-provider", "1"

        def propose(self, document, rules):
            return baseline

    # Alter both raw statement and evidence so only document grounding catches this.
    fact = baseline["candidates"][0]["fact"]
    fact["raw_statement"] = fact["evidence"][0]["quote"] = "FABRICATED SOURCE TEXT"
    with pytest.raises(ValidationError, match="not grounded"):
        extract_facts(document, rules, FakeProvider())
    baseline = RuleBasedProvider().propose(document, rules)
    baseline["candidates"][0]["fact"]["evidence"][0]["extraction_status"] = "reviewed"
    with pytest.raises(ValidationError, match="cannot create human approvals"):
        extract_facts(document, rules, FakeProvider())


def test_hash_mismatch_encryption_and_invalid_pdf(synthetic_pdf):
    with pytest.raises(ValueError, match="hash mismatch"):
        parse_pdf(synthetic_pdf + b"changed", source(synthetic_pdf))
    encrypted = pdf_bytes(["Synthetic encrypted example"], encrypt=True)
    with pytest.raises(ValueError, match="Encrypted PDF"):
        parse_pdf(encrypted, source(encrypted))
    invalid = b"this is not a PDF"
    with pytest.raises(ValueError, match="Unable to parse PDF"):
        parse_pdf(invalid, source(invalid))


def test_real_document_flag_allowed_only_in_extraction(synthetic_pdf, rules):
    # Synthetic content tests the real-input contract without adding a real protocol fixture.
    document = parse_pdf(synthetic_pdf, source(synthetic_pdf, synthetic=False))
    assert extract_facts(document, rules).document.source.synthetic is False


def test_rule_reordering_does_not_change_output(synthetic_pdf, rules):
    document = parse_pdf(synthetic_pdf, source(synthetic_pdf))
    payload = rules.model_dump(mode="json")
    payload["rules"].reverse()
    other = extract_facts(document, ExtractionRules.model_validate(payload))
    original = extract_facts(document, rules)
    assert original.candidates == other.candidates
    assert original.review_queue == other.review_queue
    assert original.findings == other.findings


@pytest.mark.parametrize(
    "change",
    [
        lambda p: p["rules"][0].update(patterns=["("]),
        lambda p: p["rules"][0].update(patterns=["title"]),
        lambda p: p["rules"].append(p["rules"][0]),
    ],
)
def test_invalid_rules_are_rejected(rules, change):
    payload = rules.model_dump(mode="json")
    change(payload)
    with pytest.raises(ValidationError):
        ExtractionRules.model_validate(payload)


def test_extraction_bundle_roundtrip_and_no_overwrite(synthetic_pdf, tmp_path):
    pdf = tmp_path / "synthetic.pdf"
    pdf.write_bytes(synthetic_pdf)
    first, second = tmp_path / "first", tmp_path / "second"
    for target in (first, second):
        assert (
            extract_files(
                pdf,
                RULES_PATH,
                target,
                document_id="synthetic-protocol",
                document_version="test-v2",
                expected_sha256=sha256(synthetic_pdf),
                synthetic=True,
            )
            == 0
        )
    manifest = ExtractionManifest.model_validate_json((first / "manifest.json").read_bytes())
    extraction = ExtractionOutput.model_validate_json((first / "extraction.json").read_bytes())
    assert extraction.document.source.artifact.sha256 == sha256(synthetic_pdf)
    for artifact in manifest.outputs:
        assert sha256((first / artifact.path).read_bytes()) == artifact.sha256
        assert (first / artifact.path).read_bytes() == (second / artifact.path).read_bytes()
    assert manifest.logical_extraction_sha256 == sha256(
        canonical_json(extraction.model_dump(mode="json")).encode()
    )
    assert manifest.parser_settings["model_provider"] == "not_used"
    with pytest.raises(FileExistsError):
        extract_files(
            pdf,
            RULES_PATH,
            first,
            document_id="synthetic-protocol",
            document_version="test-v2",
            expected_sha256=sha256(synthetic_pdf),
            synthetic=True,
        )


def test_cli_invalid_input_produces_structured_error(tmp_path, monkeypatch, capsys):
    pdf = tmp_path / "bad.pdf"
    pdf.write_bytes(b"invalid")
    monkeypatch.setattr(
        "sys.argv",
        [
            "trial-extract",
            "--pdf",
            str(pdf),
            "--rules",
            str(RULES_PATH),
            "--output",
            str(tmp_path / "out"),
            "--document-id",
            "test",
            "--document-version",
            "1",
            "--expected-sha256",
            "0" * 64,
        ],
    )
    assert main() == 2
    assert json.loads(capsys.readouterr().err)[0]["code"] == "EXTRACTION_ERROR"
    assert not (tmp_path / "out").exists()


@pytest.mark.parametrize(
    "text",
    [
        "A 12.5 week treatment period is planned.",
        "A 7-12 week treatment period is planned.",
        "180.5 subjects will be randomized.",
        "100-180 subjects will be randomized.",
    ],
)
def test_decimal_or_range_does_not_become_integer_tail(text, rules):
    content = pdf_bytes([text])
    output = extract_facts(parse_pdf(content, source(content)), rules)
    assert not any(
        c.field_key in {"treatment_duration_weeks", "planned_randomized_count"}
        for c in output.candidates
    )


def test_thousands_separators_preserve_original_evidence(rules):
    content = pdf_bytes(["Approximately 1,200 subjects will be screened."])
    output = extract_facts(parse_pdf(content, source(content)), rules)
    candidate = next(c for c in output.candidates if c.field_key == "planned_screened_count")
    assert candidate.fact.proposed_value == "1200"
    assert "1,200" in candidate.fact.raw_statement


def test_untrusted_span_bounds_and_incomplete_review_rejected(synthetic_pdf, rules):
    output = extract_facts(parse_pdf(synthetic_pdf, source(synthetic_pdf)), rules)
    payload = output.model_dump(mode="json")
    payload["review_queue"].pop()
    with pytest.raises(ValidationError, match="every extraction field"):
        ExtractionOutput.model_validate(payload)
    payload = output.model_dump(mode="json")
    payload["candidates"][0]["spans"][0]["end"] = 1000000
    with pytest.raises(ValidationError, match="not grounded"):
        ExtractionOutput.model_validate(payload)


def test_provider_cannot_grant_human_fact_approval(synthetic_pdf, rules):
    document = parse_pdf(synthetic_pdf, source(synthetic_pdf))
    batch = RuleBasedProvider().propose(document, rules)
    fact = batch["candidates"][0]["fact"]
    fact["reviews"] = [
        {
            "reviewer": "fabricated-reviewer",
            "reviewed_at": "2026-01-01T00:00:00Z",
            "action": "approve",
            "approved_value": fact["proposed_value"],
            "rationale": "Provider attempted to approve itself",
        }
    ]

    class InvalidApprovalProvider:
        name, version = "test-provider", "1"

        def propose(self, document, rules):
            return batch

    with pytest.raises(ValidationError, match="cannot create human approvals"):
        extract_facts(document, rules, InvalidApprovalProvider())
