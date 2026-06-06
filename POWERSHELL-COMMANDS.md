# PowerShell Commands: 30-Document Test Run

## Single-Line Commands (Copy-Paste)

### Terminal 1: Docker Services
```powershell
cd "C:\Zensar\Hyperlink automation\hyperlink-engine"; docker compose up -d; docker compose ps
```

---

### Terminal 2: Bootstrap + FastAPI Backend
```powershell
cd "C:\Zensar\Hyperlink automation\hyperlink-engine"; python -m scripts.bootstrap_synthetic_data --out data/synthetic --docs 30; poetry run uvicorn src.hyperlink_engine.dashboard.api:app --reload --port 8000 --host 0.0.0.0
```

---

### Terminal 3: React Frontend
```powershell
cd "C:\Zensar\Hyperlink automation\hyperlink-engine\src\hyperlink_engine\dashboard\simple_frontend"; npm install; npm run dev
```

---

### Terminal 4: Batch Pipeline
```powershell
cd "C:\Zensar\Hyperlink automation\hyperlink-engine"; poetry run python -m hyperlink_engine.pipeline.batch_runner --input data/synthetic --output output/run30 --mode threaded --workers 4 --verbose
```

---

### Terminal 5: Update Dashboard
```powershell
cd "C:\Zensar\Hyperlink automation\hyperlink-engine"; .venv\Scripts\python scripts/push_results_to_dashboard.py --run output/run30 --dossier demo
```

---

## Multi-Line Format (Better Readability)

### Terminal 2: Bootstrap + FastAPI
```powershell
cd "C:\Zensar\Hyperlink automation\hyperlink-engine"
Write-Host "=== Generating 30 documents ===" -ForegroundColor Cyan
python -m scripts.bootstrap_synthetic_data --out data/synthetic --docs 30

Write-Host ""
Write-Host "=== Starting FastAPI backend ===" -ForegroundColor Cyan
poetry run uvicorn src.hyperlink_engine.dashboard.api:app --reload --port 8000 --host 0.0.0.0
```

---

### Terminal 4: Batch Pipeline (MAIN COMMAND)
```powershell
cd "C:\Zensar\Hyperlink automation\hyperlink-engine"

Write-Host "=== Running batch pipeline on 30 documents ===" -ForegroundColor Green
Write-Host "Workers: 4"
Write-Host "Expected time: 5-10 minutes"
Write-Host ""

poetry run python -m hyperlink_engine.pipeline.batch_runner `
  --input data/synthetic `
  --output output/run30 `
  --mode threaded `
  --workers 4 `
  --verbose

Write-Host ""
Write-Host "=== Pipeline Complete ===" -ForegroundColor Green
```

---

### Terminal 5: Update Dashboard
```powershell
cd "C:\Zensar\Hyperlink automation\hyperlink-engine"
Write-Host "=== Pushing results to dashboard ===" -ForegroundColor Cyan
.venv\Scripts\python scripts/push_results_to_dashboard.py --run output/run30 --dossier demo
```

---

## Batch Commands (Run All Sequentially)

### Auto-Run All 4 Terminals (Advanced)
```powershell
# Terminal 1 - Docker (background job)
$dockerJob = Start-Job -ScriptBlock {
    cd "C:\Zensar\Hyperlink automation\hyperlink-engine"
    docker compose up
}

# Wait for Docker to start
Start-Sleep -Seconds 5

# Terminal 2 - Backend (background job)
$backendJob = Start-Job -ScriptBlock {
    cd "C:\Zensar\Hyperlink automation\hyperlink-engine"
    python -m scripts.bootstrap_synthetic_data --out data/synthetic --docs 30
    poetry run uvicorn src.hyperlink_engine.dashboard.api:app --reload --port 8000 --host 0.0.0.0
}

# Terminal 3 - Frontend (background job)
$frontendJob = Start-Job -ScriptBlock {
    cd "C:\Zensar\Hyperlink automation\hyperlink-engine\src\hyperlink_engine\dashboard\simple_frontend"
    npm install
    npm run dev
}

# Wait for services to start
Start-Sleep -Seconds 10

# Terminal 4 - Pipeline (foreground - monitor output)
cd "C:\Zensar\Hyperlink automation\hyperlink-engine"
Write-Host "Services starting... check background jobs"
Write-Host ""
Write-Host "Running pipeline..." -ForegroundColor Cyan

poetry run python -m hyperlink_engine.pipeline.batch_runner `
  --input data/synthetic `
  --output output/run30 `
  --mode threaded `
  --workers 4 `
  --verbose

Write-Host ""
Write-Host "Pipeline complete. Stopping services..." -ForegroundColor Green
Stop-Job -Job $dockerJob, $backendJob, $frontendJob
Remove-Job -Job $dockerJob, $backendJob, $frontendJob
```

---

## Post-Pipeline: View Results

### Count LLM & NER Calls
```powershell
cd "C:\Zensar\Hyperlink automation\hyperlink-engine"

Write-Host "=== Ollama LLM Calls ===" -ForegroundColor Cyan
Get-Content output/run30/llm_calls.jsonl | Measure-Object -Line

Write-Host ""
Write-Host "=== NER Pattern Matches ===" -ForegroundColor Cyan
Get-Content output/run30/ner_calls.jsonl | Measure-Object -Line
```

