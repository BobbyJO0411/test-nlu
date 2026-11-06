from __future__ import annotations
import math

def wilson(success,total):
    if not total:return None
    z=1.959963984540054;p=success/total;d=1+z*z/total
    c=(p+z*z/(2*total))/d; h=z*math.sqrt(p*(1-p)/total+z*z/(4*total*total))/d
    return [round(100*(c-h),3),round(100*(c+h),3)]

def summarize(rows,expected_ids):
    ids=[r['case_id'] for r in rows]
    if len(ids)!=len(set(ids)) or set(ids)!=set(expected_ids):
        raise ValueError('Exactly the frozen 100 unique case IDs are required')
    count=len(rows);valid={'success','failure'}
    if count!=100:raise ValueError('Protocol requires 100 cases')
    ready=all(r.get('a') in valid and r.get('b') in valid for r in rows)
    if not ready:
        return {'status':'incomplete','total':count,'suitability_pct':None,'agreement_pct':None}
    agreements=sum(r['a']==r['b'] for r in rows)
    finals=[];unresolved=[]
    for row in rows:
        if row['a']==row['b']:
            if row.get('final') and row['final']!=row['a']:
                raise ValueError('An agreeing pair must retain its common decision')
            finals.append(row['a'])
        elif row.get('final') in valid and row.get('resolution_reason','').strip():
            finals.append(row['final'])
        else:unresolved.append(row['case_id'])
    result={'status':'complete' if not unresolved else 'unresolved_disagreements',
        'total':count,'initial_agreements':agreements,'initial_disagreements':count-agreements,
        'agreement_pct':agreements/count*100,'unresolved_ids':unresolved,
        'suitability_pct':None,'success_count':None,'failure_count':None}
    if not unresolved:
        successes=finals.count('success')
        pa=agreements/count; p_a=sum(r['a']=='success' for r in rows)/count
        p_b=sum(r['b']=='success' for r in rows)/count
        pe=p_a*p_b+(1-p_a)*(1-p_b)
        result.update(success_count=successes,failure_count=count-successes,
            suitability_pct=successes/count*100,cohen_kappa=None if pe==1 else round((pa-pe)/(1-pe),6),
            wilson_95_pct=wilson(successes,count))
    return result
