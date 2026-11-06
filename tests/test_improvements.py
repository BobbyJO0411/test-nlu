import csv,json,subprocess,sys,tempfile,unittest
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch
from nlu.engine import ROOT,Recommender,verify_snapshot,git_blob_sha1
from nlu.metrics import summarize

def trigram(text):
    s=''.join(text.split());return {s[i:i+3] for i in range(len(s)-2)}

def jaccard(a,b):
    x,y=trigram(a),trigram(b);return len(x&y)/len(x|y)

class LeakageTests(unittest.TestCase):
    def test_tuning_and_enrichment_data_are_separate_from_evaluation_set(self):
        test=[q['query'] for q in json.loads((ROOT/'data/questions_100.json').read_text(encoding='utf-8'))]
        extra=json.loads((ROOT/'data/template_queries.json').read_text(encoding='utf-8'))['queries']
        dev=json.loads((ROOT/'data/dev_queries.json').read_text(encoding='utf-8'))
        tids={t['template_id'] for t in json.loads((ROOT/'data/templates.json').read_text(encoding='utf-8'))}
        self.assertEqual(set(extra),tids)
        self.assertEqual({d['expected_template_ids'][0] for d in dev},tids)
        self.assertEqual(len({d['dev_id'] for d in dev}),len(dev))
        added=[q for qs in extra.values() for q in qs]
        dev_q=[d['query'] for d in dev]
        self.assertFalse(set(added)&set(dev_q),'dev queries must not be template views')
        for q in added+dev_q:
            self.assertNotIn(q,test)
            self.assertLess(max(jaccard(q,t) for t in test),0.5,q)
        for q in dev_q:
            self.assertLess(max(jaccard(q,t) for t in added),0.6,q)

class RetrievalTests(unittest.TestCase):
    def test_multiview_hybrid_scores_and_metadata(self):
        model=Recommender('baseline',strategy='multiview_hybrid',alpha=0.5,beta=0.2)
        result=model.recommend('의견제출통지서가 왔는데 아직 대응할 기회가 있나요?')
        self.assertEqual(result['selected_template_id'],'T020')
        self.assertEqual(result['retrieval_strategy'],'multiview_hybrid')
        self.assertEqual(model.metadata['retrieval']['view_count'],150)
        self.assertEqual(len(model.metadata['template_queries_sha256']),64)
        with self.assertRaises(ValueError):Recommender('baseline',strategy='unknown')
        with self.assertRaises(ValueError):Recommender('baseline',strategy='multiview_hybrid',alpha=1.5)

    def test_tune_uses_dev_set_only(self):
        with tempfile.TemporaryDirectory() as temp:
            report=Path(temp)/'tune.json'
            out=subprocess.run([sys.executable,'-m','nlu.cli','tune','--backend','baseline','--report',str(report)],cwd=ROOT,capture_output=True,text=True)
            self.assertEqual(out.returncode,0,out.stderr)
            data=json.loads(report.read_text(encoding='utf-8'))
            self.assertEqual(data['dev_path'],'data/dev_queries.json')
            self.assertEqual(data['grid'][0]['total'],90)
            self.assertGreaterEqual(data['selected']['top1'],data['grid'][0]['top1'])

class SnapshotVerificationTests(unittest.TestCase):
    def test_hash_mismatch_and_unlisted_files_are_rejected(self):
        with tempfile.TemporaryDirectory() as temp:
            p=Path(temp);(p/'config.json').write_bytes(b'{}');(p/'model.safetensors').write_bytes(b'weights')
            import hashlib
            good={'config.json':SimpleNamespace(rfilename='config.json',lfs=None,blob_id=git_blob_sha1(b'{}')),
                'model.safetensors':SimpleNamespace(rfilename='model.safetensors',lfs=SimpleNamespace(sha256=hashlib.sha256(b'weights').hexdigest()),blob_id='x')}
            def api(siblings):
                return patch('huggingface_hub.HfApi',return_value=SimpleNamespace(model_info=lambda *a,**k:SimpleNamespace(siblings=siblings)))
            with api(list(good.values())):self.assertEqual(verify_snapshot(p,'m','a'*40),2)
            bad=dict(good);bad['model.safetensors']=SimpleNamespace(rfilename='model.safetensors',lfs=SimpleNamespace(sha256='0'*64),blob_id='x')
            with api(list(bad.values())),self.assertRaisesRegex(ValueError,'SHA256 mismatch'):verify_snapshot(p,'m','a'*40)
            with api([good['config.json']]),self.assertRaisesRegex(ValueError,'not listed'):verify_snapshot(p,'m','a'*40)

