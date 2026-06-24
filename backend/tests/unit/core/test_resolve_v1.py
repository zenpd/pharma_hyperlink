"""resolve_v1 — LLM resolution tie-breaker for ambiguous cross-doc targets.

Covers the new ``LlmDisambiguator.resolve_target`` (parse / validate / confidence
floor / fail-safe) and the ``_pick_sibling_or_llm`` wiring (additive: deterministic
pick wins; LLM only fires on genuine ≥2-candidate ambiguity; never raises).
"""

from __future__ import annotations

from hyperlink_engine.core.detection.llm_disambiguator import (
    DisambiguatorConfig,
    LlmDisambiguator,
)
from hyperlink_engine.orchestration.nodes import _pick_sibling_or_llm


class _FakeTransport:
    """Returns a canned raw response, mimicking a transport."""

    name = "fake"

    def __init__(self, response: str) -> None:
        self._response = response

    def generate(self, prompt: str, *, temperature: float = 0.0) -> str:
        return self._response


def _disamb(response: str) -> LlmDisambiguator:
    return LlmDisambiguator(_FakeTransport(response), DisambiguatorConfig())


# ── resolve_target ────────────────────────────────────────────────────────

def test_resolve_target_picks_valid_id():
    d = _disamb('{"id": "c1", "confidence": 0.9, "rationale": "matches study arm"}')
    out = d.resolve_target(
        ref_text="SAP Section 5.3",
        context="see SAP Section 5.3 for the analysis",
        candidates=[("c0", "sap: studyA_SAP"), ("c1", "sap: studyB_SAP")],
    )
    assert out == "c1"


def test_resolve_target_unknown_id_returns_none():
    d = _disamb('{"id": "c9", "confidence": 0.95}')
    assert d.resolve_target(ref_text="x", context="", candidates=[("c0", "a")]) is None


def test_resolve_target_below_confidence_returns_none():
    d = _disamb('{"id": "c0", "confidence": 0.3}')  # floor defaults to 0.7
    assert d.resolve_target(ref_text="x", context="", candidates=[("c0", "a")]) is None


def test_resolve_target_unparseable_returns_none():
    d = _disamb("the answer is c0, definitely")
    assert d.resolve_target(ref_text="x", context="", candidates=[("c0", "a")]) is None


def test_resolve_target_transport_error_returns_none():
    class _Boom:
        name = "boom"

        def generate(self, prompt: str, *, temperature: float = 0.0) -> str:
            raise RuntimeError("ollama down")

    d = LlmDisambiguator(_Boom(), DisambiguatorConfig())
    assert d.resolve_target(ref_text="x", context="", candidates=[("c0", "a")]) is None


def test_resolve_target_no_candidates_returns_none():
    d = _disamb('{"id": "c0", "confidence": 0.9}')
    assert d.resolve_target(ref_text="x", context="", candidates=[]) is None


# ── _pick_sibling_or_llm wiring (additive, fail-safe) ──────────────────────

class _PickResolver:
    """Records whether it was consulted; returns a fixed id."""

    def __init__(self, pick: str | None) -> None:
        self.pick = pick
        self.calls = 0

    def resolve_target(self, *, ref_text, context, candidates):  # noqa: ANN001
        self.calls += 1
        return self.pick


def test_deterministic_single_candidate_skips_llm():
    cands = [{"path": "a/sap.docx", "doc_type": "sap"}]
    r = _PickResolver("c0")
    out = _pick_sibling_or_llm(cands, "a/source.docx", {"text": "SAP"}, r)
    assert out == "a/sap.docx"
    assert r.calls == 0  # deterministic pick won; LLM never consulted


def test_resolver_none_keeps_unresolved():
    cands = [
        {"path": "a/sap1.docx", "doc_type": "sap"},
        {"path": "a/sap2.docx", "doc_type": "sap"},
    ]
    # two same-format same-dir candidates → _pick_sibling returns None
    assert _pick_sibling_or_llm(cands, "a/source.docx", {"text": "SAP"}, None) is None


def test_llm_recovers_ambiguous_link():
    cands = [
        {"path": "a/sap1.docx", "doc_type": "sap"},
        {"path": "a/sap2.docx", "doc_type": "sap"},
    ]
    det = {"text": "SAP Section 5.3", "context": "per SAP Section 5.3"}
    r = _PickResolver("c1")
    out = _pick_sibling_or_llm(cands, "a/source.docx", det, r)
    assert out == "a/sap2.docx"
    assert r.calls == 1
    assert det.get("llm_resolved") is True


def test_llm_hallucinated_id_stays_unresolved():
    cands = [
        {"path": "a/sap1.docx", "doc_type": "sap"},
        {"path": "a/sap2.docx", "doc_type": "sap"},
    ]
    det = {"text": "SAP", "context": ""}
    r = _PickResolver("c9")  # not a real candidate id
    assert _pick_sibling_or_llm(cands, "a/source.docx", det, r) is None
    assert "llm_resolved" not in det
