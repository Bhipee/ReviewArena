import unittest
from unittest.mock import AsyncMock

from reviewarena.severity import check_rating


class SeverityTests(unittest.IsolatedAsyncioTestCase):
    async def test_reproducibility_conflict_is_a_reject(self):
        quotes = ['Stage two updates the encoder.', 'Stage two freezes the encoder.']
        finding = dict(kind='protocol', issue='Conflicting updates.',
                       evidence=[dict(page=i, quote=q) for i,q in enumerate(quotes,1)])
        ask = AsyncMock(side_effect=[dict(severity='fundamental', ref=1, rationale='Different models result.'),
                                     dict(resolved=False, resolution_quote='')])
        report = dict(score=5)
        await check_rating(report,'reviewer',[],[finding],quotes,{1:'Strong reject',3:'Reject',5:'Borderline reject'},ask)
        self.assertEqual(report['score'],3)
        self.assertEqual(report['rating_check']['initial_score'],5)

    async def test_alternative_models_do_not_lower_score(self):
        quotes = ['The baseline freezes its encoder.', 'Our method updates its encoder.']
        finding = dict(kind='protocol', issue='Different updates.',
                       evidence=[dict(page=i,quote=q) for i,q in enumerate(quotes,1)])
        report = dict(score=6)
        ask = AsyncMock()
        await check_rating(report,'reviewer',[],[finding],quotes,{1:'Strong reject',3:'Reject',6:'Borderline accept'},ask)
        ask.assert_not_awaited()
        self.assertEqual(report['score'],6)
