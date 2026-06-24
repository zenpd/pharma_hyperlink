"""Plan Three — run-scoped document-preview endpoint test."""

from __future__ import annotations

import asyncio
from pathlib import Path

import pytest

pytest.importorskip("fastapi")
import httpx  # noqa: E402

from hyperlink_engine.api.app import create_app  # noqa: E402
from hyperlink_engine.orchestration.runner import PipelineRunner  # noqa: E402
from hyperlink_engine.orchestration.state import PipelineState, run_store  # noqa: E402


def _get(app, url: str) -> httpx.Response:
    async def _run() -> httpx.Response:
        transport = httpx.ASGITransport(app=app)
        async with httpx.AsyncClient(transport=transport, base_url="http://test") as client:
            return await client.get(url)
    return asyncio.run(_run())


def _sample_docs() -> list[Path]:
    docs = sorted(Path("data/synthetic/m2").glob("*.docx"))[:2]
    if not docs:
        pytest.skip("no synthetic .docx fixtures available")
    return docs


def test_agents_catalog_endpoint() -> None:
    app = create_app()
    resp = _get(app, "/api/agents")
    assert resp.status_code == 200
    body = resp.json()
    assert "detect" in body["agents"]
    assert {a["id"] for a in body["agents"]["detect"]} == {
        "detect_regex", "detect_ner", "detect_hybrid"
    }


def test_run_document_preview_before_after(tmp_path: Path) -> None:
    docs = _sample_docs()
    state = PipelineState.new(docs, tmp_path / "out", "DOS-PREVIEW-TEST")
    run_store.create(state)
    final = PipelineRunner().invoke(state)
    assert final["status"] == "done"
    run_id = final["run_id"]

    doc_name = docs[0].name
    app = create_app()
    resp = _get(app, f"/api/pipeline/run/{run_id}/document-preview?doc={doc_name}")
    assert resp.status_code == 200
    body = resp.json()

    # BEFORE: original paragraphs are present
    assert body["doc_name"] == doc_name
    assert len(body["paragraphs"]) > 0
    # AFTER: link records carry the fields the compare widget renders
    assert body["total_links"] == len(body["links"])
    if body["links"]:
        first = body["links"][0]
        for key in ("link_text", "status", "confidence"):
            assert key in first


def test_run_document_preview_unknown_doc_404(tmp_path: Path) -> None:
    docs = _sample_docs()
    state = PipelineState.new(docs, tmp_path / "out", "DOS-PREVIEW-404")
    run_store.create(state)
    PipelineRunner().invoke(state)
    app = create_app()
    resp = _get(app, f"/api/pipeline/run/{state['run_id']}/document-preview?doc=nope.docx")
    assert resp.status_code == 404
