#!/usr/bin/env bash
set -euo pipefail
ROOT="$(cd "$(dirname "$0")/.." && pwd)"
cd "$ROOT"
export NLU_HOME="${NLU_HOME:-$(dirname "$ROOT")}"
export NLU_BACKEND=e5
export NLU_MODEL_ID="${NLU_MODEL_ID:-nlpai-lab/KoE5}"
export NLU_MODEL_PATH="${NLU_MODEL_PATH:-$NLU_HOME/nlu-models/${NLU_MODEL_ID//\//__}}"
export NLU_MODE=template_direct
exec "$NLU_HOME/nlu-venv/bin/python" -m uvicorn nlu.api:app --host 127.0.0.1 --port "${NLU_PORT:-8000}"
