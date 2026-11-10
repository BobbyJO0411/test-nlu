import argparse,csv,json,platform,subprocess,sys,uuid
from datetime import datetime,timezone
from pathlib import Path
import numpy as np
from .engine import ROOT,Recommender,digest,DEFAULT_MODEL,STRATEGIES
from .metrics import summarize,DECISION_RULES

DEFAULT_QUESTIONS='data/questions_100.json'
SURVEY=['context','correctness','completeness','usability','safety']

def write(path,obj):
    Path(path).write_text(json.dumps(obj,ensure_ascii=False,indent=2)+'\n',encoding='utf-8')

def resolve(path):
    path=Path(path);return path if path.is_absolute() else ROOT/path

def rel(path):
    path=Path(path).resolve()
    try:return path.relative_to(ROOT).as_posix()
    except ValueError:return str(path)

def questions_for(manifest):
    path=resolve(manifest.get('questions_path',DEFAULT_QUESTIONS))
    return path,json.loads(path.read_text(encoding='utf-8'))

def engine_from(args):
    return Recommender(args.backend,args.model_id,args.revision,args.model_path,
        getattr(args,'strategy',None),getattr(args,'alpha',None),getattr(args,'beta',None))

def run(args):
    engine=engine_from(args)
    # Reference labels are used only after recommendation, for separate retrieval diagnostics.
    qpath=resolve(args.questions);questions=json.loads(qpath.read_text(encoding='utf-8'))
    run_id=datetime.now(timezone.utc).strftime('%Y%m%dT%H%M%SZ')+'-'+uuid.uuid4().hex[:8]
    out=Path(args.output)/run_id;out.mkdir(parents=True,exist_ok=False)
    results=[]
    for case in questions:
        result=engine.recommend(case['query'])
        if args.mode=='llm_select':
            from .llm import select
            result=select(case['query'],result,args.llm_model)
        result['case_id']=case['case_id']
        results.append(result)
    write(out/'recommendations.json',results)
    labelled=[q for q in questions if q.get('expected_template_ids')]
    top1=sum(r['selected_template_id'] in q['expected_template_ids'] for r,q in zip(results,questions) if q.get('expected_template_ids'))
    top3=sum(any(c['template_id'] in q['expected_template_ids'] for c in r['candidates']) for r,q in zip(results,questions) if q.get('expected_template_ids'))
    git=subprocess.run(['git','rev-parse','HEAD'],cwd=ROOT,capture_output=True,text=True)
    dirty=subprocess.run(['git','status','--porcelain'],cwd=ROOT,capture_output=True,text=True)
    write(out/'manifest.json',{'run_id':run_id,'created_utc':datetime.now(timezone.utc).isoformat(),
        'git_commit':git.stdout.strip() if git.returncode==0 else None,
        'git_worktree_clean':(dirty.stdout.strip()=='') if dirty.returncode==0 else None,
        'code_files_sha256':{f.relative_to(ROOT).as_posix():digest(f) for f in sorted((ROOT/'nlu').glob('*.py'))},
        'python':sys.version,'platform':platform.platform(),'engine':engine.metadata,
        'questions_path':rel(qpath),'questions_sha256':digest(qpath),
        'source_manifest_sha256':digest(ROOT/'data/source_manifest.json'),
        'recommendations_sha256':digest(out/'recommendations.json'),
        'case_count':len(results),'human_evaluation':'not_performed','gold_approval':'pending',
        'dataset_type':args.dataset_type,'status':'development_run',
        'llm_used':args.mode=='llm_select','recommendation_mode':args.mode,'failures_policy':'No fallback or substituted recommendations',
        'retrieval_diagnostic':{'top1_count':top1,'top3_count':top3,'labelled':len(labelled),'total':len(results),
            'note':'Expected-template recall is not human response suitability'},
        'dependencies':subprocess.run([sys.executable,'-m','pip','freeze'],capture_output=True,text=True,check=True).stdout.splitlines()})
    fields=['case_id','evidence_kind','a','b','c','final','resolution_reason','resolution_date','resolution_participants',
        'a_reason','b_reason','c_reason','a_1to5','b_1to5','a_name','b_name','c_name','a_role','b_role','c_role','a_date','b_date','c_date',
        *['%s_%s'%(r,k) for r in ['a','b'] for k in SURVEY]]
    with (out/'ratings_blank.csv').open('w',encoding='utf-8-sig',newline='') as f:
        writer=csv.DictWriter(f,fieldnames=fields);writer.writeheader()
        writer.writerows({'case_id':q['case_id']} for q in questions)
    print(json.dumps({'run_dir':str(out),'retrieval_top1':top1,'retrieval_top3':top3,
        'total':len(results),'human_suitability':'pending'},ensure_ascii=False))

