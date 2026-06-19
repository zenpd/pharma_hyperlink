"""Passthrough agents for layers with a single implementation today.

Ingest, Parse, Validate and Report each expose one "default" agent that simply
delegates to the existing ``node_*`` function. This keeps all six layers
uniformly selectable in the UI even where only one implementation exists, and
leaves room to register alternatives later without touching the runner.
"""

from __future__ import annotations

from hyperlink_engine.orchestration.agents.base import AgentSpec, Layer
from hyperlink_engine.orchestration.nodes import (
    node_load_dossier,
    node_parse_all,
    node_score_and_report,
    node_validate,
)

INGEST_DEFAULT = AgentSpec(
    id="ingest_default",
    layer=Layer.ingest,
    label="Hash + stage",
    description="SHA-256 each uploaded file and prepare the output directory.",
    run=node_load_dossier,
    is_default=True,
)

PARSE_DEFAULT = AgentSpec(
    id="parse_default",
    layer=Layer.parse,
    label="python-docx parse",
    description="Walk paragraphs and runs, extracting text + run metadata.",
    run=node_parse_all,
    is_default=True,
)

VALIDATE_DEFAULT = AgentSpec(
    id="validate_default",
    layer=Layer.validate,
    label="Existence + anomaly",
    description="Existence checks and anomaly detection over injected links.",
    run=node_validate,
    is_default=True,
)

REPORT_DEFAULT = AgentSpec(
    id="report_default",
    layer=Layer.report,
    label="Score + CSV",
    description="Submission-readiness score and validation_report.csv.",
    run=node_score_and_report,
    is_default=True,
)

PASSTHROUGH_AGENTS = [INGEST_DEFAULT, PARSE_DEFAULT, VALIDATE_DEFAULT, REPORT_DEFAULT]