### Quick Statistics
```powershell
cd "C:\Zensar\Hyperlink automation\hyperlink-engine"

$csvPath = "output/run30/dossier_links.csv"
$rows = @(Get-Content $csvPath | Select-Object -Skip 1)

Write-Host "=== CSV Statistics ===" -ForegroundColor Green
Write-Host "Total links: $($rows.Count)"

# Group by detection layer
$csv = Import-Csv $csvPath
$byLayer = $csv | Group-Object -Property detected_by

foreach ($group in $byLayer) {
    $pct = ($group.Count / $csv.Count * 100)
    Write-Host "  $($group.Name): $($group.Count) ($($pct.ToString('F1'))%)"
}

# Check for broken links
$broken = @($csv | Where-Object { $_.status -eq 'broken' }).Count
Write-Host ""
Write-Host "Broken links: $broken ($($broken/$csv.Count*100)%)"
```

---

## Simplified Terminal Commands (Copy These)

### Terminal 1 (Start Docker)
```powershell
cd "C:\Zensar\Hyperlink automation\hyperlink-engine"; docker compose up -d
```

### Terminal 2 (Backend + Data Gen)
```powershell
cd "C:\Zensar\Hyperlink automation\hyperlink-engine"; python -m scripts.bootstrap_synthetic_data --out data/synthetic --docs 30; poetry run uvicorn src.hyperlink_engine.dashboard.api:app --reload --port 8000
```

### Terminal 3 (Frontend)
```powershell
cd "C:\Zensar\Hyperlink automation\hyperlink-engine\src\hyperlink_engine\dashboard\simple_frontend"; npm install; npm run dev
```

### Terminal 4 (Pipeline) ⭐ **MAIN COMMAND YOU ASKED FOR**
```powershell
cd "C:\Zensar\Hyperlink automation\hyperlink-engine"; poetry run python -m hyperlink_engine.pipeline.batch_runner --input data/synthetic --output output/run30 --workers 4
```

### Terminal 5 (Update Dashboard)
```powershell
cd "C:\Zensar\Hyperlink automation\hyperlink-engine"; .venv\Scripts\python scripts/push_results_to_dashboard.py --run output/run30 --dossier demo
```

---

## Multi-Line Version (Terminal 4 - Recommended)

```powershell
cd "C:\Zensar\Hyperlink automation\hyperlink-engine"

poetry run python -m hyperlink_engine.pipeline.batch_runner `
  --input data/synthetic `
  --output output/run30 `
  --mode threaded `
  --workers 4 `
  --verbose
```

**Replace `\` with `` ` `` (backtick) for line continuations in PowerShell!**

---

## Key Differences: Bash vs PowerShell

| Feature | Bash | PowerShell |
|---|---|---|
| **Line continuation** | `\` | `` ` `` (backtick) |
| **Comment** | `#` | `#` |
| **String quotes** | `"` or `'` | `"` or `'` |
| **Command separator** | `;` | `;` |
| **Variable** | `$var` | `$var` |
| **Echo** | `echo` | `Write-Host` |
| **Count lines** | `wc -l file` | `Get-Content file \| Measure-Object -Line` |

---

## Environment Setup (If Not Done)

```powershell
# Check Python
python --version

# Check Poetry
poetry --version

# Check Node/NPM
npm --version

# Install project dependencies (if needed)
cd "C:\Zensar\Hyperlink automation\hyperlink-engine"
poetry install
```

---

## Troubleshooting in PowerShell

### Backtick Not Working?
Use single-line instead:
```powershell
poetry run python -m hyperlink_engine.pipeline.batch_runner --input data/synthetic --output output/run30 --workers 4
```

### Command Not Found?
```powershell
# Add to PATH if needed
$env:PATH += ";C:\Python311\Scripts"

# Or use full poetry path
& "C:\Users\<YourUsername>\AppData\Local\pypoetry\bin\poetry.exe" run python -m hyperlink_engine.pipeline.batch_runner --input data/synthetic --output output/run30 --workers 4
```

### Execution Policy Error?
```powershell
Set-ExecutionPolicy -ExecutionPolicy RemoteSigned -Scope CurrentUser
```

---

## One-Liner: Quick Test
```powershell
cd "C:\Zensar\Hyperlink automation\hyperlink-engine"; python -m scripts.bootstrap_synthetic_data --out data/synthetic --docs 30
```

---

## Save as Batch File (.ps1)

Create `run-pipeline.ps1`:
```powershell
# run-pipeline.ps1
cd "C:\Zensar\Hyperlink automation\hyperlink-engine"

Write-Host "Starting batch pipeline..." -ForegroundColor Green

poetry run python -m hyperlink_engine.pipeline.batch_runner `
  --input data/synthetic `
  --output output/run30 `
  --mode threaded `
  --workers 4 `
  --verbose

Write-Host "Pipeline complete!" -ForegroundColor Green
Read-Host "Press Enter to exit"
```

Run it:
```powershell
.\run-pipeline.ps1
```

---

**For Terminal 4, use:**
```powershell
poetry run python -m hyperlink_engine.pipeline.batch_runner --input data/synthetic --output output/run30 --workers 4
```

Or multi-line:
```powershell
poetry run python -m hyperlink_engine.pipeline.batch_runner `
  --input data/synthetic `
  --output output/run30 `
  --workers 4
```
