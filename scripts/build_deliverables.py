"""Build review workbooks, clearly marked simulations and editable DOCX documents."""
import argparse,csv,json,sys
from pathlib import Path
from collections import Counter
sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
from nlu.engine import ROOT,digest
from nlu.metrics import summarize
from openpyxl import Workbook
from openpyxl.styles import Font,PatternFill,Alignment
from openpyxl.worksheet.datavalidation import DataValidation
from openpyxl.chart import BarChart,Reference
from docx import Document
from docx.shared import Pt

p=argparse.ArgumentParser();p.add_argument('--run-dir',required=True);p.add_argument('--out',default=str(ROOT/'artifacts/review_package'))
a=p.parse_args();run=Path(a.run_dir);out=Path(a.out);out.mkdir(parents=True,exist_ok=True)
templates=json.loads((ROOT/'data/templates.json').read_text(encoding='utf-8'))
sources=json.loads((ROOT/'data/source_excerpts.json').read_text(encoding='utf-8'))
results=json.loads((run/'recommendations.json').read_text(encoding='utf-8'));manifest=json.loads((run/'manifest.json').read_text(encoding='utf-8'))
questions_path=ROOT/manifest.get('questions_path','data/questions_100.json')
questions=json.loads(questions_path.read_text(encoding='utf-8'))
if digest(run/'recommendations.json')!=manifest['recommendations_sha256']:raise ValueError('Results changed')
if digest(questions_path)!=manifest['questions_sha256']:raise ValueError('Dataset changed')
byid={r['case_id']:r for r in results}
if set(byid)!={q['case_id'] for q in questions} or len(results)!=100:raise ValueError('Require 100 unique results')
backend=manifest['engine']['backend'];runid=manifest['run_id']

def decorate(ws):
    ws.freeze_panes='A2';ws.auto_filter.ref=ws.dimensions
    for cell in ws[1]:
        cell.font=Font(bold=True,color='FFFFFF');cell.fill=PatternFill('solid',fgColor='25476A')
        cell.alignment=Alignment(wrap_text=True,vertical='top')
    for row in ws.iter_rows(min_row=2):
        for cell in row:cell.alignment=Alignment(wrap_text=True,vertical='top')
    for col in ws.columns:
        letter=col[0].column_letter
        header=str(col[0].value or '')
        width=24
        if any(x in header for x in ['질의','query']):width=60
        if any(x in header for x in ['답변','응답원문','answer','추천원문']):width=95
        if header in ['값','해석','평가근거','검토의견','모의협의근거']:width=70
        if header in ['ID','case_id']:width=12
        ws.column_dimensions[letter].width=width
    if ws.max_column>=6:
        for i in range(2,ws.max_row+1):ws.row_dimensions[i].height=100
    ws.sheet_view.zoomScale=80

def save(wb,name):
    for ws in wb:decorate(ws)
    wb.save(out/name)

def meta(wb,kind):
    ws=wb.create_sheet('안내');ws.append(['항목','값'])
    for row in [('자료구분',kind),('실행ID',runid),('추천파일SHA256',manifest['recommendations_sha256']),('백엔드',backend),
        ('중요','전문가 승인 전 자료. baseline 실행은 E5/KoBERT 시험 근거가 아닙니다.'),
        ('모델',str(manifest['engine'].get('model_id'))+' @ '+str(manifest['engine'].get('revision'))),
        ('질의파일',str(manifest.get('questions_path','data/questions_100.json'))+' / '+str(manifest.get('dataset_type'))),
        ('평가절차','A·B는 별도 파일에서 독립 평가. 상대 평가나 모의 시트 열람 전 판정 고정.'),
        ('성공기준','다섯 기준 모두 충족하고 수정 없이 바로 사용할 수 있을 때 success. 그 외 failure.'),
        ('주의','문항 일부 수정, 근거 부족, 결과 확정 과장 또는 질문 핵심 누락도 failure.'),
        ('개인정보','합성 질의이며 고객 식별정보 없음. 실제 평가자는 성명·자격·일시를 직접 입력.')]:ws.append(row)
    ws.column_dimensions['B'].width=100

# Standalone blinded evaluator files: no gold answer, simulated votes or other rater results.
headers=['case_id','query','recommended_answer','source_pages','문맥_1to5','정확성_1to5','완결성_1to5','활용성_1to5','안전성_1to5','판정_success_failure','평가근거','평가자성명','역할자격','평가일시']
for role in ['A','B']:
    wb=Workbook();wb.remove(wb.active);meta(wb,'실제 평가 입력용 — 미평가')
    ws=wb.create_sheet('평가');ws.append(headers)
    for q in questions:
        r=byid[q['case_id']]
        page_list=sorted({n for c in r['candidates'][:1] for s in c['source_ids'] for n in sources[s]['pdf_pages']})
        ws.append([q['case_id'],q['query'],r['recommended_answer'],','.join(map(str,page_list))]+['']*10)
    dv=DataValidation(type='list',formula1='"success,failure"');dv.errorTitle='판정 값 오류';dv.error='success 또는 failure';dv.showErrorMessage=True;ws.add_data_validation(dv);dv.add('J2:J101')
    scores=DataValidation(type='whole',operator='between',formula1=1,formula2=5);scores.showErrorMessage=True;ws.add_data_validation(scores);scores.add('E2:I101')
    ws.column_dimensions['B'].width=60;ws.column_dimensions['C'].width=100
    save(wb,f'평가자{role}_실평가.xlsx')

