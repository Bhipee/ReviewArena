import unittest
from contextlib import asynccontextmanager
from unittest.mock import AsyncMock, patch
from reviewarena.reply_writer import compose_response, style_examples


class ReplyWriterTests(unittest.IsolatedAsyncioTestCase):
    async def test_discussion_drafts_a_conditional_reply_without_creating_work(self):
        from reviewarena.api import experiment_checklist,rebuttal_markdown
        from reviewarena import workflow

        question='Could the trade-off change if requests arrive in bursts?'
        paragraph='If requests arrive together, queueing could outweigh the savings from reuse.'
        ask=AsyncMock(side_effect=[
            {'concerns':[{'quote':question,'category':'interpretation'}]},
            {'action':'Discussion','evidence_index':0,'planned_step':'Add new simulations.','priority':1,'effort':'high'},
            {'response':paragraph},
            {'unsupported_quote':''},
        ])
        @asynccontextmanager
        async def kb(*args):
            yield AsyncMock(return_value=[])
        with patch.object(workflow,'ask',ask), patch.object(workflow,'connect',kb), patch.object(workflow,'passages',return_value=[]):
            result=await workflow.rebuttal({'pages':['Cache reuse']},question)
        rows=result['responses']
        answer=rows[0]['answer']
        self.assertEqual((answer['action'],answer['draft']),('discussion',paragraph))
        self.assertFalse(answer['next_step'] or answer['experiment'] or answer['existing_evidence'])
        self.assertIsNone(answer['priority'])
        self.assertIsNone(answer['effort'])
        self.assertEqual(experiment_checklist(rows),[])
        exported=rebuttal_markdown(rows)
        self.assertIn('Response to reviewer (discussion)',exported)
        self.assertNotIn('Suggested next step',exported)
        self.assertNotIn('Experiment checklist',exported)

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
