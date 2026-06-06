# 🚀 Quick Start: 30-Document Test Run (Copy-Paste Commands)

**Time to completion:** ~15 minutes  
**Full guide:** See `RUN-GUIDE-30-DOCS.md`

---

## Terminal 1: Docker Services
```bash
cd "C:\Zensar\Hyperlink automation\hyperlink-engine"
docker compose up -d
docker compose ps
```
✅ Keep running. Services start in background.

---

## Terminal 2: Backend API
```bash
cd "C:\Zensar\Hyperlink automation\hyperlink-engine"

python -m scripts.bootstrap_synthetic_data --out data/synthetic --docs 30

poetry run uvicorn src.hyperlink_engine.dashboard.api:app --reload --port 8000 --host 0.0.0.0
```
✅ Keep running. API on http://localhost:8000

---

## Terminal 3: React Dashboard
```bash
cd "C:\Zensar\Hyperlink automation\hyperlink-engine\src\hyperlink_engine\dashboard\simple_frontend"

npm install
npm run dev
```
✅ Keep running. Dashboard on http://localhost:5174

---

## Terminal 4: Run Pipeline
```bash
cd "C:\Zensar\Hyperlink automation\hyperlink-engine"

poetry run python -m hyperlink_engine.pipeline.batch_runner `
  --input data/synthetic `
  --output output/run30 `
  --mode threaded `
  --workers 4 `
  --verbose
```
*Note: Replace backticks (`` ` ``) with backslashes (`\`) if running in a Bash shell.*

✅ Runs once (~5-10 min). Check results when done.

---

## Terminal 5: Update Dashboard
```bash
cd "C:\Zensar\Hyperlink automation\hyperlink-engine"

.venv\Scripts\python scripts/push_results_to_dashboard.py --run output/run30 --dossier demo
```
✅ Run this to sync the pipeline results with the local dashboard server.

---

## After Pipeline: View Results
```bash
cd "C:\Zensar\Hyperlink automation\hyperlink-engine"

# Count Ollama & NER calls
echo "Ollama calls:" && wc -l output/run30/llm_calls.jsonl
echo "NER calls:" && wc -l output/run30/ner_calls.jsonl

# Quick stats
python << 'EOF'
import csv
with open("output/run30/dossier_links.csv") as f:
    rows = list(csv.DictReader(f))
by_layer = {}
for r in rows:
    layer = r.get("detected_by", "unknown")
    by_layer[layer] = by_layer.get(layer, 0) + 1
print(f"Total: {len(rows)}")
for layer, count in sorted(by_layer.items()):
    print(f"  {layer}: {count} ({count/len(rows)*100:.1f}%)")
EOF
```

---

## Dashboard
- **URL:** http://localhost:5174
- **Button:** "🔬 Detection Layer Trace"
- **Shows:** Per-doc breakdown (regex vs NER vs Ollama)

---

## Expected Output
```
✅ 30 documents processed
✅ ~2,047 links injected
✅ ~48 Ollama calls (ambiguous docs)
✅ ~82 NER calls (contextual docs)
✅ 0 broken links
✅ Score: 99.2% (Grade A)
```

---

## Cleanup
```bash
# When done
docker compose down

# Archive
zip -r output/run30_results.zip output/run30/
```

---

## Troubleshooting Quick Fixes

**Ollama error?**
```bash
docker compose restart ollama
sleep 30
```

**No documents?**
```bash
python -m scripts.bootstrap_synthetic_data --out data/synthetic --docs 30
```

**API not responding?**
```bash
# Check Terminal 2 is running with: poetry run uvicorn src.hyperlink_engine.dashboard.api:app...
```

---

**See `RUN-GUIDE-30-DOCS.md` for detailed troubleshooting & explanations.**
