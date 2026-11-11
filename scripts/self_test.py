"""Self-conducted test for 「NLU 기반 반자동 응답 추천 기능 적합도」, end to end.

  prepare : run the NLU on the 100 test queries and create the A/B evaluator workbooks
  resolve : after A and B finish, list their disagreements (협의 sheet, or C workbook for 다수결)
  score   : collect all judgments, compute 적합도(%), 합의율(%), FCr-1-G and write the result report
            with a pass/fail verdict against the threshold (default 적합도 >= 80%)

Every success/failure judgment comes from the evaluators' workbooks. This script never fills one in."""
import argparse,csv,json,shutil,statistics,subprocess,sys
from collections import Counter,defaultdict
from datetime import datetime,timezone
from pathlib import Path
sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
from nlu.engine import ROOT,DEFAULT_MODEL,default_model_dir,digest
from nlu.metrics import summarize
from openpyxl import Workbook,load_workbook
from openpyxl.styles import Font,PatternFill,Alignment
from openpyxl.worksheet.datavalidation import DataValidation

OUT_ROOT=ROOT/'artifacts/self_test'
HEADERS=['case_id','query','recommended_answer','source_pages','문맥_1to5','정확성_1to5','완결성_1to5','활용성_1to5','안전성_1to5',
    '판정_success_failure','평가근거','평가자성명','역할자격','평가일시']
SURVEY=[('context','문맥 적합성'),('correctness','법적·사실 정확성'),('completeness','완결성'),('usability','실무 활용성'),('safety','안전성과 표현')]
RESOLUTION_FIELDS=['case_id','query','recommended_answer','A판정','A근거','B판정','B근거','final','resolution_reason','resolution_date','participants']
DEFAULT_THRESHOLD=80.0

def load_json(path):
    return json.loads(Path(path).read_text(encoding='utf-8'))

def style(ws,widths):
    ws.freeze_panes='A2'
    for cell in ws[1]:
        cell.font=Font(bold=True,color='FFFFFF');cell.fill=PatternFill('solid',fgColor='25476A')
        cell.alignment=Alignment(wrap_text=True,vertical='top')
    for row in ws.iter_rows(min_row=2):
        for cell in row:cell.alignment=Alignment(wrap_text=True,vertical='top')
    for col,w in widths.items():ws.column_dimensions[col].width=w

def questions_of(manifest):
    path=ROOT/manifest.get('questions_path','data/questions_100.json')
    return load_json(path)

# ---------------------------------------------------------------- prepare
def evaluator_workbook(path,role,manifest,results,questions,sources,threshold):
    byid={r['case_id']:r for r in results}
    wb=Workbook();wb.remove(wb.active)
    info=wb.create_sheet('안내');info.append(['항목','값'])
    for row in [('자료구분',f'평가자 {role} 실평가 입력용'),('실행ID',manifest['run_id']),('추천파일SHA256',manifest['recommendations_sha256']),
        ('백엔드',manifest['engine']['backend']),('모델',f"{manifest['engine'].get('model_id')} @ {manifest['engine'].get('revision')}"),
        ('평가 방법','각 고객 질의에 대해 자동 추천된 응답이 실제 문맥에 적합한지 평가합니다. 다른 평가자의 판정은 보지 않습니다.'),
        ('성공(success)','추천 응답을 수정 없이 그대로 고객 답변으로 활용 가능한 경우'),
        ('실패(failure)','불완전하거나 수정이 필요한 경우(내용 추가·삭제·수정, 잘못된 절차·기한·금액, 핵심 누락, 근거 없는 단정)'),
        ('정량 설문','문맥·정확성·완결성·활용성·안전성을 1~5점으로 입력 (1 전혀 충족하지 않음 ~ 5 완전히 충족)'),
        ('필수 입력','판정, 설문 5개, 평가근거, 평가자성명, 역할자격(실무자/변리사/고객 상담자), 평가일시를 100건 모두 입력'),
        ('합격 기준',f'적합도(성공 응답 수 ÷ 100 × 100) {threshold:g}% 이상')]:info.append(row)
    style(info,{'A':16,'B':110})
    ws=wb.create_sheet('평가');ws.append(HEADERS)
    for q in questions:
        r=byid[q['case_id']]
        pages=sorted({n for s in r['candidates'][0]['source_ids'] for n in sources[s]['pdf_pages']})
        ws.append([q['case_id'],q['query'],r['recommended_answer'],','.join(map(str,pages))]+['']*10)
    n=len(questions)+1
    dv=DataValidation(type='list',formula1='"success,failure"');dv.error='success 또는 failure';dv.showErrorMessage=True
    ws.add_data_validation(dv);dv.add(f'J2:J{n}')
    sc=DataValidation(type='whole',operator='between',formula1=1,formula2=5);sc.showErrorMessage=True
    ws.add_data_validation(sc);sc.add(f'E2:I{n}')
    style(ws,{'A':9,'B':55,'C':90,'D':12,'E':9,'F':9,'G':9,'H':9,'I':9,'J':14,'K':40,'L':12,'M':16,'N':14})
    for i in range(2,n+1):ws.row_dimensions[i].height=110
    wb.save(path)

