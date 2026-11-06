"""Combine independent manual XLSX ratings; verify run binding and preserve reasons."""
import argparse,csv,json,sys
from pathlib import Path
sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
from nlu.engine import digest
from openpyxl import load_workbook
p=argparse.ArgumentParser();p.add_argument('--run-dir',required=True);p.add_argument('--a',required=True);p.add_argument('--b',required=True);p.add_argument('--resolution');p.add_argument('--output',required=True)
a=p.parse_args();run=Path(a.run_dir);m=json.loads((run/'manifest.json').read_text(encoding='utf-8'));rs=json.loads((run/'recommendations.json').read_text(encoding='utf-8'));byid={r['case_id']:r for r in rs}
if digest(run/'recommendations.json')!=m['recommendations_sha256']:raise ValueError('Tampered results')
def read(path):
    wb=load_workbook(path,data_only=True);metadata=dict(wb['안내'].values)
    if metadata['실행ID']!=m['run_id'] or metadata['추천파일SHA256']!=m['recommendations_sha256']:raise ValueError('Wrong run workbook')
    data={}
    for row in list(wb['평가'].values)[1:]:
        cid=row[0]
        if cid not in byid or cid in data:raise ValueError('Unexpected or duplicate ID')
        if row[1]!=byid[cid]['query'] or row[2]!=byid[cid]['recommended_answer']:raise ValueError('Query or response modified after run')
        if row[9] not in ['success','failure']:raise ValueError('Missing/invalid rating at '+cid)
        if not all(isinstance(x,int) and 1<=x<=5 for x in row[4:9]):raise ValueError('All five questionnaire ratings required')
        if not all(str(x or '').strip() for x in row[10:14]):raise ValueError('Reason, name, role and date required')
        data[cid]=row
    if set(data)!=set(byid):raise ValueError('Exactly 100 cases required')
    return data
ra=read(a.a);rb=read(a.b);res={}
if a.resolution:
    with open(a.resolution,encoding='utf-8-sig',newline='') as f:
        for row in csv.DictReader(f):
            if row['case_id'] in res or row['case_id'] not in byid:raise ValueError('Invalid resolution ID')
            if row.get('final') and not all(row.get(k,'').strip() for k in ['resolution_reason','resolution_date','participants']):raise ValueError('Resolution reason, date and participants required')
            res[row['case_id']]=row
rows=[]
for cid in byid:
    x=ra[cid];y=rb[cid];r=res.get(cid,{})
    if x[11]==y[11]:raise ValueError('Independent A and B must be different people')
    rows.append({'case_id':cid,'evidence_kind':'recorded_manual','a':x[9],'b':y[9],
        'final':r.get('final',''),'resolution_reason':r.get('resolution_reason',''),
        'resolution_date':r.get('resolution_date',''),'resolution_participants':r.get('participants',''),
        'a_reason':x[10],'b_reason':y[10],'a_1to5':x[7],'b_1to5':y[7],
        **{f'a_{k}':x[j+4] for j,k in enumerate(['context','correctness','completeness','usability','safety'])},
        **{f'b_{k}':y[j+4] for j,k in enumerate(['context','correctness','completeness','usability','safety'])},
        'a_name':x[11],'b_name':y[11],'a_role':x[12],'b_role':y[12],'a_date':x[13],'b_date':y[13]})
with open(a.output,'w',encoding='utf-8-sig',newline='') as f:
    w=csv.DictWriter(f,fieldnames=list(rows[0]));w.writeheader();w.writerows(rows)
print('Saved 100 recorded ratings. This does not verify signatures or professional qualifications.')
