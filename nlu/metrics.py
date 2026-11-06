from __future__ import annotations
import math
VALID={'success','failure'}
DECISION_RULES=('consensus','majority')

def wilson(success,total):
    if not total:return None
    z=1.959963984540054;p=success/total;d=1+z*z/total
    c=(p+z*z/(2*total))/d; h=z*math.sqrt(p*(1-p)/total+z*z/(4*total*total))/d
    return [round(100*(c-h),3),round(100*(c+h),3)]

def iso_functional_correctness(failures,total):
    """ISO/IEC 25023 FCr-1-G form X = 1 - A/B (A: incorrect, B: considered).
    Numerically identical to the plan's suitability = successes/total*100."""
    x=1-failures/total
    return {'measure':'FCr-1-G Functional correctness','formula':'X = 1 - A/B',
        'A_incorrect_responses':failures,'B_responses_considered':total,'X':round(x,6),'X_pct':round(x*100,6),
        'equivalent_plan_formula':'suitability(%) = successes / total * 100',
        'note':'Clause/code mapping must be confirmed against the licensed standard text by the test agency'}

def fleiss_kappa(rows,raters):
    n=len(raters);N=len(rows)
    if n<2 or not N:return None
    p_success=sum(sum(r[k]=='success' for k in raters) for r in rows)/(N*n)
    pe=p_success**2+(1-p_success)**2
    pbar=sum((sum(r[k]=='success' for k in raters)**2+sum(r[k]=='failure' for k in raters)**2-n)/(n*(n-1)) for r in rows)/N
    return None if pe==1 else round((pbar-pe)/(1-pe),6)

def summarize(rows,expected_ids,decision_rule='consensus'):
    """A and B judge all cases independently. Disagreements are settled either by recorded consensus
    (협의) or by majority vote (다수결) with an independent third rater C on every disagreement."""
    if decision_rule not in DECISION_RULES:raise ValueError('decision_rule must be consensus or majority')
    ids=[r['case_id'] for r in rows]
    if len(ids)!=len(set(ids)) or set(ids)!=set(expected_ids):
        raise ValueError('Exactly the frozen 100 unique case IDs are required')
    count=len(rows)
    if count!=100:raise ValueError('Protocol requires 100 cases')
    ready=all(r.get('a') in VALID and r.get('b') in VALID for r in rows)
    if not ready:
        return {'status':'incomplete','total':count,'decision_rule':decision_rule,'suitability_pct':None,'agreement_pct':None}
    for r in rows:
        if r.get('c') and r['c'] not in VALID:raise ValueError('Invalid third-rater value at '+r['case_id'])
    agreements=sum(r['a']==r['b'] for r in rows)
    finals=[];unresolved=[];by_majority=0;by_consensus=0
    for row in rows:
        if row['a']==row['b']:
            if row.get('final') and row['final']!=row['a']:
                raise ValueError('An agreeing pair must retain its common decision')
            finals.append(row['a'])
        elif decision_rule=='majority':
            if row.get('c') in VALID:
                if row.get('final') and row['final']!=row['c']:
                    raise ValueError('Majority decision cannot be overridden at '+row['case_id'])
                finals.append(row['c']);by_majority+=1
            else:unresolved.append(row['case_id'])
        elif row.get('final') in VALID and row.get('resolution_reason','').strip():
            finals.append(row['final']);by_consensus+=1
        else:unresolved.append(row['case_id'])
    result={'status':'complete' if not unresolved else 'unresolved_disagreements',
        'total':count,'decision_rule':decision_rule,
        'initial_agreements':agreements,'initial_disagreements':count-agreements,
        'agreement_pct':agreements/count*100,'agreement_definition':'initial A=B count / total * 100 (before resolution)',
        'resolved_by_consensus':by_consensus,'resolved_by_majority':by_majority,'unresolved_ids':unresolved,
        'suitability_pct':None,'success_count':None,'failure_count':None,'iso_25023':None}
    if all(r.get('c') in VALID for r in rows):
        result.update(three_rater_unanimous_pct=sum(r['a']==r['b']==r['c'] for r in rows)/count*100,
            pairwise_agreement_pct={'a_b':agreements/count*100,
                'a_c':sum(r['a']==r['c'] for r in rows)/count*100,'b_c':sum(r['b']==r['c'] for r in rows)/count*100},
            fleiss_kappa=fleiss_kappa(rows,['a','b','c']))
    if not unresolved:
        successes=finals.count('success')
        pa=agreements/count; p_a=sum(r['a']=='success' for r in rows)/count
        p_b=sum(r['b']=='success' for r in rows)/count
        pe=p_a*p_b+(1-p_a)*(1-p_b)
        result.update(success_count=successes,failure_count=count-successes,
            suitability_pct=successes/count*100,cohen_kappa=None if pe==1 else round((pa-pe)/(1-pe),6),
            wilson_95_pct=wilson(successes,count),iso_25023=iso_functional_correctness(count-successes,count))
    return result