def prepare(a):
    if a.run_dir:
        run=Path(a.run_dir)
    else:
        model_path=a.model_path or str(default_model_dir(a.model_id))
        cmd=[sys.executable,'-m','nlu.cli','run','--model-id',a.model_id,'--model-path',model_path,
            '--questions',a.questions,'--dataset-type',a.dataset_type,'--output',str(ROOT/'artifacts/runs')]
        proc=subprocess.run(cmd,cwd=ROOT,capture_output=True,text=True,encoding='utf-8')
        if proc.returncode:
            sys.stderr.write(proc.stdout+proc.stderr);raise SystemExit('NLU run failed; nothing was created')
        run=Path(json.loads(proc.stdout.strip().splitlines()[-1])['run_dir'])
    manifest=load_json(run/'manifest.json');results=load_json(run/'recommendations.json')
    if digest(run/'recommendations.json')!=manifest['recommendations_sha256']:raise SystemExit('Recommendation file changed after the run')
    if manifest['engine']['backend']!='e5':raise SystemExit('The self test must use the E5 embedding model, not the lexical baseline')
    questions=questions_of(manifest)
    if len(results)!=100 or {r['case_id'] for r in results}!={q['case_id'] for q in questions}:raise SystemExit('Run must cover exactly the 100 test queries')
    out=Path(a.out)/manifest['run_id'];out.mkdir(parents=True,exist_ok=True)
    for f in ['manifest.json','recommendations.json']:shutil.copyfile(run/f,out/f)
    sources=load_json(ROOT/'data/source_excerpts.json')
    for role in ['A','B']:evaluator_workbook(out/f'평가자{role}.xlsx',role,manifest,results,questions,sources,a.threshold)
    lat=[r['latency_ms'] for r in results]
    summary={'run_id':manifest['run_id'],'folder':str(out),'model':manifest['engine'].get('model_id'),
        'git_commit':manifest.get('git_commit'),'git_worktree_clean':manifest.get('git_worktree_clean'),
        'latency_ms_median':round(statistics.median(lat),1),'latency_ms_p95':round(sorted(lat)[94],1),
        'retrieval_diagnostic':manifest.get('retrieval_diagnostic'),
        'next':'평가자A.xlsx, 평가자B.xlsx를 각 평가자에게 따로 전달하세요. 둘 다 받으면 resolve 단계를 실행합니다.'}
    (out/'실행요약.json').write_text(json.dumps(summary,ensure_ascii=False,indent=2)+'\n',encoding='utf-8')
    print(json.dumps(summary,ensure_ascii=False,indent=2))

# ---------------------------------------------------------------- resolve
def judgments(path):
    wb=load_workbook(path,data_only=True)
    return {row[0]:row for row in list(wb['평가'].values)[1:] if row and row[0]}

