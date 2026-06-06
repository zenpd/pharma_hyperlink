# Complete end-to-end test script for Frontend-Backend Sync
# Run from: c:\Zensar\Hyperlink automation\hyperlink-engine

Write-Host ""
Write-Host "============================================================" -ForegroundColor Cyan
Write-Host "  HYPERLINK ENGINE - Full Frontend-Backend Sync Test Suite  " -ForegroundColor Cyan
Write-Host "============================================================" -ForegroundColor Cyan
Write-Host ""

$passed = 0
$failed = 0

$pytestCmd = "poetry run pytest"
if (Test-Path ".venv\Scripts\pytest.exe") {
    $pytestCmd = ".venv\Scripts\pytest"
}

function Pass($msg) {
    $script:passed++
    Write-Host "  [PASS] $msg" -ForegroundColor Green
}

function Fail($msg) {
    $script:failed++
    Write-Host "  [FAIL] $msg" -ForegroundColor Red
}

# -------------------------------------------------------------
# 1. Check services
# -------------------------------------------------------------
Write-Host "1) Checking services..." -ForegroundColor Yellow
Write-Host "   ---------------------------------------------" -ForegroundColor DarkGray

# Backend
try {
    $backend = Invoke-RestMethod -Uri "http://localhost:8000/health" -TimeoutSec 5 -ErrorAction Stop
    if ($backend -eq "ok") {
        Pass "Backend running on :8000 (health = ok)"
    } else {
        Fail "Backend responded but health != ok"
    }
} catch {
    Fail "Backend NOT reachable on :8000  -> Start with: poetry run uvicorn src.hyperlink_engine.dashboard.api:app --reload"
}

# Frontend
try {
    try {
        $null = Invoke-WebRequest -Uri "http://localhost:5173" -TimeoutSec 5 -UseBasicParsing -ErrorAction Stop
        Pass "Frontend running on :5173"
    } catch {
        $null = Invoke-WebRequest -Uri "http://localhost:5174" -TimeoutSec 5 -UseBasicParsing -ErrorAction Stop
        Pass "Frontend running on :5174"
    }
} catch {
    Fail "Frontend NOT reachable on :5173 or :5174  -> Start with: cd src/hyperlink_engine/dashboard/simple_frontend; npm run dev"
}

Write-Host ""

# -------------------------------------------------------------
# 2. Test API endpoints
# -------------------------------------------------------------
Write-Host "2) Testing API endpoints..." -ForegroundColor Yellow
Write-Host "   ---------------------------------------------" -ForegroundColor DarkGray

$endpoints = @(
    @{ Path = "/api/health";                         Expect = "ok text"   },
    @{ Path = "/api/dossiers";                       Expect = "dossiers"  },
    @{ Path = "/api/dossiers/demo/score";            Expect = "score"     },
    @{ Path = "/api/dossiers/demo/anomalies";        Expect = "anomalies" },
    @{ Path = "/api/dossiers/demo/links";            Expect = "links"     },
    @{ Path = "/api/dossiers/demo/export.csv";       Expect = "csv"       },
    @{ Path = "/api/dossiers/demo/export.xlsx";      Expect = "xlsx"      }
)

foreach ($ep in $endpoints) {
    try {
        $resp = Invoke-WebRequest -Uri "http://localhost:8000$($ep.Path)" -TimeoutSec 10 -UseBasicParsing -ErrorAction Stop
        if ($resp.StatusCode -eq 200) {
            Pass "$($ep.Path) -> 200"
        } else {
            Fail "$($ep.Path) -> $($resp.StatusCode)"
        }
    } catch {
        Fail "$($ep.Path) -> Error: $($_.Exception.Message)"
    }
}

Write-Host ""

# -------------------------------------------------------------
# 3. Validate response shapes
# -------------------------------------------------------------
Write-Host "3) Validating JSON response shapes..." -ForegroundColor Yellow
Write-Host "   ---------------------------------------------" -ForegroundColor DarkGray

try {
    $score = Invoke-RestMethod -Uri "http://localhost:8000/api/dossiers/demo/score" -TimeoutSec 10 -ErrorAction Stop
    if ($score.score -and $score.dossier_id -eq "demo") {
        Pass "/score has 'score' ($($score.score)) and 'dossier_id'"
    } else {
        Fail "/score response missing expected fields"
    }
} catch { Fail "/score shape check failed: $($_.Exception.Message)" }

try {
    $anomalies = Invoke-RestMethod -Uri "http://localhost:8000/api/dossiers/demo/anomalies" -TimeoutSec 10 -ErrorAction Stop
    if ($null -ne $anomalies.count -and $anomalies.anomalies) {
        Pass "/anomalies has 'count' ($($anomalies.count)) and 'anomalies' array"
    } else {
        Fail "/anomalies response missing expected fields"
    }
} catch { Fail "/anomalies shape check failed: $($_.Exception.Message)" }

try {
    $links = Invoke-RestMethod -Uri "http://localhost:8000/api/dossiers/demo/links" -TimeoutSec 10 -ErrorAction Stop
    if ($null -ne $links.count -and $links.links) {
        Pass "/links has 'count' ($($links.count)) and 'links' array"
    } else {
        Fail "/links response missing expected fields"
    }
} catch { Fail "/links shape check failed: $($_.Exception.Message)" }

Write-Host ""

# -------------------------------------------------------------
# 4. Run backend pytest suite
# -------------------------------------------------------------
Write-Host "4) Running backend pytest (test_frontend_backend_sync.py)..." -ForegroundColor Yellow
Write-Host "   ---------------------------------------------" -ForegroundColor DarkGray

& $pytestCmd tests/test_frontend_backend_sync.py -v --tb=short --no-header -p no:cacheprovider --override-ini="addopts=" 2>&1 | ForEach-Object { Write-Host "   $_" }

Write-Host ""

# -------------------------------------------------------------
# 5. Run full backend unit test suite
# -------------------------------------------------------------
Write-Host "5) Running full backend test suite..." -ForegroundColor Yellow
Write-Host "   ---------------------------------------------" -ForegroundColor DarkGray

& $pytestCmd tests/unit/test_dashboard_api.py -v --tb=short --no-header -p no:cacheprovider --override-ini="addopts=" 2>&1 | ForEach-Object { Write-Host "   $_" }

Write-Host ""

# -------------------------------------------------------------
# 6. Summary
# -------------------------------------------------------------
Write-Host "============================================================" -ForegroundColor Cyan
Write-Host "  RESULTS:  $passed passed  |  $failed failed" -ForegroundColor $(if ($failed -eq 0) { "Green" } else { "Red" })
Write-Host "============================================================" -ForegroundColor Cyan

if ($failed -eq 0) {
    Write-Host ""
    Write-Host "  All frontend-backend sync checks PASSED!" -ForegroundColor Green
    Write-Host "  Frontend and Backend are IN SYNC." -ForegroundColor Green
    Write-Host ""
} else {
    Write-Host ""
    Write-Host "  Some checks FAILED. See details above." -ForegroundColor Red
    Write-Host "  Fix the issues and re-run this script." -ForegroundColor Red
    Write-Host ""
}
