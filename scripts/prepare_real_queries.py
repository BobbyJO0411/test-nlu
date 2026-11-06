"""Turn an exported list of real customer questions into an anonymized 100-case holdout candidate.

Input: CSV (UTF-8/UTF-8-SIG) with a question column and optional category column.
Output: questions JSON in the evaluation format (labels left empty for expert annotation),
an annotation CSV and a sampling manifest. Raw input is never copied into the repository.
Masking is a first pass only: a person must still review every case before approval."""
import argparse,csv,hashlib,json,random,re,sys
from collections import Counter
from datetime import datetime,timezone
from pathlib import Path
sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
from nlu.engine import ROOT

PATTERNS=[
    ('[이메일]',re.compile(r'[\w.+-]+@[\w-]+(?:\.[\w-]+)+')),
    ('[URL]',re.compile(r'https?://\S+|www\.\S+')),
    ('[주민번호]',re.compile(r'\b\d{6}\s*-\s*[1-8]\d{6}\b')),
    ('[카드번호]',re.compile(r'\b(?:\d{4}[- ]?){3}\d{4}\b')),
    ('[출원번호]',re.compile(r'\b(?:40|41|45)\s*-\s*(?:19|20)\d{2}\s*-\s*\d{5,7}\b')),
    ('[등록번호]',re.compile(r'\b(?:40|41|45)\s*-\s*\d{7}\b')),
    ('[사업자번호]',re.compile(r'\b\d{3}\s*-\s*\d{2}\s*-\s*\d{5}\b')),
    ('[전화번호]',re.compile(r'(?:\+82[- ]?)?\b0\d{1,2}[- .)]?\d{3,4}[- .]?\d{4}\b')),
    ('[계좌번호]',re.compile(r'\b\d{2,6}-\d{2,6}-\d{2,8}\b')),
]
NAME_HINT=re.compile(r'[가-힣]{2,4}\s?(?:님|씨|고객님|대표님|변리사님)')
REQUIRED_CHECKS=['문맥과 의도 일치','핵심 절차·조건 누락 없음','원문 기준 및 최신 적용 규정과 모순 없음',
    '질문하지 않은 사실·확정 판단 생성 없음','추가 수정 없이 활용 가능']

def mask(text):
    hits=Counter()
    for label,pattern in PATTERNS:
        text,n=pattern.subn(label,text)
        if n:hits[label]+=n
    return text,dict(hits),bool(NAME_HINT.search(text))

def normalize(text):
    return re.sub(r'\s+','',text).lower()

def trigram(text):
    s=normalize(text);return {s[i:i+3] for i in range(max(len(s)-2,0))}

def similarity(a,b):
    x,y=trigram(a),trigram(b)
    return len(x&y)/len(x|y) if x and y else 0.0

def allocate(counts,n):
    total=sum(counts.values());raw={k:v*n/total for k,v in counts.items()}
    alloc={k:int(v) for k,v in raw.items()}
    for k in sorted(raw,key=lambda k:raw[k]-alloc[k],reverse=True)[:n-sum(alloc.values())]:alloc[k]+=1
    return alloc