def resolve(a):
    run=Path(a.run_dir);manifest=load_json(run/'manifest.json')
    ra,rb=judgments(a.a),judgments(a.b)
    missing=[cid for cid in ra if ra[cid][9] not in ('success','failure') or rb.get(cid,[None]*10)[9] not in ('success','failure')]
    if missing:raise SystemExit('A and B must finish all cases first. Missing: '+', '.join(missing[:20]))
    diff=[cid for cid in ra if ra[cid][9]!=rb[cid][9]]
    agree=len(ra)-len(diff)
    if a.decision_rule=='majority':
        out=run/'평가자C.xlsx'
        subprocess.run([sys.executable,str(ROOT/'scripts/make_tiebreak_workbook.py'),'--run-dir',str(run),'--a',a.a,'--b',a.b,'--output',str(out)],check=True)
    else:
        out=run/'협의결과.csv'
        with out.open('w',encoding='utf-8-sig',newline='') as f:
            w=csv.DictWriter(f,fieldnames=RESOLUTION_FIELDS);w.writeheader()
            for cid in diff:
                x,y=ra[cid],rb[cid]
                w.writerow({'case_id':cid,'query':x[1],'recommended_answer':x[2],'A판정':x[9],'A근거':x[10],'B판정':y[9],'B근거':y[10]})
    print(json.dumps({'initial_agreements':agree,'disagreements':len(diff),'case_ids':diff,'file':str(out),
        'next':('평가자C.xlsx를 제3평가자에게 전달하세요.' if a.decision_rule=='majority' else
            '협의결과.csv의 final(success/failure), resolution_reason, resolution_date, participants를 채우세요.')},ensure_ascii=False,indent=2))

# ---------------------------------------------------------------- score
def survey_stats(rows):
    stats={}
    for person in ['a','b']:
        for key,label in SURVEY:
            vals=[int(r[f'{person}_{key}']) for r in rows]
            stats[f'{person}_{key}']={'label':label,'mean':round(sum(vals)/len(vals),2),'distribution':{str(i):vals.count(i) for i in range(1,6)}}
    return stats

def verdict_of(result,threshold):
    if result['status']!='complete':return '판정 불가'
    return '합격' if result['suitability_pct']>=threshold else '불합격'

def score(a):
    run=Path(a.run_dir);manifest=load_json(run/'manifest.json');results=load_json(run/'recommendations.json')
    if digest(run/'recommendations.json')!=manifest['recommendations_sha256']:raise SystemExit('Recommendation file changed after the run')
    questions=questions_of(manifest);qby={q['case_id']:q for q in questions};rby={r['case_id']:r for r in results}
    ratings=run/'ratings.csv'
    cmd=[sys.executable,str(ROOT/'scripts/collect_ratings.py'),'--run-dir',str(run),'--a',a.a,'--b',a.b,'--decision-rule',a.decision_rule,'--output',str(ratings)]
    if a.decision_rule=='majority':cmd+=['--c',a.c or str(run/'평가자C.xlsx')]
    else:
        res=a.resolution or str(run/'협의결과.csv')
        if Path(res).exists():cmd+=['--resolution',res]
    proc=subprocess.run(cmd,capture_output=True,text=True,encoding='utf-8')
    if proc.returncode:sys.stderr.write(proc.stderr);raise SystemExit('평가 파일 확인 실패: '+(proc.stderr.strip().splitlines() or ['?'])[-1])
    with ratings.open(encoding='utf-8-sig',newline='') as f:rows=list(csv.DictReader(f))
    result=summarize(rows,[q['case_id'] for q in questions],a.decision_rule)
    finals={}
    for r in rows:
        if r['a']==r['b']:finals[r['case_id']]=r['a']
        elif a.decision_rule=='majority':finals[r['case_id']]=r.get('c') or ''
        else:finals[r['case_id']]=r.get('final') or ''
    by_cat=defaultdict(Counter)
    for cid,f in finals.items():by_cat[qby[cid]['category']][f or 'unresolved']+=1
    lat=[r['latency_ms'] for r in results]
    verdict=verdict_of(result,a.threshold)
    approval_path=ROOT/'data/approval.json'
    approval=load_json(approval_path) if approval_path.exists() else {}
    gold={'recorded':bool(approval.get('reviewer_name') and approval.get('approval_date'))
            and approval.get('questions_sha256')==manifest['questions_sha256']
            and approval.get('templates_sha256')==manifest['engine'].get('templates_sha256'),
        'reviewer':approval.get('reviewer_name',''),'role':approval.get('reviewer_role',''),'date':approval.get('approval_date','')}
    report={'test_item':'NLU 기반 반자동 응답 추천 기능 적합도','created_utc':datetime.now(timezone.utc).isoformat(),
        'run_id':manifest['run_id'],'decision_rule':a.decision_rule,'threshold_pct':a.threshold,'verdict':verdict,
        'suitability_pct':result['suitability_pct'],'agreement_pct':result['agreement_pct'],
        'success_count':result['success_count'],'failure_count':result['failure_count'],
        'initial_agreements':result['initial_agreements'],'initial_disagreements':result['initial_disagreements'],
        'resolved_by_consensus':result['resolved_by_consensus'],'resolved_by_majority':result['resolved_by_majority'],
        'unresolved_ids':result['unresolved_ids'],'iso_25023':result['iso_25023'],'cohen_kappa':result.get('cohen_kappa'),
        'wilson_95_pct':result.get('wilson_95_pct'),'survey':survey_stats(rows),
        'by_category':{k:dict(v) for k,v in sorted(by_cat.items())},
        'evaluators':{p:sorted({(r[f'{p}_name'],r[f'{p}_role']) for r in rows if r.get(f'{p}_name')}) for p in ['a','b','c']},
        'latency_ms':{'median':round(statistics.median(lat),1),'p95':round(sorted(lat)[94],1)},
        'environment':{'model_id':manifest['engine'].get('model_id'),'revision':manifest['engine'].get('revision'),
            'dimension':manifest['engine'].get('dimension'),'retrieval':manifest['engine'].get('retrieval'),
            'python':manifest.get('python'),'platform':manifest.get('platform'),'git_commit':manifest.get('git_commit'),
            'git_worktree_clean':manifest.get('git_worktree_clean'),'questions_path':manifest.get('questions_path'),
            'questions_sha256':manifest.get('questions_sha256'),'templates_sha256':manifest['engine'].get('templates_sha256'),
            'recommendations_sha256':manifest['recommendations_sha256'],
            'dependencies':[d for d in manifest.get('dependencies',[]) if d.split('==')[0].lower() in
                ('torch','sentence-transformers','transformers','numpy','scikit-learn','openpyxl')]},
        'gold_set_approval':gold,'ratings_sha256':digest(ratings)}
    (run/'시험결과.json').write_text(json.dumps(report,ensure_ascii=False,indent=2)+'\n',encoding='utf-8')
    detail_workbook(run/'시험결과_상세.xlsx',rows,finals,qby,rby,report)
    write_report(run/'시험결과서.docx',report,manifest)
    print(json.dumps({k:report[k] for k in ['verdict','suitability_pct','agreement_pct','success_count','failure_count',
        'initial_agreements','unresolved_ids','threshold_pct']},ensure_ascii=False,indent=2))
    return 0 if verdict=='합격' else 1

