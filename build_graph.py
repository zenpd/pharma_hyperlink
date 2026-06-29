#!/usr/bin/env python3
"""
build_graph.py — code-only graphify knowledge graph (no LLM, no API key).
 
Produces:  graphify-out/graph.json  +  graphify-out/GRAPH_REPORT.md
For the interactive view, run `graphify export html` afterwards.
 
Setup once:
    pip install graphifyy
 
Run (from the repo root):
    python build_graph.py            # graphs the current folder
    python build_graph.py <path>     # or a specific folder
"""
from __future__ import annotations
 
import sys
from pathlib import Path
 
from graphify.detect import detect
from graphify.extract import collect_files, extract
from graphify.build import build_from_json
from graphify.cluster import cluster, score_all
from graphify.analyze import god_nodes, surprising_connections, suggest_questions
from graphify.report import generate
from graphify.export import to_json
 
 
def main() -> None:
    root = Path(sys.argv[1] if len(sys.argv) > 1 else ".").resolve()
    print(f"scanning {root} ...")
    det = detect(root)
 
    code: list[Path] = []
    for f in det.get("files", {}).get("code", []):
        p = Path(f)
        code += collect_files(p) if p.is_dir() else [p]
    if not code:
        print("no code files found - nothing to graph.")
        return
 
    print(f"AST-extracting {len(code)} code files (deterministic, no LLM) ...")
    extraction = extract(code, cache_root=root)
 
    graph = build_from_json(extraction, root=str(root), directed=False)
    if graph.number_of_nodes() == 0:
        print("graph is empty - extraction produced no nodes.")
        return
 
    communities = cluster(graph)
    cohesion = score_all(graph, communities)
    gods = god_nodes(graph)
    surprises = surprising_connections(graph, communities)
    labels = {cid: f"Community {cid}" for cid in communities}
    questions = suggest_questions(graph, communities, labels)
 
    out = Path("graphify-out")
    out.mkdir(exist_ok=True)
    to_json(graph, communities, str(out / "graph.json"))
 
    report = generate(
        graph, communities, cohesion, labels, gods, surprises,
        det, {"input": 0, "output": 0}, str(root),
        suggested_questions=questions,
    )
    (out / "GRAPH_REPORT.md").write_text(report, encoding="utf-8")
 
    print(
        f"graph.json + GRAPH_REPORT.md written: "
        f"{graph.number_of_nodes()} nodes, {graph.number_of_edges()} edges, "
        f"{len(communities)} communities"
    )
    print("next: run `graphify export html`  ->  graphify-out/graph.html")
 
 
if __name__ == "__main__":
    main()