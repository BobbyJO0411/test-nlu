import contextlib,io,json,shutil,sys,tempfile,unittest
from pathlib import Path
from openpyxl import load_workbook
from nlu.engine import ROOT
sys.path.insert(0,str(ROOT/'scripts'))
import make_template_review_workbook as maker
import apply_template_review as applier

class TemplateReviewTests(unittest.TestCase):
    def setUp(self):
        self.tmp=Path(tempfile.mkdtemp());self.addCleanup(shutil.rmtree,self.tmp)
        self.templates=self.tmp/'templates.json';self.views=self.tmp/'template_queries.json'
        shutil.copy(ROOT/'data/templates.json',self.templates);shutil.copy(ROOT/'data/template_queries.json',self.views)
        self.book=self.tmp/'review.xlsx';maker.build(self.book)

    def fill(self,template_decision='approve',view_decision='keep',reviewer=True,overrides=None):
        wb=load_workbook(self.book)
        for row in wb['템플릿'].iter_rows(min_row=2):
            row[6].value=template_decision;row[9].value='2026-11-10'
        for row in wb['대표질문'].iter_rows(min_row=2):row[3].value=view_decision
        if reviewer:
            for row in wb['검토자'].iter_rows(min_row=2):row[1].value='테스트 값'
        for sheet,rid,col,value in overrides or []:
            for row in wb[sheet].iter_rows(min_row=2):
                if row[0].value==rid:row[col].value=value
        wb.save(self.book)

    def run_apply(self,*extra):
        out=io.StringIO()
        with contextlib.redirect_stdout(out):
            code=applier.main(['--workbook',str(self.book),'--templates',str(self.templates),'--template-queries',str(self.views),*extra])
        return code,json.loads(out.getvalue())

    def test_workbook_lists_every_template_and_view(self):
        wb=load_workbook(self.book)
        self.assertEqual(wb['템플릿'].max_row-1,30)
        self.assertEqual(wb['대표질문'].max_row-1,sum(len(v) for v in json.loads(self.views.read_text(encoding='utf-8'))['queries'].values()))

    def test_blank_review_is_invalid_and_changes_nothing(self):
        before=self.templates.read_bytes()
        code,summary=self.run_apply('--write')
        self.assertEqual(code,1);self.assertEqual(summary['result'],'invalid')
        self.assertEqual(self.templates.read_bytes(),before)

    def test_missing_reviewer_is_invalid(self):
        self.fill(reviewer=False)
        code,summary=self.run_apply('--write')
        self.assertEqual(code,1);self.assertTrue(any('검토자' in e for e in summary['errors']))

    def test_full_approval_marks_every_item_approved(self):
        self.fill()
        code,summary=self.run_apply('--write')
        self.assertEqual(code,0);self.assertEqual(summary['result'],'approved')
        templates=json.loads(self.templates.read_text(encoding='utf-8'))
        self.assertTrue(all(t['approval_status']=='approved' and t['expert_review']['law_review_date'] for t in templates))
        self.assertEqual(json.loads(self.views.read_text(encoding='utf-8'))['status'],'approved')

    def test_dry_run_does_not_write(self):
        self.fill();before=self.templates.read_bytes()
        code,_=self.run_apply()
        self.assertEqual(code,0);self.assertEqual(self.templates.read_bytes(),before)

    def test_revision_is_applied_but_not_approved(self):
        self.fill(overrides=[('템플릿','T002',6,'revise'),('템플릿','T002',7,'수정된 응답 원문'),
            ('대표질문','T001-1',3,'remove'),('대표질문','T001-1',5,'다른 템플릿 질문')])
        code,summary=self.run_apply('--write')
        self.assertEqual(code,0);self.assertEqual(summary['result'],'changes_requested')
        t={x['template_id']:x for x in json.loads(self.templates.read_text(encoding='utf-8'))}
        self.assertEqual(t['T002']['answer'],'수정된 응답 원문');self.assertEqual(t['T002']['approval_status'],'revised_pending_reconfirm')
        views=json.loads(self.views.read_text(encoding='utf-8'))
        self.assertEqual(views['status'],'revised_pending_reconfirm')
        original=json.loads((ROOT/'data/template_queries.json').read_text(encoding='utf-8'))['queries']['T001']
        self.assertEqual(views['queries']['T001'],original[1:])

    def test_revise_without_text_is_invalid(self):
        self.fill(overrides=[('템플릿','T003',6,'revise')])
        code,summary=self.run_apply('--write')
        self.assertEqual(code,1);self.assertTrue(any('T003' in e for e in summary['errors']))

    def test_template_removal_is_not_applied_automatically(self):
        self.fill(overrides=[('템플릿','T004',6,'remove'),('템플릿','T004',8,'중복 템플릿')])
        before=self.templates.read_bytes()
        code,summary=self.run_apply('--write')
        self.assertEqual(code,2);self.assertEqual(summary['result'],'manual_action_required')
        self.assertEqual(self.templates.read_bytes(),before)

    def test_stale_workbook_is_refused(self):
        self.fill()
        data=json.loads(self.templates.read_text(encoding='utf-8'));data[0]['answer']+=' '
        self.templates.write_text(json.dumps(data,ensure_ascii=False,indent=2)+'\n',encoding='utf-8')
        with self.assertRaises(SystemExit):self.run_apply('--write')

if __name__=='__main__':unittest.main()
