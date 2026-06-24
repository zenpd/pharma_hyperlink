# Orchestration and agents

The LangGraph state machine that runs the six layers, plus selectable per-run agents.

## How it works
- Node sequence load → parse → detect → resolve → inject → validate → report: `orchestration/nodes.py`, compiled in `orchestration/graph.py` with a sequential fallback in `orchestration/runner.py`.
- Run state + in-memory run store: `orchestration/state.py`; live SSE events: `orchestration/events.py`.
- Selectable agents (Fast / Balanced / Max-Accuracy + per-layer override): `orchestration/agents/registry.py`, `orchestration/agents/detect_agents.py`, `orchestration/agents/inject_agents.py`.
- Local-only LangSmith tracing: `orchestration/tracing.py`.

## Gotchas
- An absent `agent_profile` runs the legacy default node list verbatim (byte-identical behaviour).

## Related
[[Detection cascade]] · [[Workers and queue]] · [[Pipeline run and live status]] · [[_Home]]
