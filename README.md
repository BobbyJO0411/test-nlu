# 상표 NLU 응답 추천·시험 준비 패키지

시험 항목 「NLU 기반 반자동 응답 추천 기능 적합도」를 준비하는 저장소입니다. 고객 질의를 한국어 E5 문장 임베딩으로 변환해 사전 등록된 응답 템플릿 30개 중 상위 3개를 뽑고, 1순위 템플릿 원문을 그대로 추천합니다. 평가자 파일 생성, 협의·다수결 집계, 적합도·합의율·ISO FCr-1-G 산출까지 포함합니다.

**현재 상태:** 실제 실무자·변리사의 평가와 승인, 시험기관 확인은 아직 없습니다. 질의 100건은 합성 초안이고 개발 중 이미 공개됐으므로 최종 성적에는 새로 수집·승인한 질의를 씁니다. 가상 A·B 결과는 규칙 기반 모의 예제이며 제출할 수 없습니다. 자세한 내용은 [docs/현재검증결과.md](docs/현재검증결과.md)에 있습니다.

## 구성

| 위치 | 내용 |
|---|---|
| data/questions_100.json, .csv | 25유형 × 4건 합성 시험 질의(개발 검증용) |
| data/templates.json | 템플릿 30개: 대표 질문, 응답 원문, 근거, 승인 상태 |
| data/template_queries.json | 템플릿별 추가 대표 질문 4개(총 120개), 템플릿 DB의 일부로 승인 대상 |
| data/dev_queries.json | 튜닝 전용 개발셋 90건. 시험 질의와 분리 |
| data/model_profiles.json | 모델별 고정 커밋·접두어·라이선스. 기본 nlpai-lab/KoE5 |
| data/retrieval_config.json | 개발셋에서 정한 모델별 검색 방식과 가중치 |
| data/verified_models/ | 모델 파일 해시 검증 기록 |
| nlu/engine.py, api.py | 임베딩 검색 → top3 → 템플릿 원문 추천, REST API |
| nlu/cli.py | run(100건 실행), tune(개발셋 튜닝), score(집계) |
| nlu/metrics.py | 적합도, 합의율, 협의/다수결, κ, Wilson 구간, ISO X=1−A/B |
| scripts/ | 설치·실행, 모델 다운로드, 평가 파일 생성, 평가 수집, 제3평가자 파일, 실질의 익명화, 승인 해시 |
| docs/ | 시험방법서, 평가 기준, 성적서 양식, 체크리스트, 시험기관 확인요청서, 실질의 수집 절차 |
| artifacts/review_package | 최종 개발 실행 기준 평가자 파일·총괄 시트·DOCX |
| artifacts/evidence | 튜닝 결과, 100건 비교, 이전 로그 |

## 설치와 실행

venv, 모델 캐시, 검증된 모델 복사본은 저장소 상위 폴더(NLU_HOME, 기본값)에 만들어집니다.

Windows (PowerShell, Python 3.12 필요):
```powershell
powershell -ExecutionPolicy Bypass -File scripts\install.ps1
powershell -ExecutionPolicy Bypass -File scripts\start.ps1
```

Linux:
```bash
bash scripts/install.sh
bash scripts/start.sh
```

API는 http://127.0.0.1:8000 에서 /health, POST /recommend, 웹 화면(/)을 제공합니다.
```bash
curl --fail -H 'Content-Type: application/json' -d '{"query":"상표 의견제출통지서를 받았는데 최종 거절인가요?"}' http://127.0.0.1:8000/recommend
```

Windows에서는 Git Bash의 curl이 한글 인자를 UTF-8로 보내지 않을 수 있으므로 PowerShell을 씁니다.
```powershell
$body = [Text.Encoding]::UTF8.GetBytes('{"query":"상표 의견제출통지서를 받았는데 최종 거절인가요?"}')
Invoke-RestMethod -Method Post -Uri http://127.0.0.1:8000/recommend -ContentType 'application/json; charset=utf-8' -Body $body
```

아래 python은 NLU_HOME의 venv Python입니다(Windows: `..\nlu-venv\Scripts\python.exe`, Linux: `../nlu-venv/bin/python`).

## 모델

기본 모델 nlpai-lab/KoE5는 intfloat/multilingual-e5-large를 한국어 데이터로 미세조정한 공개 모델(MIT, 1024차원)입니다. 시험계획의 ‘E5-Ko’ 요건 후보이며, 인정 여부는 시험기관이 확인해야 합니다. 다른 모델을 써야 하면 data/model_profiles.json에 고정 커밋을 추가하고 `--model-id`로 지정한 뒤 튜닝과 실행을 다시 합니다. 다운로드한 모든 파일은 Hugging Face 공개 해시와 대조하며, 오류가 나면 baseline으로 대체하지 않고 중단합니다.

```bash
python scripts/download_model.py --model-id nlpai-lab/KoE5
```