def main():
    p=argparse.ArgumentParser();p.add_argument('--input',required=True);p.add_argument('--column',default='query')
    p.add_argument('--category-column',default='category');p.add_argument('--size',type=int,default=100)
    p.add_argument('--seed',type=int,default=20261106);p.add_argument('--prefix',default='R')
    p.add_argument('--output',default='data/questions_holdout_candidate.json');p.add_argument('--min-chars',type=int,default=6)
    a=p.parse_args();src=Path(a.input)
    with src.open(encoding='utf-8-sig',newline='') as f:rows=list(csv.DictReader(f))
    if not rows or a.column not in rows[0]:raise SystemExit(f'Column {a.column!r} not found')
    seen=set();pool=[];dropped=Counter()
    for row in rows:
        text=(row.get(a.column) or '').strip()
        if len(text)<a.min_chars:dropped['too_short']+=1;continue
        masked,hits,name_hint=mask(text);key=normalize(masked)
        if key in seen:dropped['duplicate']+=1;continue
        seen.add(key);pool.append({'query':masked,'category':(row.get(a.category_column) or '').strip(),'pii_masked':hits,'possible_name':name_hint})
    if len(pool)<a.size:raise SystemExit(f'Only {len(pool)} usable questions; {a.size} required')
    rng=random.Random(a.seed)
    if all(x['category'] for x in pool):
        groups={};[groups.setdefault(x['category'],[]).append(x) for x in pool]
        alloc=allocate(Counter({k:len(v) for k,v in groups.items()}),a.size)
        chosen=[x for k,v in sorted(groups.items()) for x in rng.sample(v,alloc[k])]
        sampling='proportional_stratified_by_observed_category'
    else:
        chosen=rng.sample(pool,a.size);sampling='simple_random';alloc=None
    rng.shuffle(chosen)
    known=[t['representative_query'] for t in json.loads((ROOT/'data/templates.json').read_text(encoding='utf-8'))]
    known+=[q for qs in json.loads((ROOT/'data/template_queries.json').read_text(encoding='utf-8'))['queries'].values() for q in qs]
    known+=[d['query'] for d in json.loads((ROOT/'data/dev_queries.json').read_text(encoding='utf-8'))]
    cases=[]
    for i,x in enumerate(chosen,1):
        near=max(similarity(x['query'],k) for k in known)
        cases.append({'case_id':f'{a.prefix}{i:03d}','category':x['category'],'query':x['query'],'style':'',
            'expected_template_ids':[],'reference_answer':'','source_ids':[],'origin':'real_anonymized',
            'approval_status':'pending_expert_review','split':'independent_holdout_candidate',
            'required_checks':REQUIRED_CHECKS,'anonymization':{'masked':x['pii_masked'],'possible_name_review':x['possible_name'],'manual_review':'pending'},
            'max_similarity_to_template_or_dev_queries':round(near,3)})
    out=resolve_out(a.output);out.write_text(json.dumps(cases,ensure_ascii=False,indent=2)+'\n',encoding='utf-8')
    with out.with_name(out.stem+'_annotation.csv').open('w',encoding='utf-8-sig',newline='') as f:
        w=csv.writer(f);w.writerow(['case_id','category','query','possible_name_review','expected_template_ids(쉼표)','reference_answer','source_ids','reviewer','review_date','comment'])
        for c in cases:w.writerow([c['case_id'],c['category'],c['query'],c['anonymization']['possible_name_review'],'','','','','',''])
    manifest={'created_utc':datetime.now(timezone.utc).isoformat(),'input_file_name':src.name,
        'input_sha256':hashlib.sha256(src.read_bytes()).hexdigest(),'input_rows':len(rows),'usable_after_masking_dedup':len(pool),
        'dropped':dict(dropped),'sampling':sampling,'allocation':alloc,'seed':a.seed,'size':a.size,
        'output':out.name,'output_sha256':hashlib.sha256(out.read_bytes()).hexdigest(),
        'masked_counts':dict(sum((Counter(c['anonymization']['masked']) for c in cases),Counter())),
        'possible_name_cases':[c['case_id'] for c in cases if c['anonymization']['possible_name_review']],
        'note':'Automated masking is incomplete by nature. Experts must review anonymization and label expected templates before approval. Do not tune retrieval on this file.'}
    out.with_name(out.stem+'_sampling_manifest.json').write_text(json.dumps(manifest,ensure_ascii=False,indent=2)+'\n',encoding='utf-8')
    print(json.dumps({'output':str(out),'cases':len(cases),'sampling':sampling,'possible_name_cases':len(manifest['possible_name_cases'])},ensure_ascii=False))

def resolve_out(path):
    path=Path(path);return path if path.is_absolute() else ROOT/path

if __name__=='__main__':main()
