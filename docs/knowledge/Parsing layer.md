# Parsing layer

Layer 2 — turn raw files into token streams with location anchors detection/injection can map back to.

## How it works
- docx → paragraphs + runs/styles: `core/parsing/docx_parser.py`.
- pdf → pages, spans, blocks, existing link annotations: `core/parsing/pdf_parser.py`.
- `node_parse_all` in `orchestration/nodes.py` records para/run counts.
- `_read_docx_blocks` (in `workers/tasks.py`) yields typed blocks (paragraph / table) reused by every preview panel, keeping `text` on each block so a table is still found by its dotted number.

## Gotchas
- PDF table parsing (`find_tables`) is the slow part of preview — kept text-only for snippets.

## Related
[[Ingestion layer]] · [[Detection cascade]] · [[Injection layer]] · [[_Home]]
