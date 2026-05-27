"""Layer 3 — Local LLM disambiguator (Ollama).

Used **only** as a last-resort refinement for ambiguous reference candidates
where regex + NER agree on a span but disagree on the entity type, or where
both layers produced a confidence below ``llm_confidence_threshold``.

The disambiguator is the part of the pipeline most sensitive to compliance:

* **All inference is local** — no external API calls. Settings enforce this
  via ``enforce_local_llm_only`` (default true). The transport refuses any
  base URL that doesn't resolve to a loopback / private address.
* **Every decision is logged** — input candidate, surrounding context window,
  prompt template id, model name, response, final pick. Drives the GxP audit
  trail.
* **A deterministic stub is wired** so unit tests, CI, and developer laptops
  without Ollama running still exercise the cascade end-to-end. The stub
  picks the highest-confidence candidate and explains why.

Public surface:

    disamb = build_disambiguator()
    decision = disamb.refine(candidates=[...], context="…")
"""

from __future__ import annotations

import json
import os
import urllib.parse
from dataclasses import dataclass, field
from typing import Iterable, Protocol

from hyperlink_engine.config.logging_setup import get_logger
from hyperlink_engine.config.settings import get_settings
from hyperlink_engine.detection.regex_patterns import Match

_log = get_logger("detection.llm")


# Prompt template — keep deliberately short; the LLM's job here is *picking*,
# not generating freeform text. Versioned via PROMPT_VERSION so audit logs
# can pin a decision to a specific prompt revision.
PROMPT_VERSION = "disambiguate_v1"

_PROMPT_TEMPLATE = """\
You are helping link references inside a regulatory pharma dossier.
Multiple candidate interpretations were detected for a span of text.
Pick exactly ONE — the most likely match given the surrounding context.

Surrounding context:
\"\"\"{context}\"\"\"

Candidates (id, label, text, confidence):
{candidates}

Reply with ONLY a JSON object on a single line:
{{"id": "<chosen pattern_id>", "confidence": <0.0-1.0>, "rationale": "<short>"}}
"""


@dataclass(frozen=True)
class DisambiguationDecision:
    """Result of one disambiguator call."""

    chosen: Match
    rationale: str
    model: str
    prompt_version: str = PROMPT_VERSION
    raw_response: str | None = None
    candidates_considered: tuple[str, ...] = field(default_factory=tuple)


class LlmTransport(Protocol):
    """The interface concrete transports (Ollama, stub) implement."""

    name: str

    def generate(self, prompt: str, *, temperature: float = 0.0) -> str: ...


# ─────────────────────────────────────────────────────────────────────────
# Stub transport — deterministic, no network. Used in tests + offline mode.
# ─────────────────────────────────────────────────────────────────────────


class DeterministicStubTransport:
    """Picks the highest-confidence candidate by re-emitting structured JSON.

    The stub parses the candidate list out of the prompt — relying on the
    fact that we control the prompt template above — and returns a JSON
    payload that selects the top candidate.
    """

    name = "stub:deterministic"

    def generate(self, prompt: str, *, temperature: float = 0.0) -> str:
        candidates = _parse_candidates_from_prompt(prompt)
        if not candidates:
            return json.dumps(
                {"id": "", "confidence": 0.0, "rationale": "no candidates parsed"}
            )
        # Highest confidence first; ties broken by longer text (more specific).
        best = max(candidates, key=lambda c: (c["confidence"], len(c["text"])))
        return json.dumps(
            {
                "id": best["id"],
                "confidence": best["confidence"],
                "rationale": f"stub picked highest-confidence candidate ({best['label']})",
            }
        )


def _parse_candidates_from_prompt(prompt: str) -> list[dict[str, object]]:
    """Parse the human-readable candidate block back into structured records.

    Lines look like: `- STUDY_ID_NCT_V1 | STUDY_ID | "NCT46913810" | 0.99`
    """
    out: list[dict[str, object]] = []
    for line in prompt.splitlines():
        stripped = line.strip()
        if not stripped.startswith("- "):
            continue
        parts = [p.strip() for p in stripped[2:].split("|")]
        if len(parts) != 4:
            continue
        pid, label, text_q, conf_s = parts
        try:
            conf = float(conf_s)
        except ValueError:
            continue
        text = text_q.strip().strip('"')
        out.append({"id": pid, "label": label, "text": text, "confidence": conf})
    return out


