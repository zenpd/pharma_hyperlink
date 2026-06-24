"""PLAN FIFTEEN — the /results endpoint stamps a per-document link-type
breakdown (internal / cross_doc / external / broken) onto each ``per_doc``
entry so the Pipeline screen can render the same four buckets the BeforeAfter
compare widget shows.

Invariants locked here:
  * internal + cross_doc + external == links   (the three kinds partition)
  * broken is a status overlay counted independently (a broken link is still
    one of the three kinds, so it does NOT add a fourth partition)
  * sum(per_doc.broken) == top-level broken_links
"""

from __future__ import annotations

import asyncio
from pathlib import Path

import pytest

pytest.importorskip("fastapi")

import httpx  # noqa: E402

from hyperlink_engine.api.app import create_app  # noqa: E402
from hyperlink_engine.orchestration.state import PipelineState, run_store  # noqa: E402


def _get(app, url: str) -> httpx.Response:
    async def _run() -> httpx.Response:
        transport = httpx.ASGITransport(app=app)
        async with httpx.AsyncClient(transport=transport, base_url="http://test") as c:
            return await c.get(url)

    return asyncio.run(_run())


def _link(source_doc: str, text: str, kind: str, status: str = "ok") -> dict:
    return {
        "source_doc": source_doc,
        "link_text": text,
        "link_location_descriptor": "",
        "target_doc": "",
        "target_anchor": "",
        "link_kind": kind,
        "status": status,
        "confidence": 1.0,
        "error_msg": None,
    }


def test_results_per_doc_carries_link_type_breakdown(tmp_path: Path) -> None:
    src = "NCT99_SAP.docx"  # source basename the links carry
    state = PipelineState.new([tmp_path / src], tmp_path, dossier_id="DOS-TEST")
    state["status"] = "completed"
    state["score"] = 100.0
    state["grade"] = "A"
    state["linked_files"] = [tmp_path / "NCT99_SAP_linked.docx"]
    state["links"] = [
        _link(src, "Section 2.5", "internal_bookmark"),
        _link(src, "Section 6.3", "internal_bookmark", status="broken"),  # internal + broken overlay
        _link(src, "Table 3", "cross_doc"),
        _link(src, "https://clinicaltrials.gov", "external_url"),
    ]
    run_store.create(state)
    rid = state["run_id"]

    app = create_app()
    try:
        resp = _get(app, f"/api/pipeline/run/{rid}/results")
        assert resp.status_code == 200, resp.text
        body = resp.json()

        per_doc = {d["filename"]: d for d in body["per_doc"]}
        entry = per_doc["NCT99_SAP_linked.docx"]

        assert entry["links"] == 4
        assert entry["internal"] == 2          # two internal_bookmark (one of them broken)
        assert entry["cross_doc"] == 1
        assert entry["external"] == 1
        assert entry["broken"] == 1            # status overlay, not a 4th partition

        # The three kinds partition the links exactly.
        assert entry["internal"] + entry["cross_doc"] + entry["external"] == entry["links"]
        # Per-doc broken reconciles with the run-level broken count.
        assert sum(d["broken"] for d in body["per_doc"]) == body["broken_links"]
    finally:
        run_store._runs.pop(rid, None)  # keep the shared store clean for other tests
