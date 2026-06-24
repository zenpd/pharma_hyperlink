# Injection layer

Layer 4 — write hyperlinks into new `_linked` copies, never the originals.

## How it works
- Word hyperlinks + bookmarks: `core/injection/docx_linker.py`; PDF link annotations sized to the matched phrase: `core/injection/pdf_linker.py`.
- Dosscriber-aware style preservation: `core/injection/style_preserver.py`.
- eCTD cross-references / backbone writing: `core/injection/ectd_xref.py`, `core/injection/ectd_backbone_writer.py`.
- `node_inject_links` in `orchestration/nodes.py` pre-builds the anchor index and provisions cross-doc bookmarks, then calls `inject_links` in `workers/tasks.py`.

## Gotchas
- Originals are never mutated — output is always `*_linked.docx` / `*_linked.pdf` (see [[Auth and compliance]]).

## Related
[[Resolution and anchoring]] · [[Validation layer]] · [[Run Compare and link navigation]] · [[_Home]]
