# Run Guide: 30-Document Extended Test Set (Phase 2 NER/Ollama Validation)

**Objective:** Execute the full hyperlink automation pipeline on 30 documents with traceable detection layer logging (regex, NER, Ollama).

**Duration:** ~10–15 minutes setup + 5–10 minutes processing

**Prerequisites:**
- ✅ Python 3.11+, Poetry installed
- ✅ Docker & docker-compose installed
- ✅ Node.js 18+ (for React dashboard)
- ✅ ~4GB RAM available (Ollama 8B model)

---

## Overview: 4-Terminal Architecture

| Terminal | Service | Port | Purpose |
|---|---|---|---|
| **Terminal 1** | Docker Services | 11434, 6379, 7687 | Ollama LLM, Redis, Neo4j |
| **Terminal 2** | FastAPI Backend | 8000 | Dashboard API endpoint |
| **Terminal 3** | React Frontend | 5174 | Web dashboard UI |
| **Terminal 4** | Batch Pipeline | — | Process 30 documents |

---

## Step-by-Step Execution

### ⏱️ Terminal 1: Start Docker Services (2 min)

```bash
cd "C:\Zensar\Hyperlink automation\hyperlink-engine"

# Start Ollama, Redis, Neo4j in background
docker compose up -d

# Verify all services are running
docker compose ps
```

**Expected output:**
```
NAME                COMMAND                  SERVICE   STATUS      PORTS
hyperlink-ollama    "ollama serve"           ollama    Up 2 min    0.0.0.0:11434->11434/tcp
hyperlink-redis     "redis-server..."        redis     Up 2 min    0.0.0.0:6379->6379/tcp
hyperlink-neo4j     "tini -- /startup.sh"    neo4j     Up 2 min    0.0.0.0:7687->7687/tcp, 7688/tcp
```

**Keep this terminal open.** Services run in background.

---

### ⏱️ Terminal 2: Generate 30 Documents + Start FastAPI Backend (3 min)

```bash
cd "C:\Zensar\Hyperlink automation\hyperlink-engine"

# Step 1: Generate 30 synthetic documents (20 standard + 5 ambiguous + 5 contextual)
echo "=== Generating 30 documents ==="
python -m scripts.bootstrap_synthetic_data --out data/synthetic --docs 30

# Expected output:
# ======================================================================
# Generated 30 documents under data\synthetic
#   - 20 standard (regex-friendly)
#   - 5 ambiguous (Ollama triggers)
#   - 5 contextual (NER triggers)
# Wrote eCTD backbone: data\synthetic\index.xml
# Wrote manifest:      data\synthetic\MANIFEST.txt
# Estimated references embedded: ~2000
# Expected Ollama calls: ~40 (8–15 per ambiguous doc)
# Expected NER calls: ~65 (13–20 per contextual doc)
# ======================================================================

echo ""
echo "=== Starting FastAPI backend on port 8000 ==="
echo "Waiting for Ollama to pull llama2 model (if needed)..."
echo "Ctrl+C to stop the server."
echo ""

# Step 2: Start the FastAPI backend (keep running in this terminal)
poetry run uvicorn src.hyperlink_engine.dashboard.api:app --reload --port 8000 --host 0.0.0.0
```

**Expected output (first run — Ollama model pull may take 2–3 min):**
```
INFO:     Uvicorn running on http://0.0.0.0:8000
INFO:     Application startup complete
```

**Important:** Keep this terminal open (FastAPI stays running).

---

### ⏱️ Terminal 3: Start React Dashboard Frontend (2 min)

Open a **new terminal** while keeping Terminal 2 running.

```bash
cd "C:\Zensar\Hyperlink automation\hyperlink-engine\src\hyperlink_engine\dashboard\simple_frontend"

# Step 1: Install frontend dependencies (first time only)
echo "=== Installing React dependencies ==="
npm install

# Step 2: Start the development server
echo ""
echo "=== Starting React dashboard on http://localhost:5174 ==="
echo "Ctrl+C to stop the server."
echo ""

npm run dev
```

