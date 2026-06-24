# LangSmith Tracing (Developer Debugging — Dev Only)

> **Compliance note:** This is a **developer-only** aid. The hosted LangSmith
> cloud (`api.smith.langchain.com`) is **NOT permitted** for this project — it
> would send dossier metadata off-machine and violate the on-prem / 21 CFR
> Part 11 / GxP constraint. Tracing here is wired to a **self-hosted, local**
> LangSmith only, and the code refuses any non-local endpoint while
> `enforce_local_llm_only` is on (the default).

## What you get

When enabled, every LangGraph pipeline run is reported to your local LangSmith
instance: the node graph, per-node timings, inputs/outputs, and the
conditional push/flag branch — a visual trace of the state machine.

## 1. Run a self-hosted LangSmith locally

LangSmith self-hosted is a licensed LangChain product. Follow the official
docs (https://docs.smith.langchain.com/self_hosting) — typically a Docker
Compose stack that exposes the API on `http://localhost:1984`. You will need a
self-hosted license key from LangChain.

Once running, you should be able to reach the API at `http://localhost:1984`.

## 2. Enable tracing in this project (env vars)

```powershell
$env:HYPERLINK_LANGSMITH_TRACING  = "true"
$env:HYPERLINK_LANGSMITH_ENDPOINT = "http://localhost:1984"   # must be local
$env:HYPERLINK_LANGSMITH_PROJECT  = "hyperlink-engine"
$env:HYPERLINK_LANGSMITH_API_KEY  = "<your-self-hosted-key>"   # if required

.venv\Scripts\uvicorn hyperlink_engine.api.app:app --port 8000
```

On the next pipeline run the backend log shows:

```
{"event": "langsmith_tracing_enabled", "endpoint": "http://localhost:1984", ...}
```

Then open the LangSmith UI and find the runs under the `hyperlink-engine`
project.

## 3. Safety behavior

- Default is **OFF** (`langsmith_tracing=false`) — no tracing, no env vars set.
- If you point `HYPERLINK_LANGSMITH_ENDPOINT` at a non-local host while
  `enforce_local_llm_only` is on, tracing is **refused** and logged:
  `langsmith_tracing_refused_nonlocal`. Nothing is sent.
- Tracing is configured in `orchestration/tracing.py` and invoked from
  `build_pipeline_graph()`. It never affects pipeline results.

## Why not the existing audit trail?

The append-only `audit.jsonl` already records every node transition locally
and is the GxP source of truth. LangSmith is only a richer **visual** debugger
for development — use it when you need to *see* the graph, not for compliance.