def detail_workbook(path,rows,finals,qby,rby,report):
    wb=Workbook();ws=wb.active;ws.title='판정내역'
    ws.append(['case_id','유형','질의','추천 템플릿','추천 응답','A','B','C','최초일치','최종판정','A근거','B근거','협의/C 근거'])
    for r in rows:
        cid=r['case_id'];q=qby[cid];rec=rby[cid]
        ws.append([cid,q['category'],q['query'],rec['selected_template_id'],rec['recommended_answer'],r['a'],r['b'],r.get('c',''),
            int(r['a']==r['b']),finals[cid],r['a_reason'],r['b_reason'],r.get('resolution_reason') or r.get('c_reason','')])
    style(ws,{'A':9,'B':12,'C':50,'D':10,'E':70,'F':9,'G':9,'H':9,'I':9,'J':10,'K':35,'L':35,'M':35})
    s=wb.create_sheet('요약');s.append(['지표','값'])
    for k,label in [('suitability_pct','적합도(%)'),('agreement_pct','합의율(%)'),('success_count','최종 성공'),('failure_count','최종 실패'),
        ('initial_agreements','최초 일치'),('initial_disagreements','최초 불일치'),('threshold_pct','합격 기준(%)'),('verdict','판정')]:
        s.append([label,report[k]])
    s.append(['FCr-1-G X',report['iso_25023']['X'] if report['iso_25023'] else None])
    style(s,{'A':18,'B':20})
    c=wb.create_sheet('유형별');c.append(['유형','성공','실패','미해결'])
    for cat,cnt in report['by_category'].items():c.append([cat,cnt.get('success',0),cnt.get('failure',0),cnt.get('unresolved',0)])
    style(c,{'A':16,'B':8,'C':8,'D':8})
    v=wb.create_sheet('설문');v.append(['평가자','항목','평균','1','2','3','4','5'])
    for key,st in report['survey'].items():
        v.append([key[0].upper(),st['label'],st['mean']]+[st['distribution'][str(i)] for i in range(1,6)])
    style(v,{'A':8,'B':18,'C':8})
    wb.save(path)

