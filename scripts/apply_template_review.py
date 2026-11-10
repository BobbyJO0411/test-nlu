"""Check a completed template DB review workbook and, with --write, apply it to data/templates.json and
data/template_queries.json.

- Without --write the files are not touched; the script only validates and prints a summary.
- A workbook made from older files (hash mismatch) is refused.
- Every template and representative question must be judged; revise needs replacement text, remove needs a reason.
- Fully approved: every template gets approval_status=approved and an expert_review record.
- Revisions: the text is replaced and the item is marked revised_pending_reconfirm. Retune on the dev set and run a
  second review round with a fresh workbook; nothing is approved until a round passes with no changes.
- Template removal is never applied automatically, because it changes expected template IDs and the dev set.
The script records what the workbook says. It cannot verify who filled it in; the signed record stays the evidence."""
import argparse,json,sys
from pathlib import Path
sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
from nlu.engine import ROOT,digest
from openpyxl import load_workbook

TEMPLATE_DECISIONS={'approve','revise','remove'}
VIEW_DECISIONS={'keep','revise','remove'}
REVIEWER_FIELDS=['성명','역할·자격','소속','검토일','서명기록참조']

def text(v):
    return '' if v is None else str(v).strip()

def read(path,templates_path,queries_path):
    wb=load_workbook(path,data_only=True)
    info={text(r[0]):text(r[1]) for r in wb['안내'].iter_rows(min_row=2,values_only=True)}
    if info.get('templates_sha256')!=digest(templates_path) or info.get('template_queries_sha256')!=digest(queries_path):
        raise SystemExit('Workbook was made from different template files; create a fresh one with make_template_review_workbook.py')
    reviewer={text(r[0]):text(r[1]) for r in wb['검토자'].iter_rows(min_row=2,values_only=True)}
    trows=[[text(c) for c in r] for r in wb['템플릿'].iter_rows(min_row=2,values_only=True) if r and r[0]]
    vrows=[[text(c) for c in r] for r in wb['대표질문'].iter_rows(min_row=2,values_only=True) if r and r[0]]
    return reviewer,trows,vrows

def validate(reviewer,trows,vrows,templates,views):
    errors=[]
    missing=[f for f in REVIEWER_FIELDS if not reviewer.get(f)]
    if missing:errors.append('검토자 항목 누락: '+', '.join(missing))
    if [r[0] for r in trows]!=[t['template_id'] for t in templates]:errors.append('템플릿 시트의 ID 목록이 현재 DB와 다릅니다')
    expected_views=[f'{tid}-{i}' for tid,qs in views.items() for i in range(1,len(qs)+1)]
    if [r[0] for r in vrows]!=expected_views:errors.append('대표질문 시트의 ID 목록이 현재 DB와 다릅니다')
    for r in trows:
        tid,decision,revision,comment,law_date=r[0],r[6],r[7],r[8],r[9]
        if decision not in TEMPLATE_DECISIONS:errors.append(f'{tid}: 판정 누락 또는 잘못된 값 ({decision!r})')
        elif decision=='revise' and not revision:errors.append(f'{tid}: revise에는 수정안이 필요합니다')
        elif decision=='remove' and not comment:errors.append(f'{tid}: remove에는 사유(검토의견)가 필요합니다')
        if decision in ('approve','revise') and not law_date:errors.append(f'{tid}: 법령·기한 확인기준일이 필요합니다')
    for r in vrows:
        vid,decision,revision,comment=r[0],r[3],r[4],r[5]
        if decision not in VIEW_DECISIONS:errors.append(f'{vid}: 판정 누락 또는 잘못된 값 ({decision!r})')
        elif decision=='revise' and not revision:errors.append(f'{vid}: revise에는 수정안이 필요합니다')
        elif decision=='remove' and not comment:errors.append(f'{vid}: remove에는 사유(검토의견)가 필요합니다')
    return errors

