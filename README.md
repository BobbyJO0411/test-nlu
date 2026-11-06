# 상표 NLU 응답 추천·시험 준비 패키지

첨부 「상표심사기준」(2025.12.10)을 참고한 100건 합성 질의, 기준답변 초안, 30개 등록 응답 템플릿, E5 검색 API, 독립 평가용 XLSX와 시험방법서입니다. 실제 실무자·변리사의 평가·승인은 아직 없습니다. 가상 A·B 결과는 규칙 기반 모의 예제이며 시험성적으로 제출할 수 없습니다.

## 구성

| 위치 | 내용 |
|---|---|
| data/questions_100.json, .csv | 25유형 × 4건, 문맥·구어·오해·경계조건 질의 |
| data/templates.json | 30개 대표 질문·응답 원문·근거·승인 상태 |
| data/source_excerpts.json | PDF 물리 페이지·원문 발췌, 인쇄 쪽수 |
| nlu/engine.py, api.py | E5 임베딩 → top3 후보 → 템플릿 원문 추천 |
| nlu/llm.py | 옵션 OpenAI 후보 ID 선택; 자유 답변 생성 없음 |
| nlu/cli.py, metrics.py | 실행ID·환경·해시·추천 원문 기록, 완전성 검증·집계 |
| scripts/build_deliverables.py | 별도 A/B 평가파일·총괄 데이터시트·DOCX·명시적 모의 예제 생성 |
| scripts/collect_ratings.py | 실제 독립 평가파일과 협의 기록 결합 |
| artifacts/review_package | 검토용 XLSX·DOCX, 개발 실행 원문, 모의 예제 |
| docs | 시험방법·평가 기준·결과 작성 양식·제출 체크리스트 |

## 설치 및 실행

Python 3.12 / Linux CPU 기준입니다. 각 클라우드 작업은 격리된 환경이므로 기존 /workspace/test-nlu 체크아웃을 사용하며 별도 worktree를 만들 필요가 없습니다.

```bash
cd /workspace/test-nlu
bash scripts/install.sh
bash scripts/start.sh
```

API는 /health, POST /recommend를 제공합니다. 내부 검증 요청 예시:

```bash
curl --fail -H 'Content-Type: application/json' \
  -d '{"query":"상표 의견제출통지서를 받았는데 최종 거절인가요?"}' \
  http://127.0.0.1:8000/recommend
```

기본 모델은 intfloat/multilingual-e5-small입니다. 한국어를 지원하는 E5 계열이며 별도 E5-Ko 전용 학습이나 이 데이터셋에 대한 미세조정을 수행한 모델이 아닙니다. 시험기관이 특정 E5-Ko 또는 KoBERT를 요구하면 모델 승인 후 --model-id로 지정해 다시 검증해야 합니다. 설치 스크립트는 검증된 모델 커밋 614241f622f53c4eeff9890bdc4f31cfecc418b3을 지정합니다. 실제 모델 SHA와 파일 해시는 다운로드 시 고정되며 오류 시 baseline으로 대체하지 않습니다.

## 100건 실제 실행과 평가 파일

```bash
/workspace/nlu-venv/bin/python -m nlu.cli run --backend e5 --model-path /workspace/nlu-model
/workspace/nlu-venv/bin/python scripts/build_deliverables.py --run-dir artifacts/runs/<run-id>
```

생성된 ‘평가자A_실평가.xlsx’와 ‘평가자B_실평가.xlsx’는 각각 독립된 실제 평가자가 작성합니다. ‘NLU_100건_평가데이터시트.xlsx’는 기준답변 검토·실행 결과·평가집계와 모의 계산 예제를 분리한 총괄 검토 파일입니다. actual 평가자에게 모의 파일과 상대 평가를 보여주지 않습니다.

```bash
/workspace/nlu-venv/bin/python scripts/collect_ratings.py \
  --run-dir artifacts/runs/<run-id> --a <A.xlsx> --b <B.xlsx> \
  --resolution <협의결과.csv> --output <ratings.csv>
/workspace/nlu-venv/bin/python -m nlu.cli score \
  --run-dir artifacts/runs/<run-id> --ratings <ratings.csv> --output <metrics.json>
```

최종 판정이 100건 확정되기 전에는 적합도를 산출하지 않습니다. 최초 합의율은 협의 전 A=B 건수/100입니다. A/B 두 명의 불일치는 협의로 확정하며 근거를 필수 기록합니다. 입력 파일의 이름만으로 서명·자격·실제 평가행위를 인증하지 않습니다.

실무자 승인 후 approval.example.json을 참고해 approval.json에 실기록과 현재 파일 해시를 입력하고 서명 승인서 원본을 보관합니다. 채워 넣을 승인 이름·판정·서명은 생성하지 않았습니다.

## 옵션 LLM 후보 선택

기존 OpenAI 연계를 위한 후보 선택 어댑터를 제공합니다. NLU_LLM_API_KEY를 안전하게 설정한 뒤 --mode llm_select --llm-model <승인모델>로 실행합니다. 키는 채팅이나 Git에 저장하지 않습니다. API 입력·프롬프트 해시, 모델명·응답ID·사용량을 기록하며 검색 후보 밖의 선택은 오류로 처리합니다. 이 모드의 실제 외부 API 호출은 인증이 없으면 수행하지 않습니다. 기존 제품에 연결된 상태나 자유 생성 API 결과와 동일하다고 주장하지 않습니다.

## 검증과 해석

```bash
/workspace/nlu-venv/bin/python -m unittest discover -s tests -v
/workspace/nlu-venv/bin/python -m nlu.cli run --backend baseline
```

baseline은 개발 비교용 문자 검색입니다. 기대 템플릿 ID 일치율은 검색 진단이고 사람이 ‘수정 없이 사용 가능’하다고 평가한 적합도와 다릅니다. docs/현재검증결과.md에 실제 실행된 검증과 남은 요구사항을 기록합니다.

현재 100건은 템플릿과 함께 작성된 합성 초안입니다. 미사용 독립 시험셋 또는 실제 고객 로그라고 표시할 수 없습니다. 최종 시험에는 전문가 사전 승인, 운영 분포 검토·기관 승인, 실제 독립 평가·협의·서명이 필요합니다. ISO 인용 코드와 산식 대응, 특정 모델 허용 여부 및 합격 기준은 시험기관 확인 전입니다.
