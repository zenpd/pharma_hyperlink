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
from hyperlink_engine.core.detection.regex_patterns import Match

try:  # LangSmith tracing is optional (dev-only). Degrade to a no-op decorator.
    from langsmith import traceable as _traceable
except Exception:  # pragma: no cover - langsmith not installed

    def _traceable(*dargs, **dkwargs):  # type: ignore[no-redef]
        # Support both bare @_traceable and parameterised @_traceable(...).
        if dargs and callable(dargs[0]) and not dkwargs:
            return dargs[0]

        def _wrap(fn):
            return fn

        return _wrap


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


# Resolution tie-breaker prompt ("resolve_v1"). Distinct job from the type
# disambiguator above: the reference is already FOUND — here several candidate
# *target documents* fit and we pick which one the link should point to. Used
# only when the deterministic resolver cannot separate ≥2 candidates.
RESOLVE_PROMPT_VERSION = "resolve_v1"

_RESOLVE_TEMPLATE = """\
You are linking a cross-reference inside a regulatory pharma dossier to the
correct target DOCUMENT. The reference was found; several documents could be its
target. Pick exactly ONE — the most likely, given the reference and its context.

Reference text:
\"\"\"{ref}\"\"\"

Surrounding context:
\"\"\"{context}\"\"\"

Candidate target documents (id, type, filename):
{candidates}

Reply with ONLY a JSON object on a single line:
{{"id": "<chosen id>", "confidence": <0.0-1.0>, "rationale": "<short>"}}
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


class NvidiaTransport:
    """OpenAI-compatible chat-completions transport (NVIDIA API Catalog, etc.).

    REMOTE — sends the prompt off-machine to a cloud GPU endpoint. Selected only
    when ``llm_provider="nvidia"``. Intended for POC / synthetic-data demos; the
    local :class:`OllamaTransport` remains the default and the GxP product path.
    Same ``generate(prompt) -> str`` contract as the local transport, so the
    disambiguator's prompt template, JSON parsing, and logging are unchanged.
    """

    def __init__(
        self, base_url: str, model: str, api_key: str, timeout: float = 60.0
    ) -> None:
        if not api_key:
            raise RuntimeError(
                "llm_provider='nvidia' but no API key set "
                "(HYPERLINK_LLM_API_KEY)."
            )
        self._base_url = base_url.rstrip("/")
        self._model = model
        self._api_key = api_key
        self._timeout = timeout
        self.name = f"nvidia:{model}"

    def generate(self, prompt: str, *, temperature: float = 0.0) -> str:
        try:
            import requests  # type: ignore[import-not-found]
        except ImportError as exc:  # pragma: no cover — bare env
            raise RuntimeError("requests is required for NvidiaTransport") from exc

        url = f"{self._base_url}/chat/completions"
        payload = {
            "model": self._model,
            "messages": [{"role": "user", "content": prompt}],
            "temperature": temperature,
            "max_tokens": get_settings().llm_max_tokens,
            "stream": False,
        }
        headers = {
            "Authorization": f"Bearer {self._api_key}",
            "Accept": "application/json",
        }
        response = requests.post(
            url, json=payload, headers=headers, timeout=self._timeout
        )
        response.raise_for_status()
        body = response.json()
        choices = body.get("choices") or []
        if not choices:
            return ""
        return str(choices[0].get("message", {}).get("content", "")).strip()


# In-process dedupe cache: identical (model, prompt) → response. Disambiguation
# runs at temperature 0 (deterministic), so caching repeated spans is safe and
# skips redundant calls (e.g. the same study-id confirmed across many docs).
_LITELLM_CACHE: dict[str, str] = {}


class LiteLlmTransport:
    """Unified transport via **LiteLLM** — one client for local Ollama, NVIDIA
    NIM, and other OpenAI-compatible providers. Selected by
    :func:`build_disambiguator` from ``llm_provider``. Supports an optional
    cloud→local ``fallback`` and an in-process dedupe cache. Same
    ``generate(prompt) -> str`` contract as the native transports, so the
    disambiguator, prompt template, parsing, and logging are unchanged.
    """

    def __init__(
        self,
        model: str,
        *,
        api_base: str | None = None,
        api_key: str | None = None,
        timeout: float = 60.0,
        fallback: dict[str, str] | None = None,
        label: str | None = None,
    ) -> None:
        self._model = model
        self._api_base = api_base
        self._api_key = api_key
        self._timeout = timeout
        self._fallback = fallback  # {"model":..., "api_base":?, "api_key":?}
        self.name = label or f"litellm:{model}"

    def _complete(
        self,
        model: str,
        prompt: str,
        temperature: float,
        api_base: str | None,
        api_key: str | None,
    ) -> str:
        import logging as _logging

        import litellm  # lazy import — only when the LiteLLM path is used

        # Quiet LiteLLM's own INFO logger so our structured logs stay clean.
        _logging.getLogger("LiteLLM").setLevel(_logging.WARNING)
        litellm.telemetry = False  # GxP: no phone-home
        litellm.suppress_debug_info = True
        litellm.drop_params = True  # tolerate provider-specific param gaps
        resp = litellm.completion(
            model=model,
            messages=[{"role": "user", "content": prompt}],
            temperature=temperature,
            max_tokens=get_settings().llm_max_tokens,
            api_base=api_base,
            api_key=api_key,
            timeout=self._timeout,
        )
        msg = resp.choices[0].message
        content = getattr(msg, "content", None)
        if content is None and isinstance(msg, dict):
            content = msg.get("content")
        return str(content or "").strip()

    def generate(self, prompt: str, *, temperature: float = 0.0) -> str:
        cache_key = f"{self._model}\x00{hash(prompt)}"
        hit = _LITELLM_CACHE.get(cache_key)
        if hit is not None:
            return hit
        try:
            out = self._complete(
                self._model, prompt, temperature, self._api_base, self._api_key
            )
        except Exception as exc:  # noqa: BLE001 — try the local fallback if set
            if not self._fallback:
                raise
            _log.warning(
                "litellm_primary_failed_using_fallback",
                model=self._model,
                fallback=self._fallback.get("model"),
                error=str(exc),
            )
            out = self._complete(
                self._fallback["model"],
                prompt,
                temperature,
                self._fallback.get("api_base"),
                self._fallback.get("api_key"),
            )
        _LITELLM_CACHE[cache_key] = out
        return out


# ─────────────────────────────────────────────────────────────────────────
# Disambiguator — orchestrates prompt rendering, transport call, and parse.
# ─────────────────────────────────────────────────────────────────────────


@dataclass(frozen=True)
class DisambiguatorConfig:
    confidence_threshold: float = 0.7
    context_window: int = 80  # chars on each side of the span
    max_candidates: int = 6
    model: str = "llama3.2:3b"
    # When True every span is refined by the LLM regardless of confidence.
    force_refine: bool = False


@_traceable(run_type="llm", name="ollama_disambiguate")
def _traced_generate(prompt: str, *, transport: "LlmTransport", model: str) -> str:
    """One LLM disambiguation call, isolated so LangSmith captures the prompt
    (input) and the raw model response (output) as a child run nested under the
    ``detect_references`` node. When LangSmith is inactive this is a plain
    function call (the decorator is a no-op)."""
    return transport.generate(prompt, temperature=0.0)


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
            force_refine=get_settings().llm_force_refine,
        )

    @property
    def transport_name(self) -> str:
        return self._transport.name

    @property
    def confidence_threshold(self) -> float:
        return self._config.confidence_threshold

    @property
    def force_refine(self) -> bool:
        return self._config.force_refine

    def should_refine(self, candidates: Iterable[Match]) -> bool:
        """True if any candidate sits below the confidence floor.

        When ``force_refine`` is set, any non-empty candidate list triggers
        refinement — the LLM is consulted for every span, not only the
        low-confidence ones.
        """
        cands = list(candidates)
        if not cands:
            return False
        if self._config.force_refine:
            return True
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
        try:
            raw = _traced_generate(
                prompt, transport=self._transport, model=self._config.model
            )
        except Exception as exc:  # noqa: BLE001 — a transport hiccup must never drop detections
            # Ollama down, model missing, timeout, etc. → keep the original
            # regex/NER match instead of losing the span (and the whole doc).
            _log.warning(
                "llm_transport_error_keeping_original",
                transport=self._transport.name,
                error=str(exc),
            )
            return None
        # Full prompt + raw response, for inspection. Also surfaces in LangSmith
        # as the `ollama_disambiguate` child run (see _traced_generate above).
        _log.info(
            "llm_io",
            model=self._config.model,
            transport=self._transport.name,
            prompt_version=PROMPT_VERSION,
            prompt=prompt[:2000],
            raw_response=(raw or "")[:2000],
        )
        decision = self._parse_response(raw, candidates)
        _log.info(
            "llm_refine",
            transport=self._transport.name,
            prompt_version=PROMPT_VERSION,
            n_candidates=len(candidates),
            chosen_id=decision.chosen.pattern_id if decision else None,
        )
        return decision

    # ── resolution tie-breaker (resolve_v1) ──────────────────────────────

    def resolve_target(
        self,
        *,
        ref_text: str,
        context: str,
        candidates: list[tuple[str, str]],
    ) -> str | None:
        """Pick ONE target-document id among ambiguous candidates ("resolve_v1").

        ``candidates`` is a list of ``(id, description)`` pairs. Returns the chosen
        id, or ``None`` when the LLM fails, is unparseable, returns an unknown id,
        or sits below the confidence floor — so the caller keeps its deterministic
        (typically "unresolved") outcome. Strictly additive and never raises.
        """
        if not candidates:
            return None
        valid_ids = {cid for cid, _ in candidates}
        rendered = "\n".join(f"- {cid} | {desc}" for cid, desc in candidates)
        prompt = _RESOLVE_TEMPLATE.format(
            ref=(ref_text or "").replace('"""', "'''"),
            context=(context or "").replace('"""', "'''")[:600],
            candidates=rendered,
        )
        try:
            raw = self._transport.generate(prompt, temperature=0.0)
        except Exception as exc:  # noqa: BLE001 — a transport hiccup must not break resolution
            _log.warning(
                "resolve_transport_error", transport=self._transport.name, error=str(exc)
            )
            return None
        try:
            payload = json.loads(_extract_first_json(raw))
        except (json.JSONDecodeError, ValueError):
            _log.warning("resolve_response_unparseable", raw=(raw or "")[:200])
            return None
        chosen = str(payload.get("id", ""))
        if chosen not in valid_ids:
            _log.warning(
                "resolve_chose_unknown_id", chosen=chosen, offered=sorted(valid_ids)
            )
            return None
        try:
            confidence = float(payload.get("confidence", 0.0))
        except (TypeError, ValueError):
            confidence = 0.0
        if confidence < self._config.confidence_threshold:
            _log.info(
                "resolve_below_confidence",
                chosen=chosen,
                confidence=confidence,
                floor=self._config.confidence_threshold,
            )
            return None
        _log.info(
            "resolve_target",
            transport=self._transport.name,
            prompt_version=RESOLVE_PROMPT_VERSION,
            chosen=chosen,
            confidence=confidence,
            rationale=str(payload.get("rationale", ""))[:200],
        )
        return chosen

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


