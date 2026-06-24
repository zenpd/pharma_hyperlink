# Reporting and scoring

Layer 6 — exports plus the submission-readiness score and grade.

## How it works
- CSV / XLSX exporters: `core/reporting/csv_exporter.py`, `core/reporting/xlsx_exporter.py`.
- Readiness score + grade from real bookmark/file/URL checks (not hard-coded): `core/reporting/readiness_score.py`.
- Gate-review PDF for sign-off packets: `core/reporting/gate_review_pdf.py`.
- `node_score_and_report` + the runner's readiness floor route a run to push vs. flag: `orchestration/runner.py`.

## Gotchas
- The score gates routing: at/above the readiness floor a run pushes to Dossplorer, otherwise it goes to the review queue.

## Related
[[Validation layer]] · [[Reports and review screens]] · [[eCTD backbone and graph]] · [[_Home]]
