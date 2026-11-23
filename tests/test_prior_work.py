import unittest
from unittest.mock import AsyncMock, patch, Mock

import mcp_scholar_server as server
from reviewarena.prior_work import discover
from reviewarena.novelty import compare_contributions


class DiscoveryTests(unittest.IsolatedAsyncioTestCase):
    async def test_empty_plan_still_searches_outside_corpus(self):
        scholar = AsyncMock(return_value=[])
        _, log = await discover(
            {"pages": ["A sparse classifier"]},
            [{"text": "Sparse classification using nearest prototypes."}],
            "2024-01-01",
            scholar,
            AsyncMock(return_value={}),
        )
        self.assertTrue(log)
        self.assertTrue(scholar.call_args.kwargs["topic"])

    async def test_search_trace_excludes_unverified_citations_and_later_records(self):
        paper = {
            "pages": [
                "Example study",
                "REFERENCES A. Author. A grounded baseline. 2021.",
            ],
            "sections": [dict(heading="REFERENCES", start_page=2, end_page=2)],
        }
        hit = dict(
            title="A grounded baseline",
            url="https://example.org/old",
            abstract="Evidence for a mechanism.",
            published="2021-01-01",
        )
        scholar = AsyncMock(
            side_effect=[
                [hit, dict(hit, title="Later", published="2024-01-01")],
                RuntimeError("unavailable"),
            ]
        )
        ask = AsyncMock(
            return_value={
                "titles": ["A grounded baseline", "Invented title"],
                "topics": ["prototype classifiers"],
            }
        )
        rows, log = await discover(
            paper,
            [dict(text="Different types of classifier.")],
            "2024-01-01",
            scholar,
            ask,
        )
        self.assertEqual([r["title"] for r in rows], [hit["title"]])
        self.assertTrue(rows[0]["cited_in_manuscript"])
        self.assertEqual([r["status"] for r in log], ["complete", "unavailable"])

    async def test_selects_exact_fulltext_passage_and_labels_unresolved(self):
        claim = "The model routes the input to an expert."
        prior = "The router sends each input to one expert network."
        study = dict(
            title="Experts",
            url="https://arxiv.org/abs/2001.00001",
            published="2020-01-01",
            updated="2025-01-01",
            abstract="Evidence only added after the cutoff.",
            catalog="arXiv",
        )
        reader = AsyncMock(
            return_value=[
                dict(page=3, url="https://arxiv.org/pdf/2001.00001v1", quote=prior)
            ]
        )
        ask = AsyncMock(side_effect=[{"id": 1}, {"relation": "unclear"}])
        with patch("reviewarena.novelty.comparison_reviews", return_value=[]):
            results = await compare_contributions(
                dict(pages=[claim]),
                [dict(page=1, text=claim)],
                [study],
                "2024-01-01",
                ask,
                reader,
            )
        r = results[0]
        self.assertEqual(r["prior_page"], 3)
        self.assertEqual(r["prior_quote"], prior)
        self.assertEqual(r["status"], "Insufficient evidence")
        self.assertEqual(len(ask.call_args_list[0].kwargs["choices"]), 1)

    async def test_supported_technical_difference_and_validation_are_attributed(self):
        claim = "The model routes sparse inputs to the nearest prototype."
        prior = (
            "The earlier model routes sparse inputs with a learned linear classifier."
        )
        experiment = (
            "Replacing prototype routing with a linear classifier reduced accuracy."
        )
        study = dict(
            title="Linear routing for sparse inputs",
            abstract=prior,
            published="2020-01-01",
            url="https://example.org/linear",
        )
        model = AsyncMock(
            side_effect=[
                dict(id=1),
                dict(
                    relation_id=3,
                    comparison="One router selects the nearest prototype and the other uses a learned linear classifier.",
                    current_detail=claim,
                    prior_detail=prior,
                ),
                dict(code=1),
                dict(validation_quote=experiment),
            ]
        )
        paper = dict(
            pages=[claim, experiment],
            sections=[dict(heading="Results", excerpt=experiment)],
        )
        with patch("reviewarena.novelty.comparison_reviews", return_value=[]):
            rows = await compare_contributions(
                paper, [dict(text=claim, page=1)], [study], "2024-01-01", model
            )
        row = rows[0]
        self.assertEqual(
            (row["status"], row["prior_quote"], row["validation_page"]),
            ("distinct", prior, 2),
        )

    async def test_missing_experiment_in_one_passage_cannot_establish_novelty(self):
        claim = "Our model uses a sparse encoder and a balanced router."
        quote = "The sparse encoder uses a dense dictionary for decoding."
        school = dict(
            title="Sparse encoder",
            url="https://example.org/study",
            published="2022-01-01",
            abstract=quote,
        )
        llm = AsyncMock(
            side_effect=[
                {"id": 1},
                {
                    "relation_id": 3,
                    "comparison": "The prior paper does not mention a router.",
                    "current_detail": "uses a sparse encoder",
                    "prior_detail": "uses a dense dictionary",
                },
            ]
        )
        with patch("reviewarena.novelty.comparison_reviews", return_value=[]):
            rows = await compare_contributions(
                dict(pages=[claim]),
                [dict(page=1, text=claim)],
                [school],
                "2024-01-01",
                llm,
            )
        self.assertEqual(rows[0]["status"], "Insufficient evidence")
        self.assertEqual(rows[0]["prior_quote"], quote)

    async def test_different_measurements_are_not_a_technical_novelty(self):
        claim = "The sparse model lowers error at fixed compute."
        quote = "The sparse model lowers compute at fixed error."
        paper = dict(pages=[claim])
        source = dict(
            title="Sparse model",
            url="https://example.org/old",
            published="2021-01-01",
            abstract=quote,
        )
        model = AsyncMock(
            side_effect=[
                dict(id=1),
                dict(
                    relation_id=3,
                    comparison="The two studies fix different quantities.",
                    current_detail=claim,
                    prior_detail=quote,
                ),
                dict(code=3),
            ]
        )
        with patch("reviewarena.novelty.comparison_reviews", return_value=[]):
            rows = await compare_contributions(
                paper, [dict(page=1, text=claim)], [source], "2024-01-01", model
            )
        self.assertEqual(rows[0]["status"], "Different evaluation settings")

    async def test_evaluation_label_uses_original_excerpts_when_model_omits_details(
        self,
    ):
        claim = "The sparse model lowers error at fixed compute."
        quote = "The sparse model lowers compute at fixed error."
        source = dict(
            title="Sparse model",
            url="https://example.org/old",
            published="2021-01-01",
            abstract=quote,
        )
        model = AsyncMock(
            side_effect=[
                dict(id=1),
                dict(
                    relation_id=3,
                    comparison="Both models lower error at fixed compute.",
                ),
                dict(output=3),
            ]
        )
        with patch("reviewarena.novelty.comparison_reviews", return_value=[]):
            rows = await compare_contributions(
                dict(pages=[claim]),
                [dict(page=1, text=claim)],
                [source],
                "2024-01-01",
                model,
            )
        self.assertEqual(model.call_args.kwargs, dict(excerpt_a=claim, excerpt_b=quote))
        self.assertEqual(rows[0]["status"], "Different evaluation settings")
        self.assertNotIn("Both models lower error", rows[0]["comparison"])

    async def test_a_bad_model_title_does_not_drop_the_printed_baseline(self):
        paper = dict(
            pages=[
                "We compare against linear prototypes.",
                "REFERENCES Alice Smith. Linear prototypes. 2020.",
            ],
            sections=[dict(heading="References", start_page=2, end_page=2)],
        )
        scholar = AsyncMock(return_value=[])
        await discover(
            paper,
            [dict(text=paper["pages"][0])],
            "2024-01-01",
            scholar,
            AsyncMock(
                return_value=dict(
                    titles=["An invented paper"], topics=["prototype clustering"]
                )
            ),
        )
        calls = [(c.kwargs["query"], c.kwargs["topic"]) for c in scholar.call_args_list]
        self.assertIn(("Linear prototypes", False), calls)
        self.assertIn(("prototype clustering", True), calls)
        self.assertNotIn(("An invented paper", False), calls)


class CatalogTests(unittest.TestCase):
    def test_openalex_abstract_order_and_exclusive_date(self):
        arxiv = Mock(content=b"<feed/>")
        alex = Mock()
        hit = dict(
            id="id",
            doi=None,
            title="Prior",
            publication_date="2024-09-30",
            abstract_inverted_index={"it": [1, 3], "Use": [0], "with": [2]},
        )
        alex.json.return_value = {
            "results": [hit, dict(hit, title="Later", publication_date="2024-10-01")]
        }
        with patch.object(server.requests, "get", side_effect=[arxiv, alex]):
            rows = server._search_papers("technical keywords", "2024-10-01", 5, True)
        self.assertEqual(
            [(r["title"], r["abstract"]) for r in rows], [("Prior", "Use it with it")]
        )