def list_ollama_models(base_url: str, *, timeout: float = 3.0) -> list[str] | None:
    """Return the model names Ollama currently has, or ``None`` if unreachable.

    A return of ``None`` means the daemon didn't answer (down / not installed);
    an empty list means it answered but has no models pulled.
    """
    try:
        import requests  # type: ignore[import-not-found]
    except ImportError:  # pragma: no cover — bare env
        return None
    try:
        resp = requests.get(f"{base_url.rstrip('/')}/api/tags", timeout=timeout)
        resp.raise_for_status()
        body = resp.json()
        return [str(m.get("name", "")) for m in body.get("models", []) if m.get("name")]
    except Exception:  # noqa: BLE001 — any failure means "treat as unreachable"
        return None


def _resolve_model(desired: str, available: list[str]) -> str | None:
    """Pick the best available Ollama model for ``desired``.

    Prefers an exact match, then a same-family match (compares the name before
    the ``:`` tag, e.g. ``llama3.1`` vs ``llama3.1:8b``), then the first model
    that's pulled. Returns ``None`` only when nothing is available.
    """
    if not available:
        return None
    if desired in available:
        return desired
    fam = desired.split(":", 1)[0].lower()
    for name in available:
        if name.split(":", 1)[0].lower() == fam:
            return name
    return available[0]


