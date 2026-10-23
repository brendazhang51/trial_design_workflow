"""Rebuild the small TS candidate/CT snapshots from an archived official NCI HTML file.

Usage: python tools/build_ts_assets.py outputs/mvp-sources/sdtm-ct-2025-03-28.html
This imports names/codes, not requiredness, response obligations or SDTMIG rules.
"""

import csv
import hashlib
import json
import sys
from html.parser import HTMLParser
from pathlib import Path

RELEASE = "2025-03-28"
URL = "https://evs.nci.nih.gov/ftp1/CDISC/SDTM/Archive/SDTM%20Terminology%202025-03-28.html"
LISTS = {"C66738", "C67152", "C66735", "C66737", "C99077", "C66736", "C66739"}


class Tables(HTMLParser):
    def __init__(self):
        super().__init__()
        self.rows, self.cells, self.parts = [], [], []
        self.row_class = self.current_list = ""
        self.in_cell = False

    def handle_starttag(self, tag, attrs):
        attrs = dict(attrs)
        if tag == "tr":
            self.cells, self.row_class = [], attrs.get("class", "")
        if tag == "td":
            self.parts, self.in_cell = [], True
        if tag == "br" and self.in_cell:
            self.parts.append(" ")

    def handle_data(self, text):
        if self.in_cell:
            self.parts.append(text)

    def handle_endtag(self, tag):
        if tag == "td":
            self.cells.append(" ".join("".join(self.parts).split()))
            self.in_cell = False
        if tag == "tr" and self.cells:
            if self.row_class == "cl":
                self.current_list = self.cells[3]
            elif self.row_class == "cli" and self.current_list in LISTS:
                # The submission-value cell spans two columns; there are six actual cells.
                self.rows.append((self.current_list, *self.cells[1:]))


def build(source: Path, destination: Path):
    content = source.read_bytes()
    parser = Tables()
    parser.feed(content.decode("iso-8859-1"))
    names = {r[2]: r[1] for r in parser.rows if r[0] == "C67152"}
    codes = [r for r in parser.rows if r[0] == "C66738"]
    if not codes or any(r[2] not in names for r in codes):
        raise ValueError("Official code/name join is incomplete")
    destination.mkdir(parents=True, exist_ok=True)
    ct_path = destination / "ct-2025-03-28.csv"
    with ct_path.open("w", newline="", encoding="utf-8") as stream:
        writer = csv.writer(stream)
        writer.writerow(["release", "codelist", "code", "value"])
        writer.writerows((RELEASE, r[0], r[2], r[1]) for r in sorted(parser.rows))
    # These are project mapping suggestions. They do not assert CDISC applicability.
    mapping = {
        "TITLE": ("protocol_title", "text", "", "protocol|clinicaltrials_gov"),
        "ACTSUB": ("actual_enrollment", "integer", "", "clinicaltrials_gov"),
        "PLANSUB": ("planned_enrollment", "integer", "", "protocol|clinicaltrials_gov"),
        "TPHASE": ("study_phase", "text", "C66737", "protocol|clinicaltrials_gov"),
        "STYPE": ("study_type", "text", "C99077", "clinicaltrials_gov"),
        "TBLIND": ("masking", "text", "C66735", "clinicaltrials_gov"),
        "TINDTP": ("primary_purpose", "text", "C66736", "clinicaltrials_gov"),
        "REGID": ("nct_id", "text", "", "clinicaltrials_gov|protocol"),
        "SPONSOR": ("lead_sponsor", "text", "", "clinicaltrials_gov"),
        "SSTDTC": ("study_start_date", "date", "", "clinicaltrials_gov"),
        "SENDTC": ("study_completion_date", "date", "", "clinicaltrials_gov"),
    }
    path = destination / "ts-parameters-v1.csv"
    with path.open("w", newline="", encoding="utf-8") as stream:
        writer = csv.writer(stream)
        writer.writerow(
            [
                "TSPARMCD",
                "TSPARM",
                "applicability_rule",
                "expected_fact_key",
                "value_type",
                "response_codelist",
                "likely_source",
                "automation_status",
                "rule_source",
                "notes",
                "registry_version",
                "ct_release",
            ]
        )
        for row in sorted(codes, key=lambda r: r[1]):
            code, nci = row[1:3]
            field, value_type, codelist, likely = mapping.get(
                code, ("", "text", "UNVERIFIED", "external_or_manual")
            )
            writer.writerow(
                [
                    code,
                    names[nci],
                    "review",
                    field,
                    value_type,
                    codelist,
                    likely,
                    "propose" if field else "manual",
                    f"{URL}#CL.C66738.TSPARMCD; NCI {nci}; names C67152",
                    "Code/name from NCI CT. Applicability/requiredness and IG v3.4 coverage "
                    "not established. Fact/response mapping is a project suggestion for review.",
                    "ts-candidates-v1",
                    RELEASE,
                ]
            )
    meta = {
        "source_url": URL,
        "source_sha256": hashlib.sha256(content).hexdigest(),
        "ct_release": RELEASE,
        "codelists": sorted(LISTS),
        "candidate_count": len(codes),
        "scope": "all terms in C66738, not an SDTMIG requirement set",
        "standards_gap": "SDTMIG 3.4/model/errata and requiredness rules not supplied",
        "files": {p.name: hashlib.sha256(p.read_bytes()).hexdigest() for p in (ct_path, path)},
    }
    extraction_rules = Path("config/extraction/protocol-facts-v1.json")
    if extraction_rules.is_file():
        (destination / extraction_rules.name).write_bytes(extraction_rules.read_bytes())
        meta["files"][extraction_rules.name] = hashlib.sha256(
            extraction_rules.read_bytes()
        ).hexdigest()
    (destination / "sources.json").write_text(json.dumps(meta, indent=2) + "\n")
    print(
        f"Generated {len(codes)} source-backed TS candidates; mapped "
        f"{len(set(mapping) & {r[1] for r in codes})} fields."
    )


if __name__ == "__main__":
    build(Path(sys.argv[1]), Path("src/trial_design_workflow/assets"))
