from unittest import TestCase

from reviewarena.reviewer_ui import weakness_cards


class WeaknessCardTests(TestCase):
    def test_merges_legacy_fields_and_retains_distinct_sources(self):
        quote = {"page": 4, "quote": "The system was tested on one site."}
        prior = {"title": "Baseline", "url": "https://example.org/paper", "quote": "Two other sites were tested."}
        report = {
            "weaknesses": [{"issue": "Limited diversity.", "pages": [4], "evidence": [dict(quote, id="1"), dict(quote, id="2"), prior]}],
            "weakness": ["Limited diversity.", "Dataset size is unclear."],
        }
        first, second = weakness_cards(report)
        self.assertEqual(first["pages"], [4])
        self.assertEqual([s["quote"] for s in first["sources"]], [quote["quote"], prior["quote"]])
        self.assertEqual(second, {"issue": "Dataset size is unclear.", "pages": [], "sources": []})

    def test_reference_ids_alone_are_not_paper_passages(self):
        report = {"weaknesses": [], "weakness": [{"issue": "Missing control.", "evidence_ids": ["page 5, excerpt 2.1"]}]}
        self.assertEqual(weakness_cards(report), [{"issue": "Missing control.", "pages": [], "sources": []}])

    def test_empty_and_plain_text_reports(self):
        self.assertEqual(weakness_cards({}), [])
        self.assertEqual(weakness_cards({"weaknesss": "Missing comparison."})[0]["issue"], "Missing comparison.")