def _make_disambiguator(
    transport: LlmTransport, force_refine: bool | None, *, model: str | None = None
) -> LlmDisambiguator:
    """Wrap a transport, honoring an explicit ``force_refine`` and/or ``model``."""
    if force_refine is None and model is None:
        return LlmDisambiguator(transport)
    s = get_settings()
    cfg = DisambiguatorConfig(
        confidence_threshold=s.llm_confidence_threshold,
        model=model or s.ollama_model,
        force_refine=s.llm_force_refine if force_refine is None else force_refine,
    )
    return LlmDisambiguator(transport, cfg)


def _build_litellm_transport(settings) -> "LlmTransport | None":
    """Build the unified LiteLLM transport for the configured provider.

    Returns ``None`` (so the caller falls back to the native transports) when
    LiteLLM isn't installed or the selected provider can't be satisfied.
    """
    try:
        import litellm  # noqa: F401 — availability probe
    except Exception:  # pragma: no cover — litellm not installed
        _log.info("litellm_not_installed_using_native_transport")
        return None

    timeout = getattr(settings, "ollama_timeout", 90.0)

    if settings.llm_provider == "nvidia":
        if not settings.llm_api_key:
            _log.warning("nvidia_selected_but_no_api_key_using_native")
            return None
        _log.warning(
            "remote_llm_enabled_poc_only",
            provider="nvidia",
            model=settings.nvidia_model,
            note="prompt is sent OFF-MACHINE — POC/synthetic data only, not the GxP product path",
        )
        # Optional cloud→local fallback: retry on local Ollama if it's up.
        fallback = None
        avail = list_ollama_models(settings.ollama_host)
        if avail:
            local = _resolve_model(settings.ollama_model, avail)
            if local:
                fallback = {"model": f"ollama/{local}", "api_base": settings.ollama_host}
        transport = LiteLlmTransport(
            model=f"nvidia_nim/{settings.nvidia_model}",
            api_key=settings.llm_api_key,
            timeout=timeout,
            fallback=fallback,
            label=f"litellm:nvidia_nim/{settings.nvidia_model}",
        )
        _log.info(
            "litellm_transport_ready",
            provider="nvidia",
            model=settings.nvidia_model,
            fallback=(fallback or {}).get("model"),
        )
        return transport

    # Default provider: local Ollama. Resolve the actually-pulled model so a
    # missing exact tag still reaches the daemon (same robustness as native).
    avail = list_ollama_models(settings.ollama_host)
    if not avail:
        return None  # daemon down → native path handles the stub fallback
    local = _resolve_model(settings.ollama_model, avail)
    if not local:
        return None
    if local != settings.ollama_model:
        _log.warning(
            "ollama_model_substituted", desired=settings.ollama_model, chosen=local
        )
    transport = LiteLlmTransport(
        model=f"ollama/{local}",
        api_base=settings.ollama_host,
        timeout=timeout,
        label=f"litellm:ollama/{local}",
    )
    _log.info("litellm_transport_ready", provider="ollama", model=local)
    return transport


