"""Merge the expert annotation CSV (expected templates, reference answers, sources) into a holdout questions file.
Records who annotated; does not approve anything by itself."""
import argparse,csv,json,sys
from pathlib import Path
sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
from nlu.engine import ROOT
p=argparse.ArgumentParser();p.add_argument('--questions',required=True);p.add_argument('--annotations',required=True);p.add_argument('--output',required=True)
a=p.parse_args()
cases=json.loads(Path(a.questions).read_text(encoding='utf-8'))
tids={t['template_id'] for t in json.loads((ROOT/'data/templates.json').read_text(encoding='utf-8'))}
sources=json.loads((ROOT/'data/source_excerpts.json').read_text(encoding='utf-8'))
with open(a.annotations,encoding='utf-8-sig',newline='') as f:notes={r['case_id']:r for r in csv.DictReader(f)}
for c in cases:
    r=notes.get(c['case_id'])
    if not r:raise SystemExit('Missing annotation: '+c['case_id'])
    expected=[x.strip() for x in r['expected_template_ids(쉼표)'].split(',') if x.strip()]
    if not expected or not set(expected)<=tids:raise SystemExit('Invalid expected_template_ids at '+c['case_id'])
    src=[x.strip() for x in r['source_ids'].split(',') if x.strip()]
    if not set(src)<=set(sources):raise SystemExit('Unknown source id at '+c['case_id'])
    if not all(r[k].strip() for k in ['reference_answer','reviewer','review_date']):raise SystemExit('Reference answer, reviewer and date required at '+c['case_id'])
    c.update(expected_template_ids=expected,reference_answer=r['reference_answer'].strip(),source_ids=src,
        annotation={'reviewer':r['reviewer'].strip(),'review_date':r['review_date'].strip(),'comment':r.get('comment','').strip()})
Path(a.output).write_text(json.dumps(cases,ensure_ascii=False,indent=2)+'\n',encoding='utf-8')
print(json.dumps({'output':a.output,'cases':len(cases)},ensure_ascii=False))
