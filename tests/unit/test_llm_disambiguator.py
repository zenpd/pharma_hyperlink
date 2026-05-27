"""Unit tests for detection/llm_disambiguator.py."""

from __future__ import annotations

import pytest

from hyperlink_engine.detection.llm_disambiguator import (
    DeterministicStubTransport,
    DisambiguatorConfig,
    LlmDisambiguator,
    OllamaTransport,
    _extract_first_json,
    _host_is_local,
    _parse_candidates_from_prompt,
    build_disambiguator,
)
from hyperlink_engine.detection.regex_patterns import Match


def _candidate(pid: str, label: str, conf: float, start: int = 0, end: int = 12) -> Match:
    return Match(
        pattern_id=pid,
        text="MED-2020-026",
        start=start,
        end=end,
        confidence=conf,
        groups={"label": label},
    )


# ── Stub transport ──────────────────────────────────────────────────────


def test_stub_picks_highest_confidence_candidate() -> None:
    disamb = LlmDisambiguator(DeterministicStubTransport())
    candidates = [
        _candidate("STUDY_ID_SPONSOR_V1", "STUDY_ID", 0.55),
        _candidate("STUDY_ID_NCT_V1", "STUDY_ID", 0.95),
    ]
    decision = disamb.refine(candidates, source_text="Study MED-2020-026 mentioned.")
    assert decision is not None
    assert decision.chosen.pattern_id == "STUDY_ID_NCT_V1"
    assert "highest-confidence" in decision.rationale


def test_should_refine_returns_true_for_low_confidence() -> None:
    disamb = LlmDisambiguator(
        DeterministicStubTransport(),
        DisambiguatorConfig(confidence_threshold=0.8),
    )
    assert disamb.should_refine([_candidate("X", "STUDY_ID", 0.6)]) is True
    assert disamb.should_refine([_candidate("X", "STUDY_ID", 0.95)]) is False
    assert disamb.should_refine([]) is False


def test_refine_returns_none_for_empty_candidates() -> None:
    disamb = LlmDisambiguator(DeterministicStubTransport())
    assert disamb.refine([], source_text="anything") is None


def test_refine_caps_candidates_to_max() -> None:
    disamb = LlmDisambiguator(
        DeterministicStubTransport(), DisambiguatorConfig(max_candidates=2)
    )
    candidates = [
        _candidate("A", "STUDY_ID", 0.5),
        _candidate("B", "STUDY_ID", 0.6),
        _candidate("C", "STUDY_ID", 0.9),
    ]
    decision = disamb.refine(candidates, source_text="ctx")
    assert decision is not None
    # The top-2 by confidence are B (0.6) and C (0.9); stub picks C.
    assert decision.chosen.pattern_id == "C"


# ── Local-host guard ────────────────────────────────────────────────────


@pytest.mark.parametrize(
    "host,expected",
    [
        ("127.0.0.1", True),
        ("localhost", True),
        ("::1", True),
        ("10.0.0.5", True),
        ("192.168.1.20", True),
        ("172.16.5.6", True),
        ("172.31.255.255", True),
        ("172.32.0.1", False),
        ("8.8.8.8", False),
        ("api.openai.com", False),
        ("", False),
    ],
)
def test_host_is_local(host: str, expected: bool) -> None:
    assert _host_is_local(host) is expected


def test_ollama_refuses_remote_host(monkeypatch: pytest.MonkeyPatch) -> None:
    # Default settings have enforce_local_llm_only=True.
    with pytest.raises(RuntimeError, match="non-local host"):
        OllamaTransport(base_url="https://api.openai.com", model="llama3.1:8b")


# ── JSON helpers ────────────────────────────────────────────────────────


def test_extract_first_json_handles_prefix_and_suffix() -> None:
    raw = 'sure, here it is: {"id":"X","confidence":0.9,"rationale":"yes"} thanks!'
    assert _extract_first_json(raw) == '{"id":"X","confidence":0.9,"rationale":"yes"}'


def test_extract_first_json_raises_when_missing() -> None:
    with pytest.raises(ValueError):
        _extract_first_json("no json here, sorry")


def test_parse_candidates_from_prompt_round_trip() -> None:
    prompt = (
        "Candidates (id, label, text, confidence):\n"
        '- STUDY_ID_NCT_V1 | STUDY_ID | "NCT46913810" | 0.99\n'
        '- STUDY_ID_SPONSOR_V1 | STUDY_ID | "MED-2020-026" | 0.55\n'
    )
    parsed = _parse_candidates_from_prompt(prompt)
    assert len(parsed) == 2
    assert parsed[0]["id"] == "STUDY_ID_NCT_V1"
    assert parsed[1]["confidence"] == 0.55


# ── Bad-response handling ───────────────────────────────────────────────


class _BrokenTransport:
    name = "stub:broken"

    def generate(self, prompt: str, *, temperature: float = 0.0) -> str:
        return "this is not json at all"


def test_refine_returns_none_on_unparseable_response() -> None:
    disamb = LlmDisambiguator(_BrokenTransport())
    decision = disamb.refine(
        [_candidate("X", "STUDY_ID", 0.5)], source_text="ctx"
    )
    assert decision is None


class _LiarTransport:
    name = "stub:liar"

    def generate(self, prompt: str, *, temperature: float = 0.0) -> str:
        return '{"id":"NOT_AN_OFFERED_ID","confidence":0.9,"rationale":"hi"}'


def test_refine_returns_none_when_llm_picks_unknown_id() -> None:
    disamb = LlmDisambiguator(_LiarTransport())
    decision = disamb.refine(
        [_candidate("X", "STUDY_ID", 0.5)], source_text="ctx"
    )
    assert decision is None


# ── Factory ─────────────────────────────────────────────────────────────


def test_factory_prefers_stub_when_requested() -> None:
    disamb = build_disambiguator(prefer_stub=True)
    assert disamb.transport_name == DeterministicStubTransport.name


def test_factory_respects_env_var(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("HYPERLINK_LLM_TRANSPORT", "stub")
    disamb = build_disambiguator()
    assert disamb.transport_name.startswith("stub")
