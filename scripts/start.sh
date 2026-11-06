#!/usr/bin/env bash
set -euo pipefail
cd /workspace/test-nlu
export NLU_BACKEND=e5
export NLU_MODEL_PATH=/workspace/nlu-model
export NLU_MODE=template_direct
exec /workspace/nlu-venv/bin/python -m uvicorn nlu.api:app --host 127.0.0.1 --port 8000
