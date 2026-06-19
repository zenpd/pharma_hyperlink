"""Bootstrap a labeled training corpus from the synthetic dossier.

The W3 spaCy NER model needs at least a few hundred labeled spans before
fine-tuning is worth anything. Rather than hand-label, we use the W1 regex
engine as a weak labeler over the synthetic dossier we already generate.
The result is "noisy but large" — perfectly fine for bootstrapping a NER
model whose job is to add **recall** that the regex engine misses.

Output:
    data/training/refs.train.jsonl
    data/training/refs.dev.jsonl
    data/training/refs.manifest.json

Each JSONL line is a spaCy-compatible record:
    {"text": "...", "entities": [[start, end, "STUDY_ID"], ...]}

Run via:
    python -m scripts.label_references --out data/training --dev-ratio 0.15
"""

from __future__ import annotations

import argparse
import json
import random
from dataclasses import dataclass
from pathlib import Path

from docx import Document

from hyperlink_engine.core.detection.regex_patterns import default_registry, resolve_overlaps


@dataclass
class LabeledExample:
    text: str
    entities: list[tuple[int, int, str]]
    source_doc: str
    paragraph_index: int


def _collect_paragraph_text(docx_path: Path) -> list[tuple[int, str]]:
    """Return (paragraph_index, text) for non-empty paragraphs in a .docx."""
    doc = Document(str(docx_path))
    out: list[tuple[int, str]] = []
    for idx, para in enumerate(doc.paragraphs):
        text = "".join(run.text for run in para.runs)
        if text.strip():
            out.append((idx, text))
    return out


def _label_text(text: str, registry) -> list[tuple[int, int, str]]:  # type: ignore[no-untyped-def]
    matches = resolve_overlaps(registry.find_all(text))
    out: list[tuple[int, int, str]] = []
    for m in matches:
        out.append((m.start, m.end, registry.get(m.pattern_id).label))
    return out


def build_corpus(synthetic_root: Path) -> list[LabeledExample]:
    if not synthetic_root.exists():
        raise SystemExit(
            f"{synthetic_root} does not exist — run `make synthetic` first."
        )
    registry = default_registry()
    examples: list[LabeledExample] = []
    for docx in sorted(synthetic_root.rglob("*.docx")):
        for p_idx, text in _collect_paragraph_text(docx):
            entities = _label_text(text, registry)
            if not entities:
                continue  # drop paragraphs with zero refs — they hurt NER signal
            examples.append(
                LabeledExample(
                    text=text,
                    entities=entities,
                    source_doc=str(docx.relative_to(synthetic_root)),
                    paragraph_index=p_idx,
                )
            )
    return examples


def split_train_dev(
    examples: list[LabeledExample], dev_ratio: float, seed: int
) -> tuple[list[LabeledExample], list[LabeledExample]]:
    rng = random.Random(seed)
    shuffled = examples.copy()
    rng.shuffle(shuffled)
    dev_size = max(1, int(len(shuffled) * dev_ratio))
    return shuffled[dev_size:], shuffled[:dev_size]


def write_jsonl(examples: list[LabeledExample], path: Path) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8") as fh:
        for ex in examples:
            fh.write(
                json.dumps(
                    {
                        "text": ex.text,
                        "entities": [list(e) for e in ex.entities],
                        "source_doc": ex.source_doc,
                        "paragraph_index": ex.paragraph_index,
                    },
                    ensure_ascii=False,
                )
                + "\n"
            )


def _entity_histogram(examples: list[LabeledExample]) -> dict[str, int]:
    counts: dict[str, int] = {}
    for ex in examples:
        for _, _, label in ex.entities:
            counts[label] = counts.get(label, 0) + 1
    return counts


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="label-references")
    parser.add_argument(
        "--synthetic",
        type=Path,
        default=Path("data/synthetic"),
        help="Root of the synthetic dossier (defaults to data/synthetic)",
    )
    parser.add_argument(
        "--out",
        type=Path,
        default=Path("data/training"),
        help="Output directory for JSONL splits",
    )
    parser.add_argument("--dev-ratio", type=float, default=0.15)
    parser.add_argument("--seed", type=int, default=42)
    args = parser.parse_args(argv)

    examples = build_corpus(args.synthetic)
    train, dev = split_train_dev(examples, args.dev_ratio, args.seed)

    train_path = args.out / "refs.train.jsonl"
    dev_path = args.out / "refs.dev.jsonl"
    manifest_path = args.out / "refs.manifest.json"

    write_jsonl(train, train_path)
    write_jsonl(dev, dev_path)

    manifest = {
        "synthetic_root": str(args.synthetic),
        "seed": args.seed,
        "dev_ratio": args.dev_ratio,
        "total_examples": len(examples),
        "train_examples": len(train),
        "dev_examples": len(dev),
        "label_histogram": _entity_histogram(examples),
        "train_path": str(train_path),
        "dev_path": str(dev_path),
    }
    manifest_path.write_text(json.dumps(manifest, indent=2), encoding="utf-8")

    print(f"Wrote {len(train)} train + {len(dev)} dev examples")
    print(f"Manifest: {manifest_path}")
    for label, count in sorted(manifest["label_histogram"].items()):
        print(f"  {label:<14} {count}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
