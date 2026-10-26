"""PDF adapter. Exact extracted text is retained without header/footer rewriting."""

import io
import re

import pypdf
from pypdf import PdfReader
from pypdf.errors import PyPdfError

from ..schemas import SourceDocument
from ..serialization import sha256
from .models import ExtractionFinding, PageText, ParsedDocument, PrintedPageMarker

PRINTED_PAGE = re.compile(
    r"(?im)^[ \t]*Page[ \t]*:?[ \t]*(?P<page>\d+)[ \t]+of[ \t]+(?P<total>\d+)[ \t]*$"
)


def parse_page(text: str, index: int) -> tuple[PageText, tuple[ExtractionFinding, ...]]:
    markers = tuple(
        PrintedPageMarker(
            page=int(m["page"]),
            total=int(m["total"]),
            start=m.start(),
            end=m.end(),
            quote=m[0],
        )
        for m in PRINTED_PAGE.finditer(text)
        if 0 < int(m["page"]) <= int(m["total"])
    )
    labels = {(m.page, m.total) for m in markers}
    printed_page = str(next(iter(labels))[0]) if len(labels) == 1 else None
    status = "proposed" if len(labels) == 1 else "ambiguous" if labels else "needs_review"
    findings = []
    if not text.strip():
        findings.append(
            ExtractionFinding(
                code="EMPTY_PAGE_TEXT",
                severity="warning",
                pdf_page_index=index,
                message="No extractable text. Inspect the page and supply reviewed OCR if needed.",
            )
        )
    elif len(text.strip()) < 80:
        findings.append(
            ExtractionFinding(
                code="LOW_PAGE_TEXT",
                severity="warning",
                pdf_page_index=index,
                message="Sparse extracted text; inspect images, scan quality and layout.",
            )
        )
    if printed_page is None:
        findings.append(
            ExtractionFinding(
                code="AMBIGUOUS_PRINTED_PAGE" if labels else "PRINTED_PAGE_UNRESOLVED",
                severity="warning",
                pdf_page_index=index,
                message="Printed page is unverified; locate evidence with the PDF page index.",
            )
        )
    return PageText(
        pdf_page_index=index,
        text=text,
        printed_page=printed_page,
        page_number_status=status,
        printed_markers=markers,
    ), tuple(findings)


def parse_pdf(content: bytes, source: SourceDocument) -> ParsedDocument:
    if sha256(content) != source.artifact.sha256:
        raise ValueError("Protocol hash mismatch; extraction was not started")
    try:
        reader = PdfReader(io.BytesIO(content), strict=True)
        if reader.is_encrypted:
            raise ValueError("Encrypted PDF is unsupported; provide an authorized readable copy")
        if not reader.pages:
            raise ValueError("PDF has no pages")
        pages, findings = [], []
        previous = None
        for index, pdf_page in enumerate(reader.pages):
            try:
                text = pdf_page.extract_text(extraction_mode="plain") or ""
            except (PyPdfError, ValueError, KeyError) as exc:
                raise ValueError(f"PDF text extraction failed on page index {index}") from exc
            page, page_findings = parse_page(text, index)
            pages.append(page)
            findings.extend(page_findings)
            if page.printed_page is not None:
                current = int(page.printed_page)
                if previous is not None and current <= previous:
                    findings.append(
                        ExtractionFinding(
                            code="PRINTED_PAGE_RESET",
                            severity="warning",
                            pdf_page_index=index,
                            message="Printed numbering restarts; use document ID and PDF index.",
                        )
                    )
                previous = current
    except PyPdfError as exc:
        raise ValueError("Unable to parse PDF; inspect document integrity") from exc
    return ParsedDocument(
        source=source,
        parser_name="pypdf",
        parser_version=pypdf.__version__,
        extraction_mode="plain",
        pages=tuple(pages),
        findings=tuple(findings),
    )