def ranks(scores,expected,order_ids):
    order=np.argsort(-scores,kind='stable');ids=[order_ids[i] for i in order]
    return min(ids.index(t) for t in expected)+1

def tune(args):
    """Select retrieval weights on the development set only. Never reads the evaluation questions."""
    engine=engine_from(args)
    dev=json.loads(resolve(args.dev).read_text(encoding='utf-8'))
    ids=[t['template_id'] for t in engine.templates]
    parts=[engine.component_scores(d['query']) for d in dev]
    def measure(strategy,alpha,beta):
        rk=[ranks(engine.combine(p,strategy,alpha,beta),d['expected_template_ids'],ids) for p,d in zip(parts,dev)]
        return {'strategy':strategy,'alpha':alpha,'beta':beta,'top1':sum(r==1 for r in rk),'top3':sum(r<=3 for r in rk),
            'mrr':round(sum(1/r for r in rk)/len(rk),6),'total':len(rk)}
    grid=[measure('passage_only',0.0,0.0)]
    grid+=[measure('multiview_hybrid',a,b) for a in [0.0,0.25,0.5,0.75,1.0] for b in [0.0,0.1,0.2,0.3]]
    best=max(grid,key=lambda g:(g['top1'],g['top3'],g['mrr']))
    key=engine.metadata['model_id'] if engine.backend=='e5' else 'baseline'
    report={'model_id':key,'revision':engine.metadata.get('revision'),'dev_path':rel(resolve(args.dev)),
        'dev_sha256':digest(resolve(args.dev)),'template_queries_sha256':engine.metadata['template_queries_sha256'],
        'grid':grid,'selected':best,'created_utc':datetime.now(timezone.utc).isoformat(),
        'note':'Development tuning only; evaluation questions were not loaded.'}
    if args.report:write(args.report,report)
    if args.write_config:
        path=ROOT/'data/retrieval_config.json';config=json.loads(path.read_text(encoding='utf-8'))
        config['settings'][key]={'strategy':best['strategy'],'alpha':best['alpha'],'beta':best['beta'],
            'dev_top1':best['top1'],'dev_top3':best['top3'],'dev_total':best['total']}
        config['status']='tuned_on_development_set'
        write(path,config)
    print(json.dumps({'model_id':key,'passage_only':grid[0],'selected':best},ensure_ascii=False))

