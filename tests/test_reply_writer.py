import unittest
from unittest.mock import AsyncMock
from reviewarena.reply_writer import compose_response, style_examples


class ReplyWriterTests(unittest.IsolatedAsyncioTestCase):
    def test_reads_and_deduplicates_actual_reply_text(self):
        history = [{'reply': '{"comment":"We address the two points separately."}'}] * 2
        self.assertEqual(style_examples(history), ['We address the two points separately.'])

    async def test_experiment_replaces_future_promise_with_result_slots(self):
        ask=AsyncMock(side_effect=[
            {'response':'In a future revision, we will audit the overlap.'},
            {'response':'Across folds, patient overlap is [overlap count] of [total patients].'},
            {'unsupported_quote':''},
        ])
        draft=await compose_response(ask,{'pages':['Audit']},'How much overlap?',None,'Audit the splits.',[],action='experiment')
        self.assertEqual(draft,'Across folds, patient overlap is [overlap count] of [total patients].')

    async def test_experiment_cannot_fall_back_to_invented_result(self):
        ask=AsyncMock(return_value={'response':'Overlap was zero.'})
        draft=await compose_response(ask,{'pages':['Audit']},'How much overlap?',None,'Measure overlap.',[],action='experiment')
        self.assertNotIn('zero',draft)
        self.assertIn('[',draft)

    async def test_missing_results_cover_both_parts_of_a_comparison(self):
        ask=AsyncMock(side_effect=[{'response':'We agree that this is important.'},
                                   {'response':'We will investigate this.'},
                                   {'primary':'expert activation patterns','comparison':'overlap'}])
        reply=await compose_response(ask,{'pages':['Experts']},'Which patterns, and how much overlap?',
                                     None,'Measure patterns and overlap.',[],action='experiment')
        self.assertIn('expert activation patterns',reply)
        self.assertIn('[measured overlap]',reply)

    def test_export_hides_evidence_only_when_absent(self):
        from reviewarena.api import rebuttal_markdown
        answer=dict(action='revise',draft='An admission is one inpatient stay.',next_step='Define admission.')
        point=dict(critique='What counts as an admission?',answer=answer)
        self.assertNotIn('Existing manuscript evidence',rebuttal_markdown([point]))
        answer['existing_evidence']=dict(page=2,quote='One inpatient stay.')
        self.assertIn('Page 2 · One inpatient stay.',rebuttal_markdown([point]))