# Simulation rules are deliberately visible and do not masquerade as professional opinions.
simulation=[]
for i,q in enumerate(questions,1):
    match=byid[q['case_id']]['selected_template_id'] in q['expected_template_ids']
    a_vote='success' if match else 'failure'
    b_vote='failure' if match and i%13==0 else a_vote
    simulation.append({'case_id':q['case_id'],'evidence_kind':'simulation',
        'a':a_vote,'b':b_vote,'final':b_vote if a_vote!=b_vote else a_vote,
        'resolution_reason':'가상 협의 예제: 보수적으로 실패 선택 (실제 협의 없음)' if a_vote!=b_vote else '',
        'a_reason':'모의 규칙 A: 기대 템플릿 ID 일치 여부만 사용',
        'b_reason':'모의 규칙 B: A 규칙에 더해 13의 배수 ID는 실패 처리. 전문 판단 아님.',
        'a_1to5':'5' if a_vote=='success' else '2','b_1to5':'5' if b_vote=='success' else '2',
        'a_name':'SIMULATED_A_실무자역할','b_name':'SIMULATED_B_변리사역할','a_date':'SIMULATED','b_date':'SIMULATED'})
summary=summarize(simulation,[q['case_id'] for q in questions]);summary.update(evidence_kind='simulation',submission_candidate=False,
    note='Rules-based demonstration, not actual practitioner/attorney evaluation or measured human suitability',backend=backend,run_id=runid)
(out/'모의평가_집계.json').write_text(json.dumps(summary,ensure_ascii=False,indent=2),encoding='utf-8')
with (out/'모의평가_제출불가.csv').open('w',encoding='utf-8-sig',newline='') as f:
    w=csv.DictWriter(f,fieldnames=list(simulation[0]));w.writeheader();w.writerows(simulation)
with (out/'협의결과_빈양식.csv').open('w',encoding='utf-8-sig',newline='') as f:
    w=csv.DictWriter(f,fieldnames=['case_id','final','resolution_reason','resolution_date','participants']);w.writeheader();w.writerows({'case_id':q['case_id']} for q in questions)

wb=Workbook();wb.remove(wb.active);meta(wb,'총괄 검토용 — 모의평가 분리, 실평가 미수행')
ws=wb.create_sheet('데이터셋검토');ws.append(['ID','유형','질의','기준답변_검토전','기대템플릿','PDF근거페이지','검토자','승인일','승인상태','검토의견'])
for q in questions:
    nums=','.join(str(n) for sid in q['source_ids'] for n in sources[sid]['pdf_pages'])
    ws.append([q['case_id'],q['category'],q['query'],q['reference_answer'],','.join(q['expected_template_ids']),nums,'','','pending_expert_review',''])
ws.column_dimensions['C'].width=65;ws.column_dimensions['D'].width=100
ws=wb.create_sheet('템플릿DB');ws.append(['ID','유형','대표질의','등록응답원문','PDF근거페이지','승인상태'])
for t in templates:ws.append([t['template_id'],t['category'],t['representative_query'],t['answer'],','.join(str(n) for sid in t['source_ids'] for n in sources[sid]['pdf_pages']),t['approval_status']])
ws.column_dimensions['D'].width=100
ws=wb.create_sheet('실행결과');ws.append(['ID','질의','자동추천원문','Top1','Top1점수','Top2','Top2점수','Top3','Top3점수','응답ms','백엔드'])
for q in questions:
    r=byid[q['case_id']];c=r['candidates'];ws.append([q['case_id'],q['query'],r['recommended_answer'],c[0]['template_id'],c[0]['score'],c[1]['template_id'],c[1]['score'],c[2]['template_id'],c[2]['score'],r['latency_ms'],backend])
ws.column_dimensions['B'].width=65;ws.column_dimensions['C'].width=100
ws=wb.create_sheet('실평가집계_빈양식');ws.append(['ID','A판정','B판정','최초일치','협의최종','협의근거','최종판정','유형'])
for i,q in enumerate(questions,2):
    ws.append([q['case_id'],'','',f'=IF(OR(B{i}="",C{i}=""),"",IF(B{i}=C{i},1,0))','','',
        f'=IF(OR(B{i}="",C{i}=""),"",IF(B{i}=C{i},B{i},IF(OR(E{i}="",F{i}=""),"",E{i})))',q['category']])