## 검색 방식과 튜닝

템플릿 점수 = α × (질의와 템플릿 대표 질문들 간 최대 코사인) + (1−α) × (질의와 템플릿 본문 코사인) + β × (문자 n-gram 유사도). α, β는 개발셋에서만 고릅니다. 시험 질의는 튜닝에 쓰지 않습니다.

```bash
python -m nlu.cli tune --model-id nlpai-lab/KoE5 --model-path ../nlu-models/nlpai-lab__KoE5 --report artifacts/evidence/tune_KoE5.json --write-config
```

시험기관이 문자 점수 결합을 허용하지 않으면 `--beta 0`으로 임베딩만 사용합니다.

## 100건 실행과 평가

```bash
python -m nlu.cli run --model-id nlpai-lab/KoE5 --model-path ../nlu-models/nlpai-lab__KoE5 --questions data/questions_holdout.json --dataset-type real_anonymized_holdout
python scripts/build_deliverables.py --run-dir artifacts/runs/<run-id>
```

정식 실행은 커밋된 깨끗한 작업트리에서 합니다. manifest에 Git 커밋, 작업트리 변경 여부, 질의·템플릿·대표 질문·검색 설정·모델 해시가 남습니다.

‘평가자A_실평가.xlsx’와 ‘평가자B_실평가.xlsx’는 서로 다른 실제 평가자가 독립적으로 작성합니다. 불일치 처리 규칙은 평가 시작 전에 정합니다.

협의:
```bash
python scripts/collect_ratings.py --run-dir artifacts/runs/<run-id> --a <A.xlsx> --b <B.xlsx> --resolution <협의결과.csv> --output <ratings.csv>
python -m nlu.cli score --run-dir artifacts/runs/<run-id> --ratings <ratings.csv> --decision-rule consensus --output <metrics.json>
```

다수결(제3평가자 C가 불일치 건만 블라인드 판정):
```bash
python scripts/make_tiebreak_workbook.py --run-dir artifacts/runs/<run-id> --a <A.xlsx> --b <B.xlsx> --output 평가자C_실평가.xlsx
python scripts/collect_ratings.py --run-dir artifacts/runs/<run-id> --a <A.xlsx> --b <B.xlsx> --c 평가자C_실평가.xlsx --decision-rule majority --output <ratings.csv>
python -m nlu.cli score --run-dir artifacts/runs/<run-id> --ratings <ratings.csv> --decision-rule majority --output <metrics.json>
```

산출 지표:
- 적합도(%) = 최종 성공 수 ÷ 100 × 100
- 합의율(%) = 최초 A=B 일치 수 ÷ 100 × 100 (협의·다수결 전 기준)
- ISO/IEC 25023 FCr-1-G: X = 1 − A/B (A = 최종 실패 수, B = 100). 적합도와 같은 값입니다. 표준 원문과의 대응은 시험기관 확인이 필요합니다.

최종 판정 100건이 모두 확정되기 전에는 적합도를 산출하지 않습니다. 입력 파일의 이름만으로 서명·자격·실제 평가 행위를 인증하지 않습니다. submission_candidate는 전문가 승인, 기관 승인, 평가자 기록, 설문, 협의/다수결 기록이 모두 갖춰질 때만 true가 됩니다.

## 실제 고객 질의와 승인

[docs/실질의_수집_및_승인절차.md](docs/실질의_수집_및_승인절차.md) 참고.
```bash
python scripts/prepare_real_queries.py --input <상담내역.csv> --output data/questions_holdout_candidate.json
python scripts/apply_annotations.py --questions data/questions_holdout_candidate.json --annotations <주석.csv> --output data/questions_holdout.json
python scripts/approval_hashes.py --questions data/questions_holdout.json --output data/approval.draft.json
```
자동 익명화는 1차 처리일 뿐이며 사람이 전부 다시 확인합니다. 승인서(data/approval.json)는 실제 서명 기록으로만 채우고 Git에 올리지 않습니다.

## 시험기관 확인

[docs/시험기관_확인요청서.md](docs/시험기관_확인요청서.md)에 모델 인정, 하이브리드 검색 허용, 표본 기준, 다수결/협의, ISO 표기, 합격 기준 등 14개 질문을 정리했습니다. 회신 문서 번호를 data/approval.json에 기록합니다.

## 옵션 LLM 후보 선택

E5 상위 3개 중 OpenAI가 template_id 하나를 고르는 어댑터입니다. NLU_LLM_API_KEY를 환경 변수로 설정하고 `--mode llm_select --llm-model <승인모델>`로 실행합니다. 키는 채팅이나 Git에 저장하지 않습니다. 후보 밖 선택은 오류로 처리하며, 인증이 없으면 외부 호출을 하지 않습니다.

## 테스트

```bash
python -m unittest discover -s tests -v
```
