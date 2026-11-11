"""End-to-end check of scripts/self_test.py with the archived KoE5 development run.
The judgments written here are test fixtures only; they are never evaluator results."""
import contextlib,csv,io,json,shutil,sys,tempfile,unittest
from pathlib import Path
from openpyxl import load_workbook
from nlu.engine import ROOT
sys.path.insert(0,str(ROOT/'scripts'))
import self_test

PKG=ROOT/'artifacts/review_package'

def quiet(fn,*args):
    out=io.StringIO()
    with contextlib.redirect_stdout(out):code=fn(list(args))
    return code,out.getvalue()

class SelfTestFlow(unittest.TestCase):
    def setUp(self):
        self.tmp=Path(tempfile.mkdtemp());self.addCleanup(shutil.rmtree,self.tmp)
        run=self.tmp/'run';run.mkdir()
        shutil.copyfile(PKG/'개발실행_manifest.json',run/'manifest.json');shutil.copyfile(PKG/'개발실행_recommendations.json',run/'recommendations.json')
        quiet(self_test.main,'prepare','--run-dir',str(run),'--out',str(self.tmp/'out'))
        self.dir=next((self.tmp/'out').iterdir())
        self.a=self.dir/'평가자A.xlsx';self.b=self.dir/'평가자B.xlsx'

    def fill(self,path,name,fail_ids):
        wb=load_workbook(path);ws=wb['평가']
        for row in ws.iter_rows(min_row=2):
            ok=row[0].value not in fail_ids
            for cell in row[4:9]:cell.value=5 if ok else 2
            row[9].value='success' if ok else 'failure';row[10].value='fixture';row[11].value=name;row[12].value='fixture role';row[13].value='2026-11-11'
        wb.save(path)

    def ids(self,n,start=1):
        return {f'Q{i:03d}' for i in range(start,start+n)}

    def test_workbooks_cover_100_cases(self):
        ws=load_workbook(self.a)['평가']
        self.assertEqual(ws.max_row-1,100)
        self.assertTrue(all(c.value in (None,'') for c in list(ws.iter_rows(min_row=2))[0][4:]))

    def test_consensus_pass_and_metrics(self):
        self.fill(self.a,'평가자1',self.ids(10));self.fill(self.b,'평가자2',self.ids(12))  # Q011,Q012 disagree
        quiet(self_test.main,'resolve','--run-dir',str(self.dir),'--a',str(self.a),'--b',str(self.b))
        res=self.dir/'협의결과.csv'
        with res.open(encoding='utf-8-sig',newline='') as f:rows=list(csv.DictReader(f))
        self.assertEqual([r['case_id'] for r in rows],['Q011','Q012'])
        for r in rows:r.update(final='success',resolution_reason='fixture',resolution_date='2026-11-11',participants='평가자1,평가자2')
        with res.open('w',encoding='utf-8-sig',newline='') as f:
            w=csv.DictWriter(f,fieldnames=list(rows[0]));w.writeheader();w.writerows(rows)
        code,_=quiet(self_test.main,'score','--run-dir',str(self.dir),'--a',str(self.a),'--b',str(self.b))
        r=json.loads((self.dir/'시험결과.json').read_text(encoding='utf-8'))
        self.assertEqual(code,0);self.assertEqual(r['verdict'],'합격')
        self.assertEqual(r['suitability_pct'],90.0);self.assertEqual(r['agreement_pct'],98.0)
        self.assertEqual(r['iso_25023']['X'],0.9)
        self.assertTrue((self.dir/'시험결과서.docx').exists() and (self.dir/'시험결과_상세.xlsx').exists())

    def test_below_threshold_fails(self):
        self.fill(self.a,'평가자1',self.ids(21));self.fill(self.b,'평가자2',self.ids(21))
        code,_=quiet(self_test.main,'score','--run-dir',str(self.dir),'--a',str(self.a),'--b',str(self.b))
        r=json.loads((self.dir/'시험결과.json').read_text(encoding='utf-8'))
        self.assertEqual(code,1);self.assertEqual(r['suitability_pct'],79.0);self.assertEqual(r['verdict'],'불합격')

    def test_exactly_threshold_passes(self):
        self.fill(self.a,'평가자1',self.ids(20));self.fill(self.b,'평가자2',self.ids(20))
        code,_=quiet(self_test.main,'score','--run-dir',str(self.dir),'--a',str(self.a),'--b',str(self.b))
        self.assertEqual(code,0)

    def test_unresolved_disagreement_gives_no_verdict(self):
        self.fill(self.a,'평가자1',set());self.fill(self.b,'평가자2',self.ids(1))
        code,_=quiet(self_test.main,'score','--run-dir',str(self.dir),'--a',str(self.a),'--b',str(self.b))
        r=json.loads((self.dir/'시험결과.json').read_text(encoding='utf-8'))
        self.assertEqual(code,1);self.assertEqual(r['verdict'],'판정 불가');self.assertIsNone(r['suitability_pct'])

    def test_unfinished_workbook_is_rejected(self):
        self.fill(self.a,'평가자1',set())
        with self.assertRaises(SystemExit):quiet(self_test.main,'score','--run-dir',str(self.dir),'--a',str(self.a),'--b',str(self.b))

    def test_same_person_as_a_and_b_is_rejected(self):
        self.fill(self.a,'같은사람',set());self.fill(self.b,'같은사람',set())
        with self.assertRaises(SystemExit):quiet(self_test.main,'score','--run-dir',str(self.dir),'--a',str(self.a),'--b',str(self.b))

    def test_majority_rule_uses_third_rater(self):
        self.fill(self.a,'평가자1',set());self.fill(self.b,'평가자2',self.ids(3))
        quiet(self_test.main,'resolve','--run-dir',str(self.dir),'--a',str(self.a),'--b',str(self.b),'--decision-rule','majority')
        wb=load_workbook(self.dir/'평가자C.xlsx');ws=wb['평가']
        self.assertEqual(ws.max_row-1,3)
        for row in ws.iter_rows(min_row=2):
            for cell in row[4:9]:cell.value=4
            row[9].value='success';row[10].value='fixture';row[11].value='평가자3';row[12].value='fixture role';row[13].value='2026-11-11'
        wb.save(self.dir/'평가자C.xlsx')
        code,_=quiet(self_test.main,'score','--run-dir',str(self.dir),'--a',str(self.a),'--b',str(self.b),'--decision-rule','majority')
        r=json.loads((self.dir/'시험결과.json').read_text(encoding='utf-8'))
        self.assertEqual(code,0);self.assertEqual(r['suitability_pct'],100.0);self.assertEqual(r['agreement_pct'],97.0)

if __name__=='__main__':unittest.main()