dv=DataValidation(type='list',formula1='"success,failure"');dv.showErrorMessage=True;ws.add_data_validation(dv);dv.add('B2:C101');dv.add('E2:E101')
ws=wb.create_sheet('실평가요약');ws.append(['지표','값','해석'])
ws.append(['평가완료쌍','=COUNT(실평가집계_빈양식!D2:D101)','100쌍 전까지 합의율 미산출'])
ws.append(['최종판정완료','=COUNTIF(실평가집계_빈양식!G2:G101,"success")+COUNTIF(실평가집계_빈양식!G2:G101,"failure")','미협의 건이 있으면 적합도 미산출'])
ws.append(['적합도','=IF(B3=100,COUNTIF(실평가집계_빈양식!G2:G101,"success")/100,"")','최종 성공/100; 실제 서명 평가 기록 필요'])
ws.append(['최초합의율','=IF(B2=100,SUM(실평가집계_빈양식!D2:D101)/100,"")','A=B/100; 협의 후 일치로 덮어쓰지 않음'])
ws.append(['ISO FCr-1-G X=1-A/B','=IF(B3=100,1-COUNTIF(실평가집계_빈양식!G2:G101,"failure")/100,"")','A=실패 응답 수, B=100. 적합도와 같은 값; 표준 원문 대응은 기관 확인'])
ws.append(['제출가능여부','미확정','기준선 백엔드이면 불가. E5 실행, 전문가 승인·서명, 기관 확인 필요'])
ws['B4'].number_format=ws['B5'].number_format=ws['B6'].number_format='0.00%'
ws=wb.create_sheet('모의평가_제출불가');ws.append(['ID','가상A_규칙','가상B_규칙','최초일치','가상최종','모의협의근거','자료구분'])
for r in simulation:ws.append([r['case_id'],r['a'],r['b'],int(r['a']==r['b']),r['final'],r['resolution_reason'],'SIMULATION — 실평가 아님'])
ws=wb.create_sheet('모의요약_제출불가');ws.append(['지표','값','분모','자료구분'])
ws.append(['규칙 기반 가상 적합도',summary['suitability_pct']/100,100,'실제 성능 아님'])
ws.append(['규칙 기반 가상 최초 합의율',summary['agreement_pct']/100,100,'실제 평가자 합의 아님'])
ws['B2'].number_format=ws['B3'].number_format='0.00%'
ws.append(['가상 성공',summary['success_count'],100,'SIMULATION'])
ws.append(['가상 실패',summary['failure_count'],100,'SIMULATION'])
chart=BarChart();chart.title='모의 계산 예제 — 제출 불가';chart.add_data(Reference(ws,min_col=2,min_row=1,max_row=3),titles_from_data=True);chart.set_categories(Reference(ws,min_col=1,min_row=2,max_row=3));ws.add_chart(chart,'F2')
ws=wb.create_sheet('유형별분포');ws.append(['유형','건수','가상성공','가상실패'])
for category,count in Counter(q['category'] for q in questions).items():
    related=[r for r,q in zip(simulation,questions) if q['category']==category]
    ws.append([category,count,sum(r['final']=='success' for r in related),sum(r['final']=='failure' for r in related)])
save(wb,'NLU_100건_평가데이터시트.xlsx')

# Render authored methodology and report templates to editable DOCX; content remains Markdown in Git.
for filename in ['시험방법서.md','평가기준_설문_협의절차.md','시험성적서_작성양식.md','근거검토_및_제출체크리스트.md','시험기관_확인요청서.md','실질의_수집_및_승인절차.md']:
    source=ROOT/'docs'/filename
    if not source.exists():continue
    document=Document();document.styles['Normal'].font.name='맑은 고딕';document.styles['Normal'].font.size=Pt(10)
    for line in source.read_text(encoding='utf-8').splitlines():
        if line.startswith('# '):document.add_heading(line[2:],0)
        elif line.startswith('## '):document.add_heading(line[3:],1)
        elif line.startswith('### '):document.add_heading(line[4:],2)
        elif line.startswith('- '):document.add_paragraph(line[2:],style='List Bullet')
        else:document.add_paragraph(line)
    document.save(out/source.with_suffix('.docx').name)
# Preserve actual baseline outputs alongside simulations, never relabel them E5.
for file in ['manifest.json','recommendations.json','ratings_blank.csv']:
    (out/('개발실행_'+file)).write_bytes((run/file).read_bytes())
files={f.name:digest(f) for f in out.iterdir() if f.is_file() and f.name!='package_manifest.json'}
(out/'package_manifest.json').write_text(json.dumps({'run_id':runid,'backend':backend,'model_id':manifest['engine'].get('model_id'),'status':'draft_review_package','files_sha256':files,'simulated_metrics_submission_eligible':False},ensure_ascii=False,indent=2),encoding='utf-8')
print(json.dumps({'output':str(out),'simulation_only':summary,'backend':backend},ensure_ascii=False))
