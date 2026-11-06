#!/usr/bin/env bash
set -euo pipefail
cd /workspace/test-nlu
nlu_env_path=/workspace/nlu-venv
export PIP_CACHE_DIR=/workspace/nlu-pip-cache
export HF_HOME=/workspace/nlu-model-cache
export HF_XET_CACHE=/workspace/nlu-model-cache/xet
export TOKENIZERS_PARALLELISM=false
python3 -m venv "$nlu_env_path"
"$nlu_env_path/bin/python" -m pip install 'torch==2.5.1+cpu' --index-url https://download.pytorch.org/whl/cpu
"$nlu_env_path/bin/python" -m pip install -r requirements.lock.txt
"$nlu_env_path/bin/python" -m pip check
if [ -f /workspace/nlu-model/verified_model.json ]; then
  "$nlu_env_path/bin/python" -c 'from nlu.engine import Recommender; m=Recommender(model_path="/workspace/nlu-model"); print(m.recommend("의견제출통지서 대응 방법은 무엇인가요?")["selected_template_id"])'
else
  "$nlu_env_path/bin/python" scripts/download_model.py --revision 614241f622f53c4eeff9890bdc4f31cfecc418b3 --destination /workspace/nlu-model
fi
"$nlu_env_path/bin/python" -m unittest discover -s tests -v