def write_report(path,report,manifest):
    from docx import Document
    from docx.shared import Pt
    d=Document();d.styles['Normal'].font.name='맑은 고딕';d.styles['Normal'].font.size=Pt(10)
    def table(rows,header=None):
        t=d.add_table(rows=0,cols=len(rows[0]) if rows else 2);t.style='Table Grid'
        if header:
            cells=t.add_row().cells
            for i,h in enumerate(header):cells[i].text=str(h);cells[i].paragraphs[0].runs[0].bold=True
        for row in rows:
            cells=t.add_row().cells
            for i,v in enumerate(row):cells[i].text='' if v is None else str(v)
        d.add_paragraph()
    env=report['environment'];ret=env.get('retrieval') or {}
    d.add_heading('시험 결과서: NLU 기반 반자동 응답 추천 기능 적합도',0)
    d.add_paragraph(f"시험 실행 ID: {report['run_id']}    작성일시(UTC): {report['created_utc'][:19]}")
    d.add_heading('1. 시험 결과 요약',1)
    iso=report['iso_25023'] or {}
    table([['적합도(%)',fmt(report['suitability_pct'])],['합의율(%)',fmt(report['agreement_pct'])],
        ['ISO/IEC 25023 FCr-1-G (X = 1 − A/B)',iso.get('X')],
        ['최종 성공 / 실패',f"{report['success_count']} / {report['failure_count']} (전체 100)"],
        ['합격 기준',f"적합도 {report['threshold_pct']:g}% 이상"],['판정',report['verdict']]],header=['항목','결과'])
    d.add_heading('2. 측정 지표',1)
    for line in ['측정 지표: ISO/IEC 25023:2016 8.2.2 Functional correctness measures (FCr-1-G: Functional correctness)',
        '적합도(%) = (성공 응답 수 ÷ 전체 응답 수) × 100',
        '합의율(%) = (합의 응답 수 ÷ 전체 응답 수) × 100  ※ 합의 응답 수: 불일치 처리 전 평가자 A·B의 최초 판정이 일치한 건수',
        'FCr-1-G: X = 1 − A/B (A: 최종 실패 응답 수, B: 평가한 전체 응답 수). 적합도와 같은 값이며 백분율로 결과를 표시함']:
        d.add_paragraph(line,style='List Bullet')
    d.add_heading('3. 측정 검증 방법',1)
    for line in ['실무자 대상 정량 설문 결과 제출(5개 항목, 1~5점, 100건 전부)',
        f"평가 불일치 시 {'다수결(제3평가자 판정)' if report['decision_rule']=='majority' else '협의'}로 최종 판정 확정"]:
        d.add_paragraph(line,style='List Bullet')
    d.add_heading('4. 측정 방법',1)
    for line in ['실사용 환경을 반영한 고객 질의 100건을 기반으로 자동 추천된 응답 결과 수집',
        '각 응답 결과에 대해 실무자 또는 평가자(변리사 또는 고객 상담자)가 추천 응답이 실제로 문맥에 적합한지 평가',
        '적절한 응답으로 수정 없이 활용 가능한 경우 ‘성공’, 불완전하거나 수정이 필요한 경우 ‘실패’로 간주하여 적합도(%) 산출']:
        d.add_paragraph(line,style='List Bullet')
    d.add_heading('5. 측정 환경',1)
    for line in ['테스트 질의는 민원 유형에 따라 다양한 주제와 문장 구조를 포함하도록 구성(25개 유형 × 4건, 문장 구조 4종)',
        '정답셋은 민원 대응 실무자 또는 상담 경험자에 의해 사전 검토 및 승인: '+(f"{report['gold_set_approval']['reviewer']} ({report['gold_set_approval']['role']}), {report['gold_set_approval']['date']}" if report['gold_set_approval']['recorded'] else '승인 기록 없음(data/approval.json 미작성 또는 파일 해시 불일치)'),
        '추천 응답 후보는 사전 등록된 응답 템플릿 DB에서 추출(상위 3개 후보, 1순위 원문 추천)',
        '객관적인 문맥 적합성 확보를 위해 합의율을 산출']:
        d.add_paragraph(line,style='List Bullet')
    d.add_heading('6. 실행 환경',1)
    table([['모델',f"{env['model_id']} (E5-Ko 기반 문장 임베딩, {env.get('dimension')}차원)"],['모델 커밋',env['revision']],
        ['검색 방식',f"{ret.get('strategy')} α={ret.get('alpha')} β={ret.get('beta')}"],
        ['지표 산출','ISO 기준 산정식 적용 후 백분율로 결과 표시'],
        ['응답 지연시간',f"중앙값 {report['latency_ms']['median']} ms, 95백분위 {report['latency_ms']['p95']} ms"],
        ['운영체제',env['platform']],['Python',(env['python'] or '').split()[0]],['주요 라이브러리',', '.join(env['dependencies'])],
        ['소스 커밋',f"{env['git_commit']} (작업트리 변경 없음: {env['git_worktree_clean']})"],
        ['질의 파일',f"{env['questions_path']} / SHA256 {env['questions_sha256']}"],['템플릿 DB SHA256',env['templates_sha256']],
        ['추천 결과 SHA256',env['recommendations_sha256']],['평가 집계 SHA256',report['ratings_sha256']]],header=['항목','내용'])
    d.add_heading('7. 평가자',1)
    rows=[[p.upper(),n,r] for p,v in report['evaluators'].items() for n,r in v]
    table(rows or [['-','-','-']],header=['구분','성명','역할·자격'])
    d.add_heading('8. 판정 일치와 불일치 처리',1)
    table([['최초 일치',report['initial_agreements']],['최초 불일치',report['initial_disagreements']],
        ['협의로 확정',report['resolved_by_consensus']],['다수결로 확정',report['resolved_by_majority']],
        ['미해결',len(report['unresolved_ids'])],['Cohen κ (보조)',report['cohen_kappa']],
        ['적합도 Wilson 95% 구간 (보조)',report['wilson_95_pct']]],header=['항목','값'])
    d.add_heading('9. 유형별 결과',1)
    table([[c,v.get('success',0),v.get('failure',0)] for c,v in report['by_category'].items()],header=['유형','성공','실패'])
    d.add_heading('10. 정량 설문 결과 (평균, 1~5점)',1)
    labels=[l for _,l in SURVEY]
    table([[label,report['survey'][f'a_{k}']['mean'],report['survey'][f'b_{k}']['mean']] for k,label in SURVEY],header=['항목','평가자 A','평가자 B'])
    d.add_heading('11. 첨부',1)
    for line in ['평가자A.xlsx, 평가자B.xlsx (평가 원본)','협의결과.csv 또는 평가자C.xlsx (불일치 처리 기록)','ratings.csv (집계 입력)',
        '시험결과_상세.xlsx (건별 판정, 유형별, 설문)','manifest.json, recommendations.json (실행 기록과 추천 원문)','시험결과.json (산출값 원본)']:
        d.add_paragraph(line,style='List Bullet')
    d.save(path)

