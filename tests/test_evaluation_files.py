import csv,json,subprocess,sys,tempfile,unittest
from pathlib import Path
from openpyxl import load_workbook
from nlu.engine import ROOT

class EvaluationFileTests(unittest.TestCase):
    def command(self,*args):
        return subprocess.run([sys.executable,*args],cwd=ROOT,capture_output=True,text=True)
    def test_manual_file_flow_and_submission_gate(self):
        with tempfile.TemporaryDirectory() as temp:
            temp=Path(temp)
            run=self.command('-m','nlu.cli','run','--backend','baseline','--output',str(temp/'runs'))
            self.assertEqual(run.returncode,0,run.stderr)
            run_dir=Path(json.loads(run.stdout)['run_dir'])
            out=temp/'package'
            build=self.command('scripts/build_deliverables.py','--run-dir',str(run_dir),'--out',str(out))
            self.assertEqual(build.returncode,0,build.stderr)
            # Unfilled forms must be rejected, not counted as passing.
            args=['scripts/collect_ratings.py','--run-dir',str(run_dir),'--a',str(out/'평가자A_실평가.xlsx'),'--b',str(out/'평가자B_실평가.xlsx'),'--output',str(temp/'ratings.csv')]
            self.assertNotEqual(self.command(*args).returncode,0)
            for person in ['A','B']:
                file=out/f'평가자{person}_실평가.xlsx';wb=load_workbook(file);ws=wb['평가']
                for row in range(2,102):
                    for col in range(5,10):ws.cell(row,col,5)
                    ws.cell(row,10,'success');ws.cell(row,11,'TEST_ONLY_SYNTHETIC_RECORD')
                    ws.cell(row,12,'TEST_ONLY_'+person);ws.cell(row,13,'TEST_ONLY_ROLE');ws.cell(row,14,'TEST_ONLY_DATE')
                wb.save(file)
            collect=self.command(*args);self.assertEqual(collect.returncode,0,collect.stderr)
            score=self.command('-m','nlu.cli','score','--run-dir',str(run_dir),'--ratings',str(temp/'ratings.csv'),'--output',str(temp/'metrics.json'))
            self.assertEqual(score.returncode,0,score.stderr)
            metrics=json.loads((temp/'metrics.json').read_text(encoding='utf-8'))
            self.assertEqual(metrics['suitability_pct'],100)
            self.assertTrue(metrics['questionnaire_complete'])
            self.assertFalse(metrics['submission_candidate'])
            self.assertFalse(metrics['embedding_backend'])
            self.assertFalse(metrics['expert_approval_record_present'])
            # Original question/response must remain unmodified.
            file=out/'평가자A_실평가.xlsx';wb=load_workbook(file);wb['평가']['C2']='Modified response';wb.save(file)
            self.assertNotEqual(self.command(*args).returncode,0)
            sim=self.command('-m','nlu.cli','score','--run-dir',str(run_dir),'--ratings',str(out/'모의평가_제출불가.csv'),'--output',str(temp/'simulation.json'))
            self.assertEqual(sim.returncode,0,sim.stderr)
            self.assertFalse(json.loads((temp/'simulation.json').read_text(encoding='utf-8'))['submission_candidate'])
            master=load_workbook(out/'NLU_100건_평가데이터시트.xlsx')
            self.assertEqual(master['실평가집계_빈양식'].max_row,101)
            self.assertIsNone(master['실평가집계_빈양식']['B2'].value)
            self.assertIn('IF',master['실평가요약']['B4'].value)

class LlmSelectorTests(unittest.TestCase):
    def test_out_of_candidates_response_is_rejected(self):
        from unittest.mock import patch,Mock
        from nlu.llm import select
        response=Mock();response.json.return_value={'choices':[{'message':{'content':'{"template_id":"BAD"}'}}]}
        result={'candidates':[{'template_id':'T001','answer':'approved draft'}]}
        with patch.dict('os.environ',{'NLU_LLM_API_KEY':'TEST_ONLY_KEY'}),patch('httpx.post',return_value=response):
            with self.assertRaises(ValueError):select('TEST_QUERY',result)
    def test_missing_key_blocks_external_call(self):
        from unittest.mock import patch
        from nlu.llm import select
        with patch.dict('os.environ',{},clear=True),patch('httpx.post') as post:
            with self.assertRaises(RuntimeError):select('TEST_QUERY',{'candidates':[]})
            post.assert_not_called()
