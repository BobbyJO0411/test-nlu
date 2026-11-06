#!/usr/bin/env bash
# Linux/macOS installer. NLU_HOME (default: parent of the repository) holds venv, cache and models.
set -euo pipefail
ROOT="$(cd "$(dirname "$0")/.." && pwd)"
cd "$ROOT"
export NLU_HOME="${NLU_HOME:-$(dirname "$ROOT")}"
MODEL_ID="${NLU_MODEL_ID:-nlpai-lab/KoE5}"
nlu_env_path="$NLU_HOME/nlu-venv"
export PIP_CACHE_DIR="$NLU_HOME/nlu-pip-cache"
export HF_HOME="$NLU_HOME/nlu-model-cache"
export HF_XET_CACHE="$NLU_HOME/nlu-model-cache/xet"
export HF_HUB_DISABLE_XET=1
export TOKENIZERS_PARALLELISM=false
model_dir="$NLU_HOME/nlu-models/${MODEL_ID//\//__}"
python3 -m venv "$nlu_env_path"
"$nlu_env_path/bin/python" -m pip install 'torch==2.5.1+cpu' --index-url https://download.pytorch.org/whl/cpu
"$nlu_env_path/bin/python" -m pip install -r requirements.lock.txt
"$nlu_env_path/bin/python" -m pip check
if [ ! -f "$model_dir/verified_model.json" ]; then
  "$nlu_env_path/bin/python" scripts/download_model.py --model-id "$MODEL_ID" --destination "$model_dir"
fi
"$nlu_env_path/bin/python" -c 'import sys; from nlu.engine import Recommender; m=Recommender(model_id=sys.argv[1],model_path=sys.argv[2]); print(m.recommend("의견제출통지서 대응 방법은 무엇인가요?")["selected_template_id"])' "$MODEL_ID" "$model_dir"
"$nlu_env_path/bin/python" -m unittest discover -s tests -v
