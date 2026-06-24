"""Adapters — external service integrations.

Provides a unified import namespace for adapter modules that currently live in
their domain packages:

  * ``neo4j_adapter``      — from ``hyperlink_engine.core.graph.neo4j_adapter``
  * ``dossplorer_client``  — from ``hyperlink_engine.core.ingestion.dossplorer_client``
  * ``ollama_client``      — from ``hyperlink_engine.core.detection.llm_disambiguator``

Usage::

    from hyperlink_engine.adapters.neo4j_adapter import Neo4jAdapter
    from hyperlink_engine.adapters.dossplorer_client import DossplorerClient
"""

# Re-export adapters from their canonical locations
from hyperlink_engine.core.graph import neo4j_adapter  # noqa: F401
from hyperlink_engine.core.ingestion import dossplorer_client  # noqa: F401