**Expected output:**
```
  ➜  Local:   http://localhost:5174/
  ➜  press h + enter to show help
```

**Open http://localhost:5174 in your browser** to see the dashboard (empty until pipeline runs).

**Keep this terminal open.**

---

### ⏱️ Terminal 4: Run Batch Pipeline on 30 Documents (5–10 min)

Open a **new terminal** while keeping Terminals 1–3 running.

```bash
cd "C:\Zensar\Hyperlink automation\hyperlink-engine"

echo "=== Running batch pipeline on 30 documents ==="
echo "This will:"
echo "  • Detect references in all 30 docs"
echo "  • Inject hyperlinks"
echo "  • Validate links"
echo "  • Log detection layer usage"
echo ""
echo "Expected time: 5–10 minutes"
echo "Ctrl+C to cancel."
echo ""

# Run the batch pipeline
poetry run python -m hyperlink_engine.pipeline.batch_runner `
  --input data/synthetic `
  --output output/run30 `
  --mode threaded `
  --workers 4 `
  --verbose

# Optional: Monitor progress
echo ""
echo "=== Pipeline execution complete ==="
echo ""
echo "Output location: output/run30/"
echo ""
echo "Next steps:"
echo "  1. Check: ls -la output/run30/"
echo "  2. View: cat output/run30/dossier_links.csv"
echo "  3. Sync Dashboard: .venv/Scripts/python scripts/push_results_to_dashboard.py --run output/run30 --dossier demo"
echo "  4. LLM calls: Get-Content output/run30/llm_calls.jsonl | Measure-Object -Line"
echo "  5. NER calls: Get-Content output/run30/ner_calls.jsonl | Measure-Object -Line"
echo "  6. Dashboard: Open/Refresh http://localhost:5174"
```

**Expected output (real-time progress):**
```
INFO:     [1/30] Processing 2-5-clin-overview.docx...
INFO:     [2/30] Processing 2-7-1-summary-bio.docx...
...
INFO:     [25/30] Processing ambiguous-refs-01.docx...
  Detected: 80 refs, 0 regex-only, 12 NER, 8 Ollama, 0 mixed
INFO:     [30/30] Processing contextual-ner-05.docx...
  Detected: 105 refs, 78 regex, 27 NER, 0 Ollama, 0 mixed

=== Batch Summary ===
Total documents:        30
Total links processed:  2,047
Regex-only:            ~1,550 (75%)
NER-triggered:         ~350 (17%)
Ollama-triggered:      ~147 (7%)

Score: 99.2% (Grade A)
Broken links: 0
Time elapsed: 7m 42s
```

---

## Parallel Verification (While Pipeline Runs)

While Terminal 4 is processing, you can monitor progress in **Terminal 2** (FastAPI logs):

```
INFO:     detection_extract regex_hits=62 ner_hits=4 after_merge=66 chars=8432
INFO:     llm_refinement text="14" confidence_before=0.55 confidence_after=0.92
INFO:     llm_refinement text="CSR" confidence_before=0.48 confidence_after=0.88
...
```

---

## Post-Pipeline: Inspect Results

Once Terminal 4 completes, open **Terminal 5** (new) to inspect outputs:

```bash
cd "C:\Zensar\Hyperlink automation\hyperlink-engine"

# Count Ollama calls
echo "=== Ollama LLM Calls ==="
wc -l output/run30/llm_calls.jsonl
# Expected: 36–57 lines

# Count NER pattern matches
echo ""
echo "=== NER Pattern Matches ==="
wc -l output/run30/ner_calls.jsonl
# Expected: 67–99 lines

# Show first few Ollama decisions
echo ""
echo "=== Sample Ollama Calls (first 3) ==="
head -3 output/run30/llm_calls.jsonl | python -m json.tool

