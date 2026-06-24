"""Core engine library — pure domain logic with no framework dependencies.

Sub-packages:
  ingestion   — document loaders (docx, pdf, eCTD XML)
  parsing     — tokenisers / paragraph extractors
  detection   — regex, NER, and LLM reference detection
  injection   — hyperlink writers (docx, pdf, eCTD backbone)
  validation  — anomaly detection, HA rules, cross-module checks
  reporting   — CSV / XLSX / PDF export
  graph       — NetworkX-based eCTD backbone graph
"""
