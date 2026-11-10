"""Create the expert review workbook for the template DB (30 templates + their representative questions).
The reviewer marks every template approve/revise/remove and every representative question keep/revise/remove.
The workbook carries the current file hashes so that apply_template_review.py can refuse a stale review."""
import argparse,json,sys
from pathlib import Path
sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
from nlu.engine import ROOT,digest
from openpyxl import Workbook
from openpyxl.styles import Font,PatternFill,Alignment
from openpyxl.worksheet.datavalidation import DataValidation

TEMPLATE_HEADER=['template_id','유형','대표질문','응답원문','근거(source_id: PDF 페이지)','금지 단정 표현',
    '판정(approve/revise/remove)','수정안(응답원문 전체)','검토의견','법령·기한 확인기준일']
VIEW_HEADER=['view_id','template_id','추가 대표질문','판정(keep/revise/remove)','수정안(질문 전체)','검토의견']
REVIEWER_FIELDS=['성명','역할·자격','소속','검토일','서명기록참조']

def build(output):
    templates=json.loads((ROOT/'data/templates.json').read_text(encoding='utf-8'))
    views=json.loads((ROOT/'data/template_queries.json').read_text(encoding='utf-8'))['queries']
    sources=json.loads((ROOT/'data/source_excerpts.json').read_text(encoding='utf-8'))
    wb=Workbook();wb.remove(wb.active)
    info=wb.create_sheet('안내');info.append(['항목','값'])
    for row in [('자료구분','템플릿 DB 전문가 검토 입력용 (실무자·변리사·상담 경험자)'),
        ('templates_sha256',digest(ROOT/'data/templates.json')),
        ('template_queries_sha256',digest(ROOT/'data/template_queries.json')),
        ('검토대상',f'템플릿 {len(templates)}개, 추가 대표질문 {sum(len(v) for v in views.values())}개'),
        ('템플릿 판정','approve: 원문 그대로 고객 답변으로 사용 가능 / revise: 수정안에 고친 원문 전체를 적음 / remove: 템플릿 DB에서 제외(검토의견에 사유)'),
        ('대표질문 판정','keep: 해당 템플릿으로 답해야 하는 질문이 맞음 / revise: 수정안에 고친 질문 / remove: 다른 템플릿에 해당하거나 부적절(검토의견에 사유)'),
        ('확인 기준','근거 페이지와 최신 법령·기한·수수료를 대조하고, 금지 단정 표현(등록 보장, 확인되지 않은 기한·금액 등)이 없는지 확인'),
        ('주의','시험 질의(실제 고객 질의 100건)를 보고 템플릿을 고치지 않습니다. 이 검토는 시험 질의 확정 전에 끝냅니다.'),
        ('반영','python scripts/apply_template_review.py --workbook <이 파일> (확인만) → 문제 없으면 --write 로 반영')]:info.append(row)
    ws=wb.create_sheet('템플릿');ws.append(TEMPLATE_HEADER)
    for t in templates:
        refs='; '.join(f"{sid}: {','.join(str(p) for p in sources[sid]['pdf_pages'])}" for sid in t['source_ids'])
        ws.append([t['template_id'],t['category'],t['representative_query'],t['answer'],refs,', '.join(t.get('must_not_claim',[])),'','','',''])
    dv=DataValidation(type='list',formula1='"approve,revise,remove"',allow_blank=True);dv.showErrorMessage=True
    ws.add_data_validation(dv);dv.add(f'G2:G{len(templates)+1}')
    vs=wb.create_sheet('대표질문');vs.append(VIEW_HEADER)
    count=0
    for tid,qs in views.items():
        for i,q in enumerate(qs,1):vs.append([f'{tid}-{i}',tid,q,'','','']);count+=1
    dv2=DataValidation(type='list',formula1='"keep,revise,remove"',allow_blank=True);dv2.showErrorMessage=True
    vs.add_data_validation(dv2);dv2.add(f'D2:D{count+1}')
    rv=wb.create_sheet('검토자');rv.append(['항목','값'])
    for f in REVIEWER_FIELDS:rv.append([f,''])
    widths={'안내':{'A':22,'B':110},'템플릿':{'A':11,'B':12,'C':40,'D':80,'E':24,'F':26,'G':16,'H':70,'I':40,'J':16},
        '대표질문':{'A':10,'B':11,'C':60,'D':16,'E':50,'F':40},'검토자':{'A':16,'B':50}}
    for sheet in wb:
        sheet.freeze_panes='A2'
        for cell in sheet[1]:
            cell.font=Font(bold=True,color='FFFFFF');cell.fill=PatternFill('solid',fgColor='25476A')
        for row in sheet.iter_rows(min_row=2):
            for cell in row:cell.alignment=Alignment(wrap_text=True,vertical='top')
        for col,w in widths[sheet.title].items():sheet.column_dimensions[col].width=w
    for i in range(2,len(templates)+2):ws.row_dimensions[i].height=110
    output=Path(output);output.parent.mkdir(parents=True,exist_ok=True);wb.save(output)
    return {'output':str(output),'templates':len(templates),'views':count}

if __name__=='__main__':
    p=argparse.ArgumentParser();p.add_argument('--output',default=str(ROOT/'artifacts/review_package/템플릿DB_전문가검토.xlsx'))
    print(json.dumps(build(p.parse_args().output),ensure_ascii=False))