# Show first few NER matches
echo ""
echo "=== Sample NER Matches (first 3) ==="
head -3 output/run30/ner_calls.jsonl | python -m json.tool

# CSV statistics
echo ""
echo "=== CSV Report Stats ==="
python << 'EOF'
import csv

with open("output/run30/dossier_links.csv") as f:
    reader = csv.DictReader(f)
    rows = list(reader)

print(f"Total links: {len(rows)}")

by_layer = {}
for r in rows:
    layer = r.get("detected_by", "unknown")
    by_layer[layer] = by_layer.get(layer, 0) + 1

for layer, count in sorted(by_layer.items()):
    pct = (count / len(rows) * 100)
    print(f"  {layer:12} {count:5} ({pct:5.1f}%)")

# LLM usage
llm_used = sum(1 for r in rows if r.get("llm_called") == "yes")
print(f"\nLLM called: {llm_used} ({llm_used/len(rows)*100:.1f}%)")

# Broken links
broken = sum(1 for r in rows if r.get("status") == "broken")
print(f"Broken links: {broken} ({broken/len(rows)*100:.2f}%)")
EOF
```

**Expected output:**
```
=== Ollama LLM Calls ===
48 output/run30/llm_calls.jsonl

=== NER Pattern Matches ===
82 output/run30/ner_calls.jsonl

=== Sample Ollama Calls (first 3) ===
{
  "doc": "ambiguous-refs-01.docx",
  "text": "14",
  "confidence_before": 0.48,
  "confidence_after": 0.92,
  "rationale": "Context suggests Study ID format (bold numbers after 'study')"
}

=== CSV Report Stats ===
Total links: 2047
  llm              147 (  7.2%)
  merged             4 (  0.2%)
  ner              350 ( 17.1%)
  regex          1546 ( 75.5%)

LLM called: 147 (7.2%)
Broken links: 0 (0.00%)
```

---

## Dashboard Inspection (Live)

While pipeline runs or after completion:

1. **Open browser:** http://localhost:5174
2. **Navigate:** Click "🔬 Detection Layer Trace" button
3. **View:**
   - Per-document breakdown (30 rows)
   - Overall layer distribution (stats cards)
   - Color-coded legend: 🟦 Regex · 🟩 NER · 🟪 Ollama · 🟧 Mixed

**Expected breakdown:**
```
Document                  | Total | Regex | NER | Ollama | Mixed
--------------------------|-------|-------|-----|--------|-------
2-5-clin-overview.docx    |    62 |    62 |   0 |      0 |     0
ambiguous-refs-01.docx    |    80 |    68 |   4 |      8 |     0
ambiguous-refs-02.docx    |    90 |    75 |   7 |      8 |     0
contextual-ner-01.docx    |    95 |    78 |  17 |      0 |     0
contextual-ner-02.docx    |    88 |    72 |  16 |      0 |     0
...
```

---

## Troubleshooting

### ❌ Terminal 2: "Ollama connection refused"

**Solution:**
```bash
# Verify Ollama is running
docker compose ps | grep ollama

# If not running, restart
docker compose restart ollama

# Wait 30 seconds for Ollama to start
sleep 30

# Try pulling model manually
curl http://localhost:11434/api/pull -d '{"name": "llama2"}'
```

---

### ❌ Terminal 4: "No documents found in data/synthetic"

**Solution:**
```bash
# Verify documents were generated
ls -la data/synthetic/

# If empty, regenerate
python -m scripts.bootstrap_synthetic_data --out data/synthetic --docs 30
```

---

### ❌ Terminal 3: "Cannot GET /api/dossiers/demo/detection-trace"

**Solution:**
```bash
# FastAPI endpoint not running or not populated with data yet
# 1. Ensure Terminal 2 is running: poetry run uvicorn src.hyperlink_engine.dashboard.api:app --reload --port 8000
# 2. Run batch pipeline in Terminal 4 first
# 3. Refresh browser after pipeline completes
```

---

### ❌ "ModuleNotFoundError: No module named 'hyperlink_engine'"

**Solution:**
```bash
# Install package in editable mode
poetry install

