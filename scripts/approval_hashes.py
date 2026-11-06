"""Print the current hashes an approver signs off on and optionally write an approval draft.
Human fields (name, role, date, signature reference, agency references) stay empty on purpose."""
import argparse,json,sys
from pathlib import Path
sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
from nlu.engine import ROOT,DEFAULT_MODEL,PROFILES,digest
p=argparse.ArgumentParser();p.add_argument('--questions',default='data/questions_100.json')
p.add_argument('--model-id',default=DEFAULT_MODEL);p.add_argument('--decision-rule',choices=['consensus','majority'],default='consensus')
p.add_argument('--output',help='write a draft (e.g. data/approval.draft.json); never overwrites')
a=p.parse_args();q=Path(a.questions);q=q if q.is_absolute() else ROOT/q
draft={'reviewer_name':'','reviewer_role':'','approval_date':'','signed_record_reference':'','current_law_review_date':'',
    'questions_path':q.relative_to(ROOT).as_posix() if q.is_relative_to(ROOT) else str(q),
    'questions_sha256':digest(q),'templates_sha256':digest(ROOT/'data/templates.json'),
    'template_queries_sha256':digest(ROOT/'data/template_queries.json'),
    'retrieval_config_sha256':digest(ROOT/'data/retrieval_config.json'),
    'model_id':a.model_id,'model_revision':PROFILES['models'].get(a.model_id,{}).get('revision',''),
    'approved_recommendation_mode':'template_direct','approved_decision_rule':a.decision_rule,
    'sampling_and_holdout_approval':'pending','agency_model_acceptance_reference':'','sampling_approval_reference':'',
    'note':'Draft only. Fill the empty fields from actual signed records, then save as data/approval.json.'}
if a.output:
    out=Path(a.output);out=out if out.is_absolute() else ROOT/out
    if out.exists():raise SystemExit(f'{out} exists; not overwriting')
    out.write_text(json.dumps(draft,ensure_ascii=False,indent=2)+'\n',encoding='utf-8')
print(json.dumps(draft,ensure_ascii=False,indent=2))
