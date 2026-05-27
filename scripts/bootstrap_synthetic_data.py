"""Generate a synthetic CTD dossier for POC testing.

Produces:
    data/synthetic/
        m2/
            2-5-clin-overview/2-5-clin-overview.docx
            2-7-clin-summary/2-7-1-summary-bio.docx
            ...
        m5/
            5-3-1-bio-stud-rep/<study>.docx
            ...
        index.xml          # eCTD backbone v3.2-ish (mock)

Each generated document contains hundreds of intentionally placed reference
strings drawn from the pattern catalog so the detection engine has rich
material to chew on. The mix is tuned for ~25 references per document,
yielding ~500 across a 20-document synthetic Module 2.

Usage:
    python -m scripts.bootstrap_synthetic_data --out data/synthetic --docs 20
"""

from __future__ import annotations

import argparse
import random
import textwrap
from dataclasses import dataclass
from pathlib import Path

from docx import Document
from lxml import etree


SPONSOR_PREFIXES = ["SP", "SUNP", "SPL", "ABC", "XYZ", "MED"]
SECTION_NUMBERS = [
    "2.5.1", "2.5.2", "2.5.3", "2.5.4", "2.5.5",
    "2.7.1", "2.7.2", "2.7.3", "2.7.4",
    "5.3.1", "5.3.2", "5.3.3", "5.3.4", "5.3.5",
    "3.2.P.5", "3.2.S.4",
]
TABLE_NUMBERS = ["14.2.1.1", "14.2.2.1", "11.4", "14.1.1", "5.3-1", "2.7.3-1", "16.1.1"]
FIGURE_NUMBERS = ["11", "14.2.1", "5", "2.7-1", "5.3-2"]
LISTING_NUMBERS = ["16.2.5", "16.1.1", "16.2.7", "16.2.5.1", "14-1"]
APPENDIX_NUMBERS = ["16.1.1", "16.2.5", "16.1.4", "16.2"]
MODULE_NUMBERS = ["5.3.1", "5.3.5", "2.5.3", "2.7.4", "3.2.P.5", "1.3.1"]


@dataclass
class StudyMeta:
    study_id: str
    nct_id: str
    sponsor: str


def _random_study() -> StudyMeta:
    sponsor = random.choice(SPONSOR_PREFIXES)
    year = random.randint(2020, 2025)
    seq = random.randint(1, 999)
    nct = f"NCT{random.randint(10000000, 99999999):08d}"
    return StudyMeta(
        study_id=f"{sponsor}-{year}-{seq:03d}",
        nct_id=nct,
        sponsor=sponsor,
    )


def _sentence(study: StudyMeta) -> str:
    """Build a single sentence containing 1–3 references."""
    templates = [
        "Demographic data are summarized in Table {table} of Section {section}.",
        "As described in Section {section}, study {study} demonstrated efficacy.",
        "Refer to Module {module} for the full CSR of {study} ({nct}).",
        "See Figure {figure} and Listing {listing} for adverse-event distributions.",
        "Per §{section}, the safety profile was acceptable; details in Appendix {appendix}.",
        "Pharmacokinetic results for {study} are tabulated in Table {table}.",
        "The {study} ({nct}) cohort is described in Section {section} and Module {module}.",
        "Listing {listing} (Appendix {appendix}) enumerates serious adverse events.",
        "Figure {figure} shows dose-response data referenced in §{section}.",
        "Cross-references to Module {module} and Section {section} are documented in Table {table}.",
    ]
    tmpl = random.choice(templates)
    return tmpl.format(
        section=random.choice(SECTION_NUMBERS),
        table=random.choice(TABLE_NUMBERS),
        figure=random.choice(FIGURE_NUMBERS),
        listing=random.choice(LISTING_NUMBERS),
        appendix=random.choice(APPENDIX_NUMBERS),
        module=random.choice(MODULE_NUMBERS),
        study=study.study_id,
        nct=study.nct_id,
    )


def _document_body(study: StudyMeta, sentences_per_doc: int) -> list[str]:
    paragraphs: list[str] = []
    paragraphs.append(f"Clinical Overview for {study.study_id} ({study.nct_id})")
    paragraphs.append("")
    paragraphs.append("Background")
    # Group sentences into paragraphs of 3–5 sentences each
    bucket: list[str] = []
    for _ in range(sentences_per_doc):
        bucket.append(_sentence(study))
        if len(bucket) >= random.randint(3, 5):
            paragraphs.append(" ".join(bucket))
            bucket = []
    if bucket:
        paragraphs.append(" ".join(bucket))
    return paragraphs


