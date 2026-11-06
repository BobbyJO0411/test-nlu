# Windows: start the recommendation API on http://127.0.0.1:8000 with a verified local model copy.
param(
    [string]$ModelId = "nlpai-lab/KoE5",
    [string]$NluHome = (Resolve-Path "$PSScriptRoot\..\..").Path,
    [int]$Port = 8000
)
$ErrorActionPreference = "Stop"
Set-Location (Resolve-Path "$PSScriptRoot\..").Path
$env:NLU_HOME = $NluHome
$env:NLU_BACKEND = "e5"
$env:NLU_MODEL_ID = $ModelId
$env:NLU_MODEL_PATH = Join-Path $NluHome ("nlu-models\" + ($ModelId -replace "/", "__"))
$env:NLU_MODE = "template_direct"
& (Join-Path $NluHome "nlu-venv\Scripts\python.exe") -m uvicorn nlu.api:app --host 127.0.0.1 --port $Port
