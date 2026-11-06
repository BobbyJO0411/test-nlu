import argparse,csv,json,platform,subprocess,sys,uuid
from datetime import datetime,timezone
from pathlib import Path
from .engine import ROOT,Recommender,digest,DEFAULT_MODEL
from .metrics import summarize

def write(path,obj):
    path.write_text(json.dumps(obj,ensure_ascii=False,indent=2)+'\n')

def run(args):
    engine=Recommender(args.backend,args.model_id,args.revision,args.model_path)
    # Reference labels are used only after recommendation, for separate retrieval diagnostics.
    questions=json.loads((ROOT/'data/questions_100.json').read_text(encoding='utf-8'))
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
    top1=sum(r['selected_template_id'] in q['expected_template_ids'] for r,q in zip(results,questions))
    top3=sum(any(c['template_id'] in q['expected_template_ids'] for c in r['candidates']) for r,q in zip(results,questions))
    git=subprocess.run(['git','rev-parse','HEAD'],cwd=ROOT,capture_output=True,text=True)
    write(out/'manifest.json',{'run_id':run_id,'created_utc':datetime.now(timezone.utc).isoformat(),
        'git_commit':git.stdout.strip() if git.returncode==0 else None,
        'code_files_sha256':{str(f.relative_to(ROOT)):digest(f) for f in (ROOT/'nlu').glob('*.py')},
        'python':sys.version,'platform':platform.platform(),'engine':engine.metadata,
        'questions_sha256':digest(ROOT/'data/questions_100.json'),
        'source_manifest_sha256':digest(ROOT/'data/source_manifest.json'),
        'recommendations_sha256':digest(out/'recommendations.json'),
        'case_count':len(results),'human_evaluation':'not_performed','gold_approval':'pending',
        'dataset_type':'jointly_authored_synthetic_draft','status':'development_run',
        'llm_used':args.mode=='llm_select','recommendation_mode':args.mode,'failures_policy':'No fallback or substituted recommendations',
        'retrieval_diagnostic':{'top1_count':top1,'top3_count':top3,'total':len(results),
            'note':'Expected-template recall is not human response suitability'},
        'dependencies':subprocess.run([sys.executable,'-m','pip','freeze'],capture_output=True,text=True,check=True).stdout.splitlines()})
    fields=['case_id','evidence_kind','a','b','final','resolution_reason','resolution_date','resolution_participants','a_reason','b_reason','a_1to5','b_1to5','a_name','b_name','a_role','b_role','a_date','b_date',*['%s_%s'%(r,k) for r in ['a','b'] for k in ['context','correctness','completeness','usability','safety']]]
    with (out/'ratings_blank.csv').open('w',encoding='utf-8-sig',newline='') as f:
        writer=csv.DictWriter(f,fieldnames=fields);writer.writeheader()
        writer.writerows({'case_id':q['case_id']} for q in questions)
    print(json.dumps({'run_dir':str(out),'retrieval_top1':top1,'retrieval_top3':top3,
        'total':100,'human_suitability':'pending'},ensure_ascii=False))

def score(args):
    run_dir=Path(args.run_dir);manifest=json.loads((run_dir/'manifest.json').read_text(encoding='utf-8'))
    if digest(run_dir/'recommendations.json')!=manifest['recommendations_sha256']:
        raise ValueError('Recommendation file changed after execution')
    if digest(ROOT/'data/questions_100.json')!=manifest['questions_sha256']:
        raise ValueError('Dataset changed after execution')
    with Path(args.ratings).open(encoding='utf-8-sig',newline='') as f:rows=list(csv.DictReader(f))
    ids=[q['case_id'] for q in json.loads((ROOT/'data/questions_100.json').read_text(encoding='utf-8'))]
    result=summarize(rows,ids)
    approval_path=ROOT/'data/approval.json'
    approval=json.loads(approval_path.read_text(encoding='utf-8')) if approval_path.exists() else {}
    approved=approval.get('questions_sha256')==manifest['questions_sha256'] and approval.get('templates_sha256')==manifest['engine']['templates_sha256'] and bool(approval.get('reviewer_name')) and bool(approval.get('approval_date')) and bool(approval.get('signed_record_reference')) and bool(approval.get('reviewer_role'))
    identities=all(all(r.get(k,'').strip() for k in ['a_name','b_name','a_role','b_role','a_date','b_date','a_reason','b_reason']) and r['a_name']!=r['b_name'] and all(r.get(k) in ['1','2','3','4','5'] for k in ['a_1to5','b_1to5']) for r in rows)
    actual_engine=manifest['engine']['backend']=='e5'
    manual=all(r.get('evidence_kind')=='recorded_manual' for r in rows)
    survey={}
    full_survey=True
    for person in ['a','b']:
        for dimension in ['context','correctness','completeness','usability','safety']:
            key=person+'_'+dimension
            values=[r.get(key,'') for r in rows]
            if not all(v in ['1','2','3','4','5'] for v in values):
                full_survey=False
                continue
            numbers=list(map(int,values))
            survey[key]={'count':len(numbers),'mean':sum(numbers)/len(numbers),
                'distribution':{str(i):numbers.count(i) for i in range(1,6)}}
    resolved_records=all(r['a']==r['b'] or all(r.get(k,'').strip() for k in ['resolution_date','resolution_participants']) for r in rows)
    agency_approved=bool(approval.get('agency_model_acceptance_reference')) and bool(approval.get('sampling_approval_reference')) and approval.get('model_id')==manifest['engine']['model_id'] and approval.get('approved_recommendation_mode')==manifest.get('recommendation_mode')
    result.update(run_id=manifest['run_id'],ratings_sha256=digest(args.ratings),
        expert_approval_record_present=approved,evaluator_records_complete=identities,
        embedding_backend=actual_engine,recorded_manual_provenance=manual,
        questionnaire_complete=full_survey,questionnaire_statistics=survey,
        resolution_records_complete=resolved_records,agency_approval_record_present=agency_approved,
        submission_candidate=result['status']=='complete' and approved and identities and actual_engine and manual and full_survey and resolved_records and agency_approved,
        note='Computes recorded judgments only; cannot authenticate identities, credentials or actual review. Agency approval and signatures remain necessary.')
    write(Path(args.output),result);print(json.dumps(result,ensure_ascii=False))

def main():
    p=argparse.ArgumentParser();sub=p.add_subparsers(dest='command',required=True)
    r=sub.add_parser('run');r.add_argument('--backend',choices=['e5','baseline'],default='e5')
    r.add_argument('--model-id',default=DEFAULT_MODEL);r.add_argument('--revision');r.add_argument('--model-path')
    r.add_argument('--mode',choices=['template_direct','llm_select'],default='template_direct');r.add_argument('--llm-model',default='gpt-4.1-mini')
    r.add_argument('--output',default=str(ROOT/'artifacts/runs'));r.set_defaults(func=run)
    s=sub.add_parser('score');s.add_argument('--run-dir',required=True);s.add_argument('--ratings',required=True)
    s.add_argument('--output',required=True);s.set_defaults(func=score)
    args=p.parse_args();args.func(args)
if __name__=='__main__':main()
