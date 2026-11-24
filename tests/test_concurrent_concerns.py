import asyncio
from contextvars import ContextVar
from threading import Barrier, Event, Lock, get_ident
from unittest import IsolatedAsyncioTestCase, TestCase
from unittest.mock import patch

import numpy as np

from reviewarena.transfer import adapt_questions
from reviewarena.verifier import verify_many


class QuestionScreeningTests(IsolatedAsyncioTestCase):
    async def test_groups_overlap_and_audit_uses_original_order(self):
        candidates = [dict(matched_claim=f"latency measurement {i}", critique_text="Is the timing comparable?")
                      for i in range(20)]
        unblock_first = asyncio.Event()
        active = peak = 0
        groups = []

        async def ask(prompt, items):
            nonlocal active, peak
            if prompt.startswith("Audit"):
                self.assertEqual(active, 0)
                self.assertEqual([item["source_claim"] for item in items],
                                 [c["matched_claim"] for c in candidates])
                return {"keep_ids": [1, 6, 11, 16]}
            active += 1
            peak = max(peak, active)
            groups.append(items[0]["claim"])
            if items[0]["claim"] == "latency measurement 0":
                await asyncio.wait_for(unblock_first.wait(), 3)
            else:
                await asyncio.sleep(0)
                unblock_first.set()
            active -= 1
            return {"questions": [dict(id=row["id"], anchor=row["claim"],
                                       question=f"How was {row['claim']} obtained?") for row in items]}

        rows = await adapt_questions(candidates, ask)
        self.assertEqual((peak, len(groups)), (2, 4))
        self.assertEqual([i for i, row in enumerate(rows) if row["target_question"]], [0, 5, 10, 15])


class EvidenceVerificationTests(TestCase):
    def test_bounded_overlap_keeps_evidence_order_progress_and_context(self):
        question_ids = ["first", "skip", "second", "third", "fourth"]
        candidates = [dict(category=i, target_question="" if i == "skip" else i) for i in question_ids]
        quote = "The measurement used a single device for every run."
        paper = {"pages": [quote]}
        context = ContextVar("test_review_id", default=None)
        context.set("current-review")
        lock = Lock()
        running = peak = 0
        both_started = Barrier(2)
        release_first = Event()
        audited = []
        progress = []
        caller = get_ident()

        def generate(task, payload):
            nonlocal running, peak
            self.assertEqual(context.get(), "current-review")
            if "quotation" in payload:
                with lock:
                    audited.append(payload["research_question"])
                return dict(relation="weakness", explanation="The measurement covers one device.")
            q = payload["question"]
            with lock:
                running += 1
                peak = max(peak, running)
            if q in ("first", "second"):
                both_started.wait(timeout=3)
            if q == "first":
                self.assertTrue(release_first.wait(timeout=3))
            with lock:
                running -= 1
            return dict(verdict="valid", refs=[1], quote=quote, reason=q)

        def on_verified(count):
            self.assertEqual(get_ident(), caller)
            progress.append(count)
            if count == 1:
                self.assertEqual(audited, ["second"])
                release_first.set()

        with patch("reviewarena.verifier.embed", side_effect=lambda texts: np.ones((len(texts), 1))), \
             patch("reviewarena.verifier.generate", side_effect=generate):
            rows = verify_many(paper, candidates, on_verified)
        self.assertEqual(peak, 2)
        self.assertEqual(progress, [1, 2, 3, 4])
        self.assertEqual([r["candidate"]["category"] for r in rows], question_ids)
        self.assertEqual([r["status"] for r in rows], ["valid", "not transferred", "valid", "valid", "valid"])
        self.assertCountEqual(audited, ["first", "second", "third", "fourth"])
        for row in rows:
            if row["status"] == "valid":
                self.assertEqual((row["evidence"][0]["page"], row["evidence"][0]["quote"]), (1, quote))