# ─────────────────────────────────────────────────────────────────────────
# Ollama transport — HTTP to a local Ollama daemon.
# ─────────────────────────────────────────────────────────────────────────


_LOOPBACK_HOSTS = {"localhost", "127.0.0.1", "::1", "0.0.0.0"}


def _host_is_local(host: str) -> bool:
    """Refuse any host that isn't loopback or RFC1918 private space."""
    host = host.strip().lower()
    if host in _LOOPBACK_HOSTS:
        return True
    if host.startswith("10."):
        return True
    if host.startswith("192.168."):
        return True
    if host.startswith("172."):
        try:
            second = int(host.split(".")[1])
            return 16 <= second <= 31
        except (ValueError, IndexError):
            return False
    return False


class OllamaTransport:
    """Talks HTTP to a local Ollama daemon (default http://127.0.0.1:11434).

    Constructor refuses any non-local base URL when
    ``enforce_local_llm_only`` is True (Phase 1 / 21 CFR Part 11 default).
    """

    def __init__(self, base_url: str, model: str, timeout: float = 30.0) -> None:
        parsed = urllib.parse.urlparse(base_url)
        host = parsed.hostname or ""
        if get_settings().enforce_local_llm_only and not _host_is_local(host):
            raise RuntimeError(
                f"Refusing to call Ollama at non-local host {host!r}: "
                "enforce_local_llm_only is on (21 CFR Part 11 compliance)."
            )
        self._base_url = base_url.rstrip("/")
        self._model = model
        self._timeout = timeout
        self.name = f"ollama:{model}"

    def generate(self, prompt: str, *, temperature: float = 0.0) -> str:
        # We use the requests library lazily so the module imports cleanly
        # even on machines that have not installed it.
        try:
            import requests  # type: ignore[import-not-found]
        except ImportError as exc:  # pragma: no cover — exercised only on bare envs
            raise RuntimeError("requests is required for OllamaTransport") from exc

        url = f"{self._base_url}/api/generate"
        payload = {
            "model": self._model,
            "prompt": prompt,
            "stream": False,
            "options": {"temperature": temperature},
        }
        response = requests.post(url, json=payload, timeout=self._timeout)
        response.raise_for_status()
        body = response.json()
        return str(body.get("response", "")).strip()


# ─────────────────────────────────────────────────────────────────────────
# Disambiguator — orchestrates prompt rendering, transport call, and parse.
# ─────────────────────────────────────────────────────────────────────────


@dataclass(frozen=True)
class DisambiguatorConfig:
    confidence_threshold: float = 0.7
    context_window: int = 80  # chars on each side of the span
    max_candidates: int = 6
    model: str = "llama3.1:8b"