def main(argv=None):
    p=argparse.ArgumentParser();p.add_argument('--workbook',required=True)
    p.add_argument('--templates',default=str(ROOT/'data/templates.json'));p.add_argument('--template-queries',default=str(ROOT/'data/template_queries.json'))
    p.add_argument('--write',action='store_true')
    a=p.parse_args(argv)
    tpath,qpath=Path(a.templates),Path(a.template_queries)
    templates=json.loads(tpath.read_text(encoding='utf-8'));qdoc=json.loads(qpath.read_text(encoding='utf-8'));views=qdoc['queries']
    reviewer,trows,vrows=read(a.workbook,tpath,qpath)
    errors=validate(reviewer,trows,vrows,templates,views)
    summary={'templates':{d:sum(r[6]==d for r in trows) for d in sorted(TEMPLATE_DECISIONS)},
        'views':{d:sum(r[3]==d for r in vrows) for d in sorted(VIEW_DECISIONS)},'errors':errors}
    changed=any(r[6]!='approve' for r in trows) or any(r[3]!='keep' for r in vrows)
    summary['result']='invalid' if errors else ('changes_requested' if changed else 'approved')
    if errors or not a.write:
        print(json.dumps(summary,ensure_ascii=False,indent=2));return 1 if errors else 0
    removed=[r[0] for r in trows if r[6]=='remove']
    if removed:
        summary['result']='manual_action_required'
        summary['message']='템플릿 삭제는 기대 템플릿 ID와 개발셋에 영향을 주므로 자동 반영하지 않습니다: '+', '.join(removed)
        print(json.dumps(summary,ensure_ascii=False,indent=2));return 2
    record={'reviewer_name':reviewer['성명'],'reviewer_role':reviewer['역할·자격'],'reviewer_org':reviewer['소속'],
        'review_date':reviewer['검토일'],'signed_record_reference':reviewer['서명기록참조'],'workbook':Path(a.workbook).name,'workbook_sha256':digest(Path(a.workbook))}
    byid={r[0]:r for r in trows}
    for t in templates:
        r=byid[t['template_id']]
        if r[6]=='revise':t['answer']=r[7];t['approval_status']='revised_pending_reconfirm'
        else:t['approval_status']='approved'
        t['expert_review']=dict(record,decision=r[6],comment=r[8],law_review_date=r[9])
    new_views={}
    vby={r[0]:r for r in vrows}
    for tid,qs in views.items():
        kept=[]
        for i,q in enumerate(qs,1):
            r=vby[f'{tid}-{i}']
            if r[3]=='keep':kept.append(q)
            elif r[3]=='revise':kept.append(r[4])
        if not kept:
            summary['result']='manual_action_required';summary['message']=f'{tid}의 대표질문이 모두 삭제됩니다. 최소 1개는 남겨야 합니다.'
            print(json.dumps(summary,ensure_ascii=False,indent=2));return 2
        new_views[tid]=kept
    qdoc['queries']=new_views
    qdoc['status']='revised_pending_reconfirm' if changed else 'approved'
    qdoc['expert_review']=dict(record,view_decisions={r[0]:{'decision':r[3],'comment':r[5]} for r in vrows if r[3]!='keep'})
    tpath.write_text(json.dumps(templates,ensure_ascii=False,indent=2)+'\n',encoding='utf-8')
    qpath.write_text(json.dumps(qdoc,ensure_ascii=False,indent=2)+'\n',encoding='utf-8')
    summary.update(templates_sha256=digest(tpath),template_queries_sha256=digest(qpath))
    if changed:summary['next']='수정 사항이 반영됐습니다. 개발셋 튜닝(nlu.cli tune)을 다시 하고, 새 검토 워크북으로 수정 사항이 없는 확인 검토를 한 번 더 받으세요.'
    else:summary['next']='전체 승인됐습니다. approval_hashes.py로 승인서 초안을 다시 만드세요.'
    print(json.dumps(summary,ensure_ascii=False,indent=2));return 0

if __name__=='__main__':sys.exit(main())
