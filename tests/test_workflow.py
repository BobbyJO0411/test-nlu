import json,unittest
from nlu.engine import ROOT,Recommender
from nlu.metrics import summarize
from fastapi.testclient import TestClient
from unittest.mock import patch

class DataTests(unittest.TestCase):
    def test_dataset_integrity_and_sources(self):
        qs=json.loads((ROOT/'data/questions_100.json').read_text(encoding='utf-8'))
        ts=json.loads((ROOT/'data/templates.json').read_text(encoding='utf-8'))
        ss=json.loads((ROOT/'data/source_excerpts.json').read_text(encoding='utf-8'))
        self.assertEqual(len(qs),100);self.assertEqual(len({q['query'] for q in qs}),100)
        self.assertEqual(len({q['case_id'] for q in qs}),100)
        tids={t['template_id'] for t in ts}
        for q in qs:
            self.assertTrue(set(q['expected_template_ids'])<=tids)
            self.assertEqual(q['approval_status'],'pending_expert_review')
            self.assertEqual(q['origin'],'synthetic_authored')
        for t in ts:
            for sid in t['source_ids']:
                self.assertIn(sid,ss)
                self.assertTrue(all(e['text'].strip() for e in ss[sid]['excerpts']))
        counts={c:sum(q['category']==c for q in qs) for c in {q['category'] for q in qs}}
        self.assertEqual(set(counts.values()),{4});self.assertEqual(len(counts),25)
    def test_baseline_predicts_without_gold_file(self):
        model=Recommender('baseline')
        result=model.recommend('상표 의견제출통지서를 받았어요. 최종 거절인가요?')
        self.assertEqual(result['selected_template_id'],'T020')
        self.assertEqual(len(result['candidates']),3)
        self.assertIn('최종 거절결정',result['recommended_answer'])
        self.assertTrue(result['requires_practitioner_review'])
        for q in ['', '   ']:
            with self.assertRaises(ValueError): model.recommend(q)
        with self.assertRaises(ValueError): model.recommend('상표',31)
    def test_e5_never_silently_falls_back(self):
        with patch('huggingface_hub.snapshot_download',side_effect=OSError('network blocked')):
            with self.assertRaises(OSError):Recommender('e5')
    def test_model_manifest_hash_failure_blocks_loading(self):
        import tempfile
        from pathlib import Path
        with tempfile.TemporaryDirectory() as temp:
            p=Path(temp);(p/'config.json').write_text('{}')
            (p/'verified_model.json').write_text(json.dumps({'model_id':'test','revision':'a'*40,'files':{'config.json':'wrong'}}))
            with self.assertRaisesRegex(ValueError,'hash mismatch'):
                Recommender('e5',model_id='test',model_path=p)

class MetricTests(unittest.TestCase):
    def setUp(self):
        self.ids=[f'Q{i:03d}' for i in range(1,101)]
        self.rows=[{'case_id':i,'a':'success','b':'success'} for i in self.ids]
    def test_all_success(self):
        m=summarize(self.rows,self.ids)
        self.assertEqual(m['suitability_pct'],100);self.assertEqual(m['agreement_pct'],100)
        self.assertIsNone(m['cohen_kappa'])
    def test_incomplete_is_not_success(self):
        self.rows[0]['a']=''
        self.assertIsNone(summarize(self.rows,self.ids)['suitability_pct'])
    def test_disagreements_do_not_inflate_initial_agreement(self):
        for row in self.rows[:10]:
            row.update(b='failure',final='failure',resolution_reason='협의 후 핵심 누락 판단')
        m=summarize(self.rows,self.ids)
        self.assertEqual(m['suitability_pct'],90);self.assertEqual(m['agreement_pct'],90)
        self.assertEqual(m['failure_count'],10)
    def test_unresolved_and_reasonless_are_blocked(self):
        self.rows[0].update(b='failure',final='success',resolution_reason='')
        m=summarize(self.rows,self.ids)
        self.assertEqual(m['status'],'unresolved_disagreements');self.assertIsNone(m['suitability_pct'])
    def test_duplicates_and_missing_ids_block(self):
        self.rows[0]['case_id']=self.rows[1]['case_id']
        with self.assertRaises(ValueError):summarize(self.rows,self.ids)
        with self.assertRaises(ValueError):summarize(self.rows[1:],self.ids)
    def test_conflicting_final_cannot_override_agreement(self):
        self.rows[0]['final']='failure'
        with self.assertRaises(ValueError):summarize(self.rows,self.ids)
    def test_all_fail_is_zero(self):
        for row in self.rows:row.update(a='failure',b='failure')
        self.assertEqual(summarize(self.rows,self.ids)['suitability_pct'],0)

class ApiTests(unittest.TestCase):
    def test_functional_recommendation_and_input_validation(self):
        with patch.dict('os.environ',{'NLU_BACKEND':'baseline'}):
            from nlu.api import app
            with TestClient(app) as client:
                self.assertEqual(client.get('/health').json()['engine']['backend'],'baseline')
                response=client.post('/recommend',json={'query':'의견제출통지서 받았는데 등록이 최종 거절된 건가요?'})
                self.assertEqual(response.status_code,200)
                self.assertEqual(response.json()['selected_template_id'],'T020')
                self.assertEqual(client.post('/recommend',json={'query':'   '}).status_code,422)
                self.assertEqual(client.post('/recommend',json={'query':'상표','top_k':31}).status_code,422)
                self.assertEqual(client.get('/').status_code,200)
                datasets=client.get('/datasets')
                self.assertEqual(datasets.status_code,200)
                self.assertEqual(len(datasets.json()['questions']),100)
                self.assertEqual(len(datasets.json()['templates']),30)

if __name__=='__main__':unittest.main()