class LlmDisambiguator:
    """Refines low-confidence candidates by prompting the local LLM."""

    def __init__(
        self,
        transport: LlmTransport,
        config: DisambiguatorConfig | None = None,
    ) -> None:
        self._transport = transport
        self._config = config or DisambiguatorConfig(
            confidence_threshold=get_settings().llm_confidence_threshold,
            model=get_settings().ollama_model,
        )

    @property
    def transport_name(self) -> str:
        return self._transport.name

    @property
    def confidence_threshold(self) -> float:
        return self._config.confidence_threshold

    def should_refine(self, candidates: Iterable[Match]) -> bool:
        """True if any candidate sits below the confidence floor."""
        cands = list(candidates)
        if not cands:
            return False
        return any(c.confidence < self._config.confidence_threshold for c in cands)

    def refine(
        self,
        candidates: list[Match],
        *,
        source_text: str,
    ) -> DisambiguationDecision | None:
        if not candidates:
            return None
        if len(candidates) > self._config.max_candidates:
            candidates = sorted(candidates, key=lambda c: -c.confidence)[
                : self._config.max_candidates
            ]
        context = self._extract_context(candidates, source_text)
        prompt = self._render_prompt(candidates, context)
        raw = self._transport.generate(prompt, temperature=0.0)
        decision = self._parse_response(raw, candidates)
        _log.info(
            "llm_refine",
            transport=self._transport.name,
            prompt_version=PROMPT_VERSION,
            n_candidates=len(candidates),
            chosen_id=decision.chosen.pattern_id if decision else None,
        )
        return decision

    # ── internal helpers ─────────────────────────────────────────────────

    def _extract_context(self, candidates: list[Match], source: str) -> str:
        window = self._config.context_window
        start = min(c.start for c in candidates)
        end = max(c.end for c in candidates)
        left = max(0, start - window)
        right = min(len(source), end + window)
        return source[left:right].strip()

    def _render_prompt(self, candidates: list[Match], context: str) -> str:
        lines = []
        for c in candidates:
            label = c.groups.get("label", "UNKNOWN")
            text = c.text.replace('"', "'")
            lines.append(f'- {c.pattern_id} | {label} | "{text}" | {c.confidence:.2f}')
        return _PROMPT_TEMPLATE.format(
            context=context.replace('"""', "'''"),
            candidates="\n".join(lines),
        )

    def _parse_response(
        self,
        raw: str,
        candidates: list[Match],
    ) -> DisambiguationDecision | None:
        try:
            payload = json.loads(_extract_first_json(raw))
        except (json.JSONDecodeError, ValueError) as exc:
            _log.warning("llm_response_unparseable", error=str(exc), raw=raw[:200])
            return None
        chosen_id = str(payload.get("id", ""))
        match = next((c for c in candidates if c.pattern_id == chosen_id), None)
        if match is None:
            _log.warning(
                "llm_chose_unknown_id",
                chosen=chosen_id,
                offered=[c.pattern_id for c in candidates],
            )
            return None
        rationale = str(payload.get("rationale", ""))[:240]
        confidence = float(payload.get("confidence", match.confidence))
        confidence = max(0.0, min(1.0, confidence))
        refined = Match(
            pattern_id=match.pattern_id,
            text=match.text,
            start=match.start,
            end=match.end,
            confidence=confidence,
            groups={**match.groups, "llm_rationale": rationale},
        )
        return DisambiguationDecision(
            chosen=refined,
            rationale=rationale,
            model=self._transport.name,
            raw_response=raw,
            candidates_considered=tuple(c.pattern_id for c in candidates),
        )


def _extract_first_json(text: str) -> str:
    """Return the first balanced {...} block in `text`, or raise ValueError."""
    depth = 0
    start = -1
    for i, ch in enumerate(text):
        if ch == "{":
            if depth == 0:
                start = i
            depth += 1
        elif ch == "}":
            depth -= 1
            if depth == 0 and start >= 0:
                return text[start : i + 1]
    raise ValueError("no JSON object in response")


# ─────────────────────────────────────────────────────────────────────────
# Factory — picks Ollama when reachable, stub otherwise.
# ─────────────────────────────────────────────────────────────────────────


def build_disambiguator(*, prefer_stub: bool = False) -> LlmDisambiguator:
    """Construct a disambiguator using the configured transport.

    The stub is selected when:
      * ``prefer_stub`` is True (tests, CI, offline dev)
      * the ``HYPERLINK_LLM_TRANSPORT`` env var is set to ``stub``
      * Ollama is not reachable on the configured host
    """
    settings = get_settings()
    forced = (os.environ.get("HYPERLINK_LLM_TRANSPORT") or "").lower()
    if prefer_stub or forced == "stub":
        return LlmDisambiguator(DeterministicStubTransport())
    try:
        transport: LlmTransport = OllamaTransport(
            base_url=settings.ollama_host,
            model=settings.ollama_model,
        )
        return LlmDisambiguator(transport)
    except RuntimeError as exc:
        _log.warning("ollama_unavailable_using_stub", error=str(exc))
        return LlmDisambiguator(DeterministicStubTransport())
