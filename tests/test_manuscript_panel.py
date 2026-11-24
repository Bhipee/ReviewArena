import base64
from contextlib import asynccontextmanager, ExitStack
import json
from pathlib import Path
from tempfile import TemporaryDirectory
from unittest import IsolatedAsyncioTestCase
from unittest.mock import AsyncMock, patch

import pymupdf
import requests

from reviewarena import workflow
from reviewarena.demos import read_review_demo
from reviewarena.model import generate
from reviewarena.paper import parse_pdf
from reviewarena.presentation_review import presentation_review
from reviewarena.reviewer_roles import REVIEWER_ROLES, PRESENTATION, INNOVATION, reviewer_prompt, specialist_finding


class ManuscriptPanelTests(IsolatedAsyncioTestCase):
    def setUp(self):
        with pymupdf.open() as pdf:
            for text in ("Figure 1: Accuracy on two cohorts. See Table ??.", "Table 1: Paired accuracy with units."):
                pdf.new_page().insert_text((36,72),text)
            self.raw=pdf.tobytes()
        self.paper=parse_pdf(self.raw)

    async def test_rendered_evidence_and_text_fallback(self):
        def inspect(task, payload, images):
            self.assertEqual(payload["page_numbers_in_image_order"],[1,2])
            self.assertTrue(all(base64.b64decode(i.split(",")[1]).startswith(b"\xff\xd8") for i in images))
            return {"observations":[{"page":1,"element":"Figure 1","observation":"Two cohorts share an axis."},
                                    {"page":9,"element":"Table X","observation":"Invalid page."}]}
        with patch.dict("os.environ",REVIEWARENA_VISION="true"), patch("reviewarena.presentation_review.generate",inspect):
            seen=await presentation_review(self.paper,self.raw)
        self.assertEqual(seen["inspected_pages"],[1,2])
        self.assertEqual(len([r for r in seen["sources"] if r["kind"]=="visual observation"]),1)
        with patch.dict("os.environ",REVIEWARENA_VISION="true"), patch("reviewarena.presentation_review.generate",side_effect=requests.HTTPError()):
            fallback=await presentation_review(self.paper,self.raw)
        self.assertFalse(fallback["inspected_pages"])
        self.assertTrue(any("Table ??" in r["quote"] for r in fallback["sources"]))
        with patch.dict("os.environ",REVIEWARENA_VISION="false"), patch("reviewarena.presentation_review.generate") as vision:
            local=await presentation_review(self.paper,self.raw)
        vision.assert_not_called()
        self.assertFalse(local["inspected_pages"])
        self.assertTrue(any(r["label"]=="Table 1" for r in local["sources"]))

    def test_image_message_uses_the_configured_chat_transport(self):
        with patch.dict("os.environ",REVIEWARENA_PUBLIC_RUN_CACHE=""), patch("reviewarena.model.model_post") as send:
            send.return_value.json.return_value={"choices":[{"message":{"content":"{\"observations\":[]}"}}]}
            generate("inspect",{"pages":[1]},images=["data:image/jpeg;base64,abc"])
            content=send.call_args.kwargs["json"]["messages"][1]["content"]
        self.assertEqual([x["type"] for x in content],["text","image_url"])
        self.assertEqual(content[1]["image_url"]["url"],"data:image/jpeg;base64,abc")

    async def test_specialist_assessment_retains_only_a_locatable_anchor(self):
        source=dict(id="s1",page=2,quote="The paired interval includes zero.")
        proposal=dict(ref=1,assessment="The effect is uncertain.")
        for key, quote, grounded in (("anchor","interval includes zero",True),("quote","includes zero",True),
                                     ("source","interval includes zero",True),("quote","significant at every site",False)):
            response={key:{"quote":quote} if key=="source" else quote,"assessment":"The effect is uncertain."}
            ask=AsyncMock(side_effect=[proposal,response])
            finding=await specialist_finding(REVIEWER_ROLES[1],[source],ask)
            self.assertEqual(finding is not None,grounded)
            if grounded:
                self.assertEqual(finding["source"]["quote"],quote)

    async def test_five_whole_paper_scores_reach_chair_and_progress(self):
        @asynccontextmanager
        async def no_tools(*_):
            yield None

        quote=self.paper["pages"][0]
        prepared=dict(manuscript_sha256=self.paper["hash"],claims=[dict(text=quote,page=1)],
                      settings=[],paper_type="empirical")
        seen={}
        async def ask(task,**data):
            if "Choose ONE source" in task:
                return {"ref":1,"assessment":"The caption identifies the two cohorts."}
            if "Independently read this one source" in task:
                return dict(anchor=data["source"]["quote"],assessment="The caption identifies the two cohorts.")
            role=data["role"]
            seen[role]=task
            self.assertTrue(task.startswith(reviewer_prompt(role)))
            self.assertTrue(data["specialist_finding"]["source"]["page"])
            if role==INNOVATION:
                self.assertIn("comparison_coverage",data)
            if role==PRESENTATION:
                self.assertIn("text and captions only",data["presentation_evidence_mode"])
            return dict(summary="The paired evaluation supports publication within the two cohorts.",
                        score=6,confidence=3,strengths=["Paired comparison, p. 1."],weaknesses=[],questions=[],
                        specialist_finding="untrusted model echo",presentation_review={"mode":"fabricated"})
        events=[]
        chair=AsyncMock(return_value={"recommendation":"Accept"})
        with ExitStack() as stack:
            def stub(name,value):
                stack.enter_context(patch.object(workflow,name,value))
            for name in ("ranked_candidates","compare_contributions","check_manuscript","investigate"):
                stub(name,AsyncMock(return_value=[]))
            stub("ask",ask)
            stub("verify_many",lambda *a,**kw:[])
            stub("comparison_reviews",lambda *a:[])
            stub("verify_comparisons",AsyncMock())
            stub("discover",AsyncMock(return_value=([],[])))
            stub("assess_research_value",AsyncMock(return_value=None))
            stub("reviewer_passages",lambda p:{r:[dict(id="s",page=1,quote=quote)] for r in REVIEWER_ROLES})
            stub("chair_recommendation",chair)
            stub("outcomes",lambda *a:None)
            stub("protocol",lambda *a:{})
            stub("current_snapshot",lambda:None)
            stub("connect",no_tools)
            stack.enter_context(patch.dict("os.environ",REVIEWARENA_VISION="false"))
            result=await workflow.run_review(self.paper,prepared_reading=prepared,on_stage=events.append,pdf_bytes=self.raw)
        self.assertEqual(len(set(seen.values())),5)
        self.assertEqual([r["role"] for r in result["reviews"]],list(REVIEWER_ROLES))
        for r in result["reviews"]:
            self.assertEqual(r["report"]["recommendation"],"Borderline accept")
            self.assertTrue(r["report"]["summary"] and r["report"]["specialist_finding"]["source"]["quote"])
            self.assertEqual("presentation_review" in r["report"],r["role"]==PRESENTATION)
        self.assertEqual(chair.await_args.args[1],result["reviews"])
        self.assertTrue(any("5/5" in s["label"] for s in events))
        self.assertTrue(all(0<=s["fraction"]<=1 for s in events))

    def test_complete_three_and_five_reviewer_demos_load(self):
        with TemporaryDirectory() as folder:
            path=Path(folder)/"review.json"
            for count in (3,5,4):
                path.write_text(json.dumps(dict(venue="ICLR",reviews=[{}]*count,request=dict(manuscript_sha256="pdf",before="date"))))
                if count==4:
                    with self.assertRaises(ValueError):
                        read_review_demo(path,"pdf","ICLR","date")
                else:
                    self.assertEqual(len(read_review_demo(path,"pdf","ICLR","date")["reviews"]),count)
