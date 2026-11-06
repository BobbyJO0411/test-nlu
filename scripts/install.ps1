# Windows installer: Python 3.12 venv, pinned CPU dependencies, verified model copy, tests.
# Usage (PowerShell, repository root):  powershell -ExecutionPolicy Bypass -File scripts\install.ps1 [-ModelId nlpai-lab/KoE5]
param(
    [string]$ModelId = "nlpai-lab/KoE5",
    [string]$NluHome = (Resolve-Path "$PSScriptRoot\..\..").Path
)
$ErrorActionPreference = "Stop"
$Root = (Resolve-Path "$PSScriptRoot\..").Path
Set-Location $Root
$env:NLU_HOME = $NluHome
$env:PIP_CACHE_DIR = Join-Path $NluHome "nlu-pip-cache"
$env:HF_HOME = Join-Path $NluHome "nlu-model-cache"
$env:HF_HUB_DISABLE_XET = "1"
$env:TOKENIZERS_PARALLELISM = "false"
$Venv = Join-Path $NluHome "nlu-venv"
$Python = Join-Path $Venv "Scripts\python.exe"
if (-not (Test-Path $Python)) { py -3.12 -m venv $Venv; if ($LASTEXITCODE -ne 0) { throw "Python 3.12 (py -3.12) is required" } }
& $Python -m pip install --upgrade pip
& $Python -m pip install "torch==2.5.1+cpu" --index-url https://download.pytorch.org/whl/cpu
& $Python -m pip install -r requirements.lock.txt
& $Python -m pip check; if ($LASTEXITCODE -ne 0) { throw "pip check failed" }
$ModelDir = Join-Path $NluHome ("nlu-models\" + ($ModelId -replace "/", "__"))
if (-not (Test-Path (Join-Path $ModelDir "verified_model.json"))) {
    & $Python scripts\download_model.py --model-id $ModelId --destination $ModelDir
    if ($LASTEXITCODE -ne 0) { throw "Model download or verification failed" }
}
& $Python -c "from nlu.engine import Recommender; import sys; m=Recommender(model_id=sys.argv[1], model_path=sys.argv[2]); print(m.recommend('의견제출통지서 대응 방법은 무엇인가요?')['selected_template_id'])" $ModelId $ModelDir
& $Python -m unittest discover -s tests -v
if ($LASTEXITCODE -ne 0) { throw "Tests failed" }
