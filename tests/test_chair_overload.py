import asyncio
from unittest import IsolatedAsyncioTestCase, TestCase
from unittest.mock import call, patch

import requests

from reviewarena.model import model_post
from reviewarena.workflow import chair_recommendation


def response(status, retry_after=None):
    result = requests.Response()
    result.status_code = status
    result._content = b"{}"
    result._content_consumed = True
    if retry_after is not None:
        result.headers["Retry-After"] = retry_after
    return result


class OverloadRetryTests(TestCase):
    def test_only_529_is_retried_at_most_twice(self):
        cases = [
            ([response(529), response(529), response(200)], [5, 10]),
            ([response(529), response(529), response(529)], [5, 10]),
            ([response(529, "24"), response(200)], [24]),
            ([response(529, "invalid"), response(403)], [5]),
            ([response(401)], []),
        ]
        for replies, delays in cases:
            with self.subTest(statuses=[r.status_code for r in replies]), \
                 patch("requests.Session.post", side_effect=replies) as post, \
                 patch("reviewarena.model.time.sleep") as sleep:
                result = model_post("https://example.invalid/chat/completions", json={"model": "test"})
                self.assertIs(result, replies[-1])
                self.assertEqual(post.call_count, len(replies))
                self.assertEqual(sleep.call_args_list, [call(s) for s in delays])
                if result.status_code == 529:
                    with self.assertRaises(requests.HTTPError):
                        result.raise_for_status()


class ChairConcurrencyTests(IsolatedAsyncioTestCase):
    async def test_all_observations_reach_verdict_with_two_in_flight(self):
        observations = ["Trial one", "Trial two", "Trial three", "Trial four", "Trial five"]
        reports = [dict(role="reviewer", report=dict(summary="Empirical evaluation",
                        weaknesses=observations, score=5))]
        active = peak = 0
        release_first = asyncio.Event()

        async def ask(prompt, **data):
            nonlocal active, peak
            if "observation" in data:
                active += 1
                peak = max(peak, active)
                await asyncio.sleep(0)
                if data["observation"] == observations[0]:
                    await asyncio.wait_for(release_first.wait(), 2)
                elif data["observation"] == observations[-1]:
                    release_first.set()
                active -= 1
                return dict(reach="central", mechanism=data["observation"])
            self.assertEqual(active, 0)
            self.assertEqual([f["mechanism"] for f in data["findings"]], observations)
            if "reviewers" in data:
                return {"recommendation": "Reject"}
            return dict(impact="This limits the evidence.", finding_id=1)

        with patch("reviewarena.workflow.ask", ask):
            result = await chair_recommendation("ICLR", reports, claims=[{"text":"test claim"}])
        self.assertEqual(peak, 2)
        self.assertEqual(result["recommendation"], "Reject")