# If poetry not found, ensure you're in the project root:
cd "C:\Zensar\Hyperlink automation\hyperlink-engine"
poetry install
```

---

## Cleanup (After Testing)

```bash
# Terminal 5 (new, after all done)
cd "C:\Zensar\Hyperlink automation\hyperlink-engine"

# Stop FastAPI (Ctrl+C in Terminal 2)
# Stop React frontend (Ctrl+C in Terminal 3)

# Stop Docker services
docker compose down

# Archive results
zip -r output/run30_results.zip output/run30/

# Clean up (optional)
rm -rf output/run30/synthetic/  # Remove intermediate files
```

---

## Success Criteria

After all steps, you should have:

- ✅ **Terminal 1:** Docker services running (Ollama, Redis, Neo4j)
- ✅ **Terminal 2:** FastAPI backend on http://localhost:8000
- ✅ **Terminal 3:** React dashboard on http://localhost:5174
- ✅ **Terminal 4:** Pipeline processed 30 documents
- ✅ **Output files:**
  - `output/run30/dossier_links.csv` (2,047 links with traceability)
  - `output/run30/llm_calls.jsonl` (~48 Ollama calls)
  - `output/run30/ner_calls.jsonl` (~82 NER matches)
  - 30 `_linked.docx` files in `output/run30/synthetic/`

---

## Expected Metrics

| Metric | Expected | Actual |
|---|---|---|
| **Total Links** | ~2,000 | — |
| **Regex-Only** | 75% | — |
| **NER-Triggered** | 17% | — |
| **Ollama-Triggered** | 7% | — |
| **Broken Links** | <1% | — |
| **Overall Score** | ≥95% | — |
| **Processing Time** | 5–10 min | — |

---

## Next Steps (Optional)

### Deep Dive: Inspect Specific Links

```bash
# Find all links detected by Ollama
cd "C:\Zensar\Hyperlink automation\hyperlink-engine"
grep 'detected_by.*llm' output/run30/dossier_links.csv | head -10

# Find all NER-triggered links
grep 'detected_by.*ner' output/run30/dossier_links.csv | head -10

# Inspect Ollama reasoning
python << 'EOF'
import json

with open("output/run30/llm_calls.jsonl") as f:
    for i, line in enumerate(f):
        call = json.loads(line)
        print(f"\n[Ollama Call #{i+1}]")
        print(f"  Text: {call['text']}")
        print(f"  Confidence: {call['confidence_before']:.2f} → {call['confidence_after']:.2f}")
        print(f"  Rationale: {call.get('rationale', 'N/A')}")
        if i >= 4:  # Show first 5
            break
EOF
```

---

## Reference Documentation

- **Detailed Plan:** `docs/hyperlink-automation-engine-architecture.md`
- **Extended Test Set Guide:** `docs/30-DOC-EXTENDED-TEST-SET.md`
- **Pattern Catalog:** `docs/pattern-catalog.md`
- **Bootstrap Script:** `scripts/bootstrap_synthetic_data.py`
- **API Reference:** `src/hyperlink_engine/dashboard/api.py`
- **React Frontend:** `src/hyperlink_engine/dashboard/simple_frontend/README.md`

---

## Support

If issues arise:
1. Check **Troubleshooting** section above
2. Review **Docker logs:** `docker compose logs -f ollama`
3. Check **FastAPI logs:** Terminal 2 output
4. Review **error files:** `output/run30/*.log`

---



Option A
$env:HYPERLINK_GRAPH_BACKEND = "networkx"
poetry run python -m hyperlink_engine.pipeline.batch_runner ...

Option B — Edit settings.py temporarily:

# Change line 47 from:
graph_backend: Literal["networkx", "neo4j"] = Field(default="neo4j")
# To:
graph_backend: Literal["networkx", "neo4j"] = Field(default="networkx")