def build_disambiguator(
    *, prefer_stub: bool = False, force_refine: bool | None = None
) -> LlmDisambiguator:
    """Construct a disambiguator using the configured transport.

    The deterministic stub is selected when:
      * ``prefer_stub`` is True (tests, CI, offline dev)
      * the ``HYPERLINK_LLM_TRANSPORT`` env var is set to ``stub``
      * the Ollama daemon is unreachable, or has no models pulled

    Otherwise a real :class:`OllamaTransport` is returned. The configured
    ``ollama_model`` is resolved against the models Ollama *actually* has — so a
    machine that has ``llama2:latest`` pulled but not the configured
    ``llama3.1:8b`` still reaches the real LLM (with a logged substitution)
    instead of 404-ing on every call.

    ``force_refine`` (when not None) overrides the global ``llm_force_refine``
    setting for the returned disambiguator.
    """
    settings = get_settings()
    forced = (os.environ.get("HYPERLINK_LLM_TRANSPORT") or "").lower()
    if prefer_stub or forced == "stub":
        return _make_disambiguator(DeterministicStubTransport(), force_refine)

    # Preferred path: the unified LiteLLM transport (one client for local Ollama
    # AND cloud providers, with caching + optional fallback). Falls through to
    # the native transports below if LiteLLM isn't installed / can't be built.
    lite = _build_litellm_transport(settings)
    if lite is not None:
        model = (
            settings.nvidia_model
            if settings.llm_provider == "nvidia"
            else settings.ollama_model
        )
        return _make_disambiguator(lite, force_refine, model=model)

    # POC switch: route to a remote OpenAI-compatible provider (NVIDIA) when
    # selected. The local Ollama path below is unchanged and remains default.
    if settings.llm_provider == "nvidia":
        _log.warning(
            "remote_llm_enabled_poc_only",
            provider="nvidia",
            base_url=settings.nvidia_base_url,
            model=settings.nvidia_model,
            note="prompt is sent OFF-MACHINE — POC/synthetic data only, not the GxP product path",
        )
        try:
            nv: LlmTransport = NvidiaTransport(
                base_url=settings.nvidia_base_url,
                model=settings.nvidia_model,
                api_key=settings.llm_api_key,
                timeout=getattr(settings, "ollama_timeout", 90.0),
            )
            _log.info(
                "nvidia_transport_ready",
                model=settings.nvidia_model,
                base_url=settings.nvidia_base_url,
            )
            return _make_disambiguator(nv, force_refine, model=settings.nvidia_model)
        except RuntimeError as exc:
            _log.warning("nvidia_unavailable_falling_back_to_local", error=str(exc))
            # fall through to the local Ollama path

    available = list_ollama_models(settings.ollama_host)
    if available is None:
        _log.warning("ollama_unreachable_using_stub", host=settings.ollama_host)
        return _make_disambiguator(DeterministicStubTransport(), force_refine)
    chosen = _resolve_model(settings.ollama_model, available)
    if chosen is None:
        _log.warning(
            "ollama_no_models_using_stub",
            host=settings.ollama_host,
            hint="pull a model, e.g. `ollama pull llama3.1:8b`",
        )
        return _make_disambiguator(DeterministicStubTransport(), force_refine)
    if chosen != settings.ollama_model:
        _log.warning(
            "ollama_model_substituted",
            desired=settings.ollama_model,
            chosen=chosen,
            available=available,
        )
    try:
        transport: LlmTransport = OllamaTransport(
            base_url=settings.ollama_host,
            model=chosen,
            timeout=getattr(settings, "ollama_timeout", 90.0),
        )
        _log.info("ollama_transport_ready", model=chosen, host=settings.ollama_host)
        return _make_disambiguator(transport, force_refine)
    except RuntimeError as exc:
        _log.warning("ollama_unavailable_using_stub", error=str(exc))
        return _make_disambiguator(DeterministicStubTransport(), force_refine)
