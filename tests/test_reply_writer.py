import unittest
from unittest.mock import AsyncMock
from reviewarena.reply_writer import compose_response, style_examples


class ReplyWriterTests(unittest.IsolatedAsyncioTestCase):
    def test_reads_and_deduplicates_actual_reply_text(self):
        history = [{'reply': '{"comment":"We address the two points separately."}'}] * 2
        self.assertEqual(style_examples(history), ['We address the two points separately.'])

    async def test_rejected_draft_cannot_add_a_commitment(self):
        ask = AsyncMock(side_effect=[
            {'response': 'We will compare patient identifiers and recruit 13 hospitals.'},
            {'unsupported_quote': 'and recruit 13 hospitals'},
        ])
        text = await compose_response(ask, {'title': 'Audit', 'pages': ['Audit']}, 'Any overlap?',
                                      None, 'Compare patient identifiers.', [])
        self.assertEqual(text, 'We will compare patient identifiers.')
