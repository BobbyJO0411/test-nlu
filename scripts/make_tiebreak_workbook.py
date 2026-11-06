"""Create the blinded third-rater (C) workbook containing only A/B disagreements (다수결 절차).
C sees the query, the recommended answer and source pages, never the A/B judgments or reasons."""
import argparse,json,sys
from pathlib import Path
sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
from nlu.engine import digest
from openpyxl import Workbook,load_workbook
from openpyxl.worksheet.datavalidation import DataValidation
p=argparse.ArgumentParser();p.add_argument('--run-dir',required=True);p.add_argument('--a',required=True);p.add_argument('--b',required=True)
p.add_argument('--output',required=True)
a=p.parse_args();run=Path(a.run_dir);m=json.loads((run/'manifest.json').read_text(encoding='utf-8'))
if digest(run/'recommendations.json')!=m['recommendations_sha256']:raise ValueError('Tampered results')
def votes(path):
    wb=load_workbook(path,data_only=True);meta=dict(wb['안내'].values)
    if meta['실행ID']!=m['run_id'] or meta['추천파일SHA256']!=m['recommendations_sha256']:raise ValueError('Wrong run workbook')
    rows=list(wb['평가'].values)
    out={r[0]:r for r in rows[1:]}
    if any(r[9] not in ['success','failure'] for r in out.values()):raise ValueError('A and B must finish all 100 cases first')
    return rows[0],out
header,ra=votes(a.a);_,rb=votes(a.b)
ids=[cid for cid in ra if ra[cid][9]!=rb[cid][9]]
wb=Workbook();wb.remove(wb.active)
info=wb.create_sheet('안내');info.append(['항목','값'])
for row in [('자료구분','제3평가자 C 실평가 입력용 — A/B 불일치 건만 포함'),('실행ID',m['run_id']),('추천파일SHA256',m['recommendations_sha256']),
    ('백엔드',m['engine']['backend']),('대상건수',len(ids)),
    ('평가절차','A·B의 판정과 근거는 제공하지 않습니다. 동일한 성공 기준으로 독립 판정합니다.'),
    ('성공기준','다섯 기준 모두 충족하고 수정 없이 바로 사용할 수 있을 때 success. 그 외 failure.'),
    ('결정규칙','다수결: A·B·C 세 판정 중 다수(= C의 판정)가 최종 판정입니다.')]:info.append(row)
info.column_dimensions['B'].width=100
ws=wb.create_sheet('평가');ws.append(list(header))
for cid in ids:ws.append(list(ra[cid][:4])+['']*10)
dv=DataValidation(type='list',formula1='"success,failure"');dv.showErrorMessage=True;ws.add_data_validation(dv);dv.add(f'J2:J{len(ids)+1}')
sc=DataValidation(type='whole',operator='between',formula1=1,formula2=5);sc.showErrorMessage=True;ws.add_data_validation(sc);sc.add(f'E2:I{len(ids)+1}')
ws.column_dimensions['B'].width=60;ws.column_dimensions['C'].width=100
wb.save(a.output)
print(json.dumps({'output':a.output,'disagreements':len(ids),'case_ids':ids},ensure_ascii=False))
