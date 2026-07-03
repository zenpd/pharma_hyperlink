# One-shot OCR setup — no admin. Run from backend\ with the venv activated.
$ErrorActionPreference = "Stop"
 
# 1) Scoop (user-level installer)
if (-not (Get-Command scoop -ErrorAction SilentlyContinue)) {
    Set-ExecutionPolicy -Scope CurrentUser RemoteSigned -Force
    Invoke-RestMethod get.scoop.sh | Invoke-Expression
}
 
# 2) System programs: OCR engine + language data + PDF renderer
scoop install tesseract tesseract-languages ghostscript
 
# 3) THE FIX THAT BIT YOU: put eng where Tesseract looks by default
New-Item -ItemType Directory -Force -Path "$env:USERPROFILE\scoop\apps\tesseract\current\tessdata" | Out-Null
Copy-Item "$env:USERPROFILE\scoop\apps\tesseract-languages\current\eng.traineddata" `
          "$env:USERPROFILE\scoop\apps\tesseract\current\tessdata\eng.traineddata" -Force
 
# 4) Put scoop's shims on the PERMANENT user PATH (so every new terminal has tesseract)
$shims = "$env:USERPROFILE\scoop\shims"
$u = [Environment]::GetEnvironmentVariable("Path","User")
if ($u -notlike "*$shims*") { [Environment]::SetEnvironmentVariable("Path","$u;$shims","User") }
 
# 5) Python wrappers into the venv
pip install -e ".[ocr]"
 
# 6) Verify
$env:Path += ";$shims"
tesseract --version
tesseract --list-langs      # must show eng
gswin64c --version