def fmt(v):
    return '산출 불가' if v is None else f'{v:.1f}'

def main(argv=None):
    p=argparse.ArgumentParser(description=__doc__,formatter_class=argparse.RawDescriptionHelpFormatter)
    sub=p.add_subparsers(dest='cmd',required=True)
    pr=sub.add_parser('prepare');pr.add_argument('--model-id',default=DEFAULT_MODEL);pr.add_argument('--model-path')
    pr.add_argument('--questions',default='data/questions_100.json');pr.add_argument('--dataset-type',default='practitioner_reviewed_test_set')
    pr.add_argument('--run-dir',help='use an existing artifacts/runs/<id> instead of running again')
    pr.add_argument('--out',default=str(OUT_ROOT));pr.add_argument('--threshold',type=float,default=DEFAULT_THRESHOLD)
    rs=sub.add_parser('resolve');rs.add_argument('--run-dir',required=True);rs.add_argument('--a',required=True);rs.add_argument('--b',required=True)
    rs.add_argument('--decision-rule',choices=['consensus','majority'],default='consensus')
    sc=sub.add_parser('score');sc.add_argument('--run-dir',required=True);sc.add_argument('--a',required=True);sc.add_argument('--b',required=True)
    sc.add_argument('--decision-rule',choices=['consensus','majority'],default='consensus')
    sc.add_argument('--resolution');sc.add_argument('--c');sc.add_argument('--threshold',type=float,default=DEFAULT_THRESHOLD)
    a=p.parse_args(argv)
    return {'prepare':prepare,'resolve':resolve,'score':score}[a.cmd](a) or 0

if __name__=='__main__':sys.exit(main())
