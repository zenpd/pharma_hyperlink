"""Push batch pipeline results from output CSV into the FastAPI dashboard.

Usage:
    python scripts/push_results_to_dashboard.py --run output/run1
    python scripts/push_results_to_dashboard.py --run output/run1 --dossier demo
"""

from __future__ import annotations

import argparse
import csv
import json
import sys
import urllib.request
from pathlib import Path


API_BASE = "http://localhost:8000"


def _post(path: str, payload: dict) -> dict:
    url = f"{API_BASE}{path}"
    data = json.dumps(payload).encode()
    req = urllib.request.Request(
        url, data=data, headers={"Content-Type": "application/json"}, method="POST"
    )
    with urllib.request.urlopen(req, timeout=10) as resp:
        return json.loads(resp.read())


def _get(path: str) -> str:
    url = f"{API_BASE}{path}"
    with urllib.request.urlopen(url, timeout=10) as resp:
        return resp.read().decode("utf-8").strip()


def read_csv_results(run_dir: Path) -> list[dict]:
    csv_path = run_dir / "dossier_links.csv"
    if not csv_path.exists():
        print(f"ERROR: {csv_path} not found. Run batch_runner first.", file=sys.stderr)
        sys.exit(1)
    rows = []
    with open(csv_path, newline="", encoding="utf-8") as f:
        reader = csv.DictReader(f)
        for row in reader:
            rows.append(row)
    return rows


def compute_score(rows: list[dict]) -> dict:
    total = len(rows)
    broken = sum(1 for r in rows if r.get("status", "").lower() == "broken")
    ok = sum(1 for r in rows if r.get("status", "").lower() == "ok")
    unverified = sum(1 for r in rows if r.get("status", "").lower() == "unverified")

    broken_rate = broken / total if total else 0.0
    score = max(0.0, 100.0 - (broken * 5) - (unverified * 0.5))
    score = min(100.0, score)

    if score >= 90:
        grade = "A"
    elif score >= 80:
        grade = "B"
    elif score >= 70:
        grade = "C"
    else:
        grade = "F"

    return {
        "score": round(score, 1),
        "grade": grade,
        "broken_links": broken,
        "blocker_anomalies": broken,
        "total_links": total,
        "ok_links": ok,
        "unverified_links": unverified,
        "is_submission_ready": score >= 85 and broken == 0,
    }


def compute_anomalies(rows: list[dict]) -> list[dict]:
    anomalies = []
    for row in rows:
        status = row.get("status", "").lower()
        if status == "broken":
            anomalies.append({
                "kind": "broken_link",
                "severity": "blocker",
                "document": row.get("source_doc", "unknown"),
                "text": row.get("link_text", "unknown"),
                "suggested_fix": f"Check target: {row.get('target_doc', 'unknown')}",
                "confidence": float(row.get("confidence", 0.9)),
            })
        elif status == "unverified":
            anomalies.append({
                "kind": "unverified_link",
                "severity": "warning",
                "document": row.get("source_doc", "unknown"),
                "text": row.get("link_text", "unknown"),
                "suggested_fix": "Manually verify target exists in submission package",
                "confidence": float(row.get("confidence", 0.7)),
            })
    return anomalies


def compute_links(rows: list[dict]) -> list[dict]:
    links = []
    for row in rows:
        links.append({
            "source_doc": row.get("source_doc", ""),
            "link_text": row.get("link_text", ""),
            "link_location_descriptor": row.get("link_location") or row.get("link_location_descriptor", ""),
            "target_doc": row.get("target_doc", ""),
            "target_anchor": row.get("target_anchor", ""),
            "status": row.get("status", "ok").lower(),
            "confidence": float(row.get("confidence", 1.0)),
            "error_msg": row.get("error_msg") or None,
            "detected_by": row.get("detected_by") or None,
            "ner_pattern": row.get("ner_pattern") or None,
            "llm_called": row.get("llm_called", "no").lower() == "yes",
            "llm_confidence_before": float(row.get("llm_confidence_before")) if row.get("llm_confidence_before") else None,
            "llm_confidence_after": float(row.get("llm_confidence_after")) if row.get("llm_confidence_after") else None,
        })
    return links


def push_to_api(dossier_id: str, score: dict, anomalies: list, links: list) -> None:
    print(f"\nPushing results to API for dossier: {dossier_id}")
    print(f"  Score       : {score['score']}% (Grade {score['grade']})")
    print(f"  Total links : {score['total_links']}")
    print(f"  Broken      : {score['broken_links']}")
    print(f"  Unverified  : {score['unverified_links']}")
    print(f"  Anomalies   : {len(anomalies)}")
    print(f"  Ready?      : {'YES' if score['is_submission_ready'] else 'NO'}")

    # Push via Dossplorer push endpoint
    payload = {
        "score": score["score"],
        "sequence": "0001",
        "anomalies": anomalies,
    }
    try:
        result = _post(f"/api/dossiers/{dossier_id}/push", payload)
        print(f"\n  API response: {result}")
    except Exception as e:
        print(f"\n  Push endpoint not available ({e})")
        print("  Trying direct store update via health check...")

    # Also update score directly in store via a PATCH-style workaround
    # by calling the internal update endpoint (if available)
    try:
        _post(f"/api/dossiers/{dossier_id}/update-store", {
            "score": score,
            "anomalies": anomalies,
            "links": links,
        })
        print("  Store updated directly.")
    except Exception:
        pass

    print(f"\n  Open http://localhost:5174 to see updated dashboard.")


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Push batch pipeline results to the FastAPI dashboard"
    )
    parser.add_argument("--run", required=True, metavar="DIR",
                        help="Output run directory (e.g. output/run1)")
    parser.add_argument("--dossier", default="demo", metavar="ID",
                        help="Dossier ID to update in dashboard (default: demo)")
    args = parser.parse_args()

    run_dir = Path(args.run)
    if not run_dir.exists():
        print(f"ERROR: Run directory not found: {run_dir}", file=sys.stderr)
        sys.exit(1)

    # Check API is reachable
    try:
        health_status = _get("/health")
        if health_status != "ok":
            raise ValueError(f"Unexpected status: {health_status}")
    except Exception as e:
        print(f"ERROR: Cannot reach API at {API_BASE} — {e}", file=sys.stderr)
        print("Make sure FastAPI is running: poetry run uvicorn ...", file=sys.stderr)
        sys.exit(1)

    print(f"Reading results from: {run_dir}")
    rows = read_csv_results(run_dir)
    print(f"Found {len(rows)} link records")

    score = compute_score(rows)
    anomalies = compute_anomalies(rows)
    links = compute_links(rows)

    push_to_api(args.dossier, score, anomalies, links)

    # Print summary
    print("\n" + "=" * 50)
    print("DASHBOARD UPDATE SUMMARY")
    print("=" * 50)
    print(f"  Score         : {score['score']}%")
    print(f"  Grade         : {score['grade']}")
    print(f"  Total Links   : {score['total_links']}")
    print(f"  Broken Links  : {score['broken_links']}")
    print(f"  Warnings      : {score['unverified_links']}")
    print(f"  Ready to Sub  : {'YES' if score['is_submission_ready'] else 'NO'}")
    print("=" * 50)
    print("\nRefresh http://localhost:5174 to see results!")


if __name__ == "__main__":
    main()