def score(args):
    run_dir=Path(args.run_dir);manifest=json.loads((run_dir/'manifest.json').read_text(encoding='utf-8'))
    if digest(run_dir/'recommendations.json')!=manifest['recommendations_sha256']:
        raise ValueError('Recommendation file changed after execution')
    qpath,questions=questions_for(manifest)
    if digest(qpath)!=manifest['questions_sha256']:
        raise ValueError('Dataset changed after execution')
    with Path(args.ratings).open(encoding='utf-8-sig',newline='') as f:rows=list(csv.DictReader(f))
    ids=[q['case_id'] for q in questions]
    result=summarize(rows,ids,args.decision_rule)
    approval_path=ROOT/'data/approval.json'
    approval=json.loads(approval_path.read_text(encoding='utf-8')) if approval_path.exists() else {}
    tq=manifest['engine'].get('template_queries_sha256')
    approved=approval.get('questions_sha256')==manifest['questions_sha256'] and approval.get('templates_sha256')==manifest['engine']['templates_sha256'] and (tq is None or approval.get('template_queries_sha256')==tq) and bool(approval.get('reviewer_name')) and bool(approval.get('approval_date')) and bool(approval.get('signed_record_reference')) and bool(approval.get('reviewer_role'))
    current_templates=json.loads((ROOT/'data/templates.json').read_text(encoding='utf-8'))
    current_views=json.loads((ROOT/'data/template_queries.json').read_text(encoding='utf-8'))
    template_items_approved=digest(ROOT/'data/templates.json')==manifest['engine']['templates_sha256'] and all(t.get('approval_status')=='approved' for t in current_templates) and (tq is None or (digest(ROOT/'data/template_queries.json')==tq and current_views.get('status')=='approved'))
    identities=all(all(r.get(k,'').strip() for k in ['a_name','b_name','a_role','b_role','a_date','b_date','a_reason','b_reason']) and r['a_name']!=r['b_name'] and all(r.get(k) in ['1','2','3','4','5'] for k in ['a_1to5','b_1to5']) for r in rows)
    third=[r for r in rows if r.get('c')]
    if third:
        identities=identities and all(all(r.get(k,'').strip() for k in ['c_name','c_role','c_date','c_reason']) and r['c_name'] not in (r['a_name'],r['b_name']) for r in third)
    actual_engine=manifest['engine']['backend']=='e5'
    manual=all(r.get('evidence_kind')=='recorded_manual' for r in rows)
    survey={}
    full_survey=True
    for person in ['a','b']:
        for dimension in SURVEY:
            key=person+'_'+dimension
            values=[r.get(key,'') for r in rows]
            if not all(v in ['1','2','3','4','5'] for v in values):
                full_survey=False
                continue
            numbers=list(map(int,values))
            survey[key]={'count':len(numbers),'mean':sum(numbers)/len(numbers),
                'distribution':{str(i):numbers.count(i) for i in range(1,6)}}
    if args.decision_rule=='majority':
        resolved_records=all(r['a']==r['b'] or r.get('c') in ['success','failure'] for r in rows)
    else:
        resolved_records=all(r['a']==r['b'] or all(r.get(k,'').strip() for k in ['resolution_date','resolution_participants']) for r in rows)
    agency_approved=bool(approval.get('agency_model_acceptance_reference')) and bool(approval.get('sampling_approval_reference')) and approval.get('model_id')==manifest['engine']['model_id'] and approval.get('approved_recommendation_mode')==manifest.get('recommendation_mode') and approval.get('approved_decision_rule',args.decision_rule)==args.decision_rule
    result.update(run_id=manifest['run_id'],ratings_sha256=digest(args.ratings),
        expert_approval_record_present=approved,template_items_approved=template_items_approved,evaluator_records_complete=identities,
        embedding_backend=actual_engine,recorded_manual_provenance=manual,
        questionnaire_complete=full_survey,questionnaire_statistics=survey,
        resolution_records_complete=resolved_records,agency_approval_record_present=agency_approved,
        submission_candidate=result['status']=='complete' and approved and template_items_approved and identities and actual_engine and manual and full_survey and resolved_records and agency_approved,
        note='Computes recorded judgments only; cannot authenticate identities, credentials or actual review. Agency approval and signatures remain necessary.')
    write(Path(args.output),result);print(json.dumps(result,ensure_ascii=False))

def add_engine_args(parser):
    parser.add_argument('--backend',choices=['e5','baseline'],default='e5')
    parser.add_argument('--model-id',default=DEFAULT_MODEL);parser.add_argument('--revision');parser.add_argument('--model-path')
    parser.add_argument('--strategy',choices=STRATEGIES);parser.add_argument('--alpha',type=float);parser.add_argument('--beta',type=float)

def main():
    p=argparse.ArgumentParser();sub=p.add_subparsers(dest='command',required=True)
    r=sub.add_parser('run');add_engine_args(r)
    r.add_argument('--questions',default=DEFAULT_QUESTIONS)
    r.add_argument('--dataset-type',default='jointly_authored_synthetic_draft')
    r.add_argument('--mode',choices=['template_direct','llm_select'],default='template_direct');r.add_argument('--llm-model',default='gpt-4.1-mini')
    r.add_argument('--output',default=str(ROOT/'artifacts/runs'));r.set_defaults(func=run)
    t=sub.add_parser('tune');add_engine_args(t)
    t.add_argument('--dev',default='data/dev_queries.json');t.add_argument('--report');t.add_argument('--write-config',action='store_true')
    t.set_defaults(func=tune)
    s=sub.add_parser('score');s.add_argument('--run-dir',required=True);s.add_argument('--ratings',required=True)
    s.add_argument('--decision-rule',choices=DECISION_RULES,default='consensus')
    s.add_argument('--output',required=True);s.set_defaults(func=score)
    args=p.parse_args();args.func(args)
if __name__=='__main__':main()
