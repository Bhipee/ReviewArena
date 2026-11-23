import unittest
from unittest.mock import AsyncMock, patch

from reviewarena.workflow import assess_research_value


class ResearchValueTests(unittest.IsolatedAsyncioTestCase):
    async def test_requires_locatable_manuscript_evidence(self):
        claim = "Researchers can audit evaluation rankings with paired inputs."
        result = "Changing the format reversed the ranking of all four models."
        for quote, expected in [(result, 2), ("A different experiment proves a clinical benefit.", None)]:
            with self.subTest(quote=quote), patch('reviewarena.workflow.ask', new=AsyncMock(
                    return_value=dict(quote=quote, value='Format should be controlled in ranking studies.'))):
                value = await assess_research_value([claim, result], [dict(text=claim)], [dict(excerpt=result)])
                self.assertEqual(value['page'] if value else None, expected)