CTD_LAYOUT: list[tuple[str, str]] = [
    ("m2/2-5-clin-overview/2-5-clin-overview.docx", "2.5 Clinical Overview"),
    ("m2/2-7-clin-summary/2-7-1-summary-bio.docx", "2.7.1 Summary of Biopharmaceutic Studies"),
    ("m2/2-7-clin-summary/2-7-2-summary-clin-pharm.docx", "2.7.2 Summary of Clinical Pharmacology"),
    ("m2/2-7-clin-summary/2-7-3-summary-clin-efficacy.docx", "2.7.3 Summary of Clinical Efficacy"),
    ("m2/2-7-clin-summary/2-7-4-summary-clin-safety.docx", "2.7.4 Summary of Clinical Safety"),
    ("m5/5-3-1-bio-stud-rep/study-001.docx", "5.3.1 BA/BE Study Report"),
    ("m5/5-3-1-bio-stud-rep/study-002.docx", "5.3.1 BA/BE Study Report"),
    ("m5/5-3-3-pk-stud-rep/study-pk-01.docx", "5.3.3 PK Study Report"),
    ("m5/5-3-5-efficacy-safety/study-eff-01.docx", "5.3.5 Efficacy/Safety Study Report"),
    ("m5/5-3-5-efficacy-safety/study-eff-02.docx", "5.3.5 Efficacy/Safety Study Report"),
    ("m3/3-2-quality/3-2-s-drug-substance.docx", "3.2.S Drug Substance"),
    ("m3/3-2-quality/3-2-p-drug-product.docx", "3.2.P Drug Product"),
    ("m4/4-2-stud-rep/nonclin-01.docx", "4.2 Non-Clinical Study Reports"),
    ("m4/4-2-stud-rep/nonclin-02.docx", "4.2 Non-Clinical Study Reports"),
    ("m1/us/1-3-1-letter.docx", "1.3.1 Cover Letter (US)"),
    ("m1/eu/1-3-1-letter.docx", "1.3.1 Cover Letter (EU)"),
    ("m2/2-3-quality-overall.docx", "2.3 Quality Overall Summary"),
    ("m2/2-4-nonclin-overview.docx", "2.4 Nonclinical Overview"),
    ("m2/2-6-nonclin-summary.docx", "2.6 Nonclinical Summary"),
    ("m5/5-3-7-case-report-forms.docx", "5.3.7 Case Report Forms"),
]


def generate_documents(out_dir: Path, num_docs: int, sentences_per_doc: int) -> list[Path]:
    out_dir.mkdir(parents=True, exist_ok=True)
    rng = random.Random(42)
    random.seed(42)  # deterministic for reproducibility

    selected = CTD_LAYOUT[:num_docs] if num_docs <= len(CTD_LAYOUT) else CTD_LAYOUT
    created: list[Path] = []

    for rel_path, title in selected:
        study = _random_study()
        target = out_dir / rel_path
        target.parent.mkdir(parents=True, exist_ok=True)

        doc = Document()
        doc.add_heading(title, level=1)
        doc.add_paragraph(f"Document path: {rel_path}")
        doc.add_paragraph("")

        for para in _document_body(study, sentences_per_doc):
            if not para:
                doc.add_paragraph("")
            elif len(para) < 80 and not para.endswith("."):
                doc.add_heading(para, level=2)
            else:
                doc.add_paragraph(para)

        doc.save(str(target))
        created.append(target)
        _ = rng  # placeholder; reserved if we want per-doc randomization later
    return created


def generate_index_xml(out_dir: Path, docs: list[Path]) -> Path:
    """Build a minimal eCTD backbone index.xml referencing every generated leaf."""
    nsmap = {
        None: "urn:hl7-org:v3",
        "xlink": "http://www.w3.org/1999/xlink",
    }
    root = etree.Element(
        "ectd",
        nsmap=nsmap,
        attrib={"dtd-version": "3.2"},
    )
    submission = etree.SubElement(
        root,
        "fda-regional",
        attrib={"submission-type": "ind", "submission-id": "synthetic-0001"},
    )

    for path in docs:
        rel = path.relative_to(out_dir).as_posix()
        leaf = etree.SubElement(
            submission,
            "leaf",
            attrib={
                "ID": f"leaf-{abs(hash(rel)) % 10**8}",
                "operation": "new",
                "{http://www.w3.org/1999/xlink}href": rel,
            },
        )
        title = etree.SubElement(leaf, "title")
        title.text = path.stem

    index = out_dir / "index.xml"
    tree = etree.ElementTree(root)
    tree.write(
        str(index),
        pretty_print=True,
        xml_declaration=True,
        encoding="UTF-8",
        standalone=False,
    )
    return index


def generate_manifest(out_dir: Path, docs: list[Path]) -> Path:
    manifest = out_dir / "MANIFEST.txt"
    lines = [
        "Synthetic CTD dossier",
        "=====================",
        f"Generated by scripts/bootstrap_synthetic_data.py",
        f"Document count: {len(docs)}",
        "",
        "Files:",
    ]
    for path in docs:
        rel = path.relative_to(out_dir).as_posix()
        lines.append(f"  - {rel}")
    manifest.write_text("\n".join(lines), encoding="utf-8")
    return manifest


def main() -> None:
    parser = argparse.ArgumentParser(description=textwrap.dedent(__doc__ or ""))
    parser.add_argument(
        "--out",
        type=Path,
        default=Path("data/synthetic"),
        help="Output directory (default: data/synthetic)",
    )
    parser.add_argument(
        "--docs",
        type=int,
        default=20,
        help="Number of documents to generate (default: 20)",
    )
    parser.add_argument(
        "--sentences-per-doc",
        type=int,
        default=25,
        help="Sentences per document — drives reference density (default: 25)",
    )
    args = parser.parse_args()

    docs = generate_documents(args.out, args.docs, args.sentences_per_doc)
    index_path = generate_index_xml(args.out, docs)
    manifest_path = generate_manifest(args.out, docs)

    total_refs_estimate = len(docs) * args.sentences_per_doc * 2  # ~2 refs/sentence
    print(f"Generated {len(docs)} documents under {args.out}")
    print(f"Wrote eCTD backbone: {index_path}")
    print(f"Wrote manifest:      {manifest_path}")
    print(f"Estimated references embedded: ~{total_refs_estimate}")


if __name__ == "__main__":
    main()