class DecisionRuleTests(unittest.TestCase):
    def setUp(self):
        self.ids=[f'Q{i:03d}' for i in range(1,101)]
        self.rows=[{'case_id':i,'a':'success','b':'success'} for i in self.ids]
        for row in self.rows[:6]:row['b']='failure'
    def test_majority_requires_third_rater_on_disagreements(self):
        m=summarize(self.rows,self.ids,'majority')
        self.assertEqual(m['status'],'unresolved_disagreements');self.assertEqual(len(m['unresolved_ids']),6)
        for i,row in enumerate(self.rows[:6]):row['c']='success' if i<4 else 'failure'
        m=summarize(self.rows,self.ids,'majority')
        self.assertEqual(m['status'],'complete');self.assertEqual(m['resolved_by_majority'],6)
        self.assertEqual(m['success_count'],98);self.assertEqual(m['agreement_pct'],94)
        self.assertEqual(m['iso_25023']['X_pct'],m['suitability_pct'])
        self.assertEqual(m['iso_25023']['A_incorrect_responses'],2)
    def test_majority_cannot_be_overridden(self):
        for row in self.rows[:6]:row['c']='success'
        self.rows[0]['final']='failure'
        with self.assertRaises(ValueError):summarize(self.rows,self.ids,'majority')
    def test_consensus_still_requires_reason(self):
        for row in self.rows[:6]:row['c']='success'
        self.assertEqual(summarize(self.rows,self.ids,'consensus')['status'],'unresolved_disagreements')
    def test_three_rater_statistics_when_c_rates_everything(self):
        for row in self.rows:row['c']=row['a']
        m=summarize(self.rows,self.ids,'majority')
        self.assertEqual(m['three_rater_unanimous_pct'],94);self.assertEqual(m['pairwise_agreement_pct']['a_c'],100)
        self.assertIsNotNone(m['fleiss_kappa'])
    def test_invalid_rule(self):
        with self.assertRaises(ValueError):summarize(self.rows,self.ids,'vote')

class RealQueryPreparationTests(unittest.TestCase):
    def test_masking_dedup_and_stratified_sampling(self):
        with tempfile.TemporaryDirectory() as temp:
            temp=Path(temp);src=temp/'export.csv'
            with src.open('w',encoding='utf-8-sig',newline='') as f:
                w=csv.writer(f);w.writerow(['query','category'])
                w.writerow(['연락처 010-1234-5678, mail a.b@test.com 로 출원번호 40-2025-0012345 진행상황 알려주세요','등록절차'])
                w.writerow(['연락처 010-1234-5678, mail a.b@test.com 로 출원번호 40-2025-0012345 진행상황 알려주세요','등록절차'])
                w.writerow(['짧음','등록절차'])
                for i in range(150):w.writerow([f'테스트 상담 질문 번호 {i} 입니다 수수료 문의','수수료' if i<90 else '거절이유통지'])
            out=temp/'holdout.json'
            r=subprocess.run([sys.executable,'scripts/prepare_real_queries.py','--input',str(src),'--output',str(out)],cwd=ROOT,capture_output=True,text=True)
            self.assertEqual(r.returncode,0,r.stderr)
            cases=json.loads(out.read_text(encoding='utf-8'))
            self.assertEqual(len(cases),100);self.assertEqual(len({c['case_id'] for c in cases}),100)
            text=json.dumps(cases,ensure_ascii=False)
            for raw in ['010-1234-5678','a.b@test.com','40-2025-0012345']:self.assertNotIn(raw,text)
            manifest=json.loads((temp/'holdout_sampling_manifest.json').read_text(encoding='utf-8'))
            self.assertEqual(manifest['dropped'],{'too_short':1,'duplicate':1})
            self.assertEqual(sum(manifest['allocation'].values()),100)
            self.assertTrue(all(c['origin']=='real_anonymized' and not c['expected_template_ids'] for c in cases))

if __name__=='__main__':unittest.main()
