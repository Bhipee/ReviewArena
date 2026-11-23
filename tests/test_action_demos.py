import json
from pathlib import Path
from tempfile import TemporaryDirectory
from unittest import TestCase
from unittest.mock import patch

from reviewarena.demos import (
    chair_inputs,
    demo_path,
    load_demo,
    read_review_demo,
    review_demo_path,
    save_demo,
    summary_inputs,
)
from reviewarena.summary_store import matching_summary, save_summary


class ActionDemoTests(TestCase):
    def setUp(self):
        folder = TemporaryDirectory()
        self.addCleanup(folder.cleanup)
        self.data = Path(folder.name)
        root = patch("reviewarena.demos.DATA", self.data)
        root.start()
        self.addCleanup(root.stop)

    def test_changed_review_inputs_cannot_reuse_result(self):
        inputs = ["pdf", "ICLR", "2024-10-01"]
        result = {
            "venue": "ICLR",
            "request": {"manuscript_sha256": "pdf", "before": inputs[2]},
            "reviews": [{}, {}, {}],
            "meta_review": {},
        }
        save_demo("review", inputs, result)
        self.assertEqual(read_review_demo(review_demo_path(*inputs), *inputs), result)
        self.assertIsNone(review_demo_path("pdf", "NeurIPS", inputs[2]))
        self.assertIsNone(load_demo("review", ["pdf", "ICLR", "2024-10-02"]))
        with self.assertRaises(ValueError):
            read_review_demo(demo_path("review", inputs), "other", "ICLR", inputs[2])
        self.assertNotEqual(
            chair_inputs(inputs, result),
            chair_inputs(inputs, dict(result, reviews=[{"score": 1}])),
        )

    def test_local_and_historical_summaries_check_example_file_and_order(self):
        examples = [
            {"content": b"old", "name": "Example.md", "summary": "short"},
            {"summary": "other"},
        ]
        inputs = summary_inputs("pdf", "instructions", examples)
        path = self.data / "summaries.db"
        save_summary(
            "paper", "pdf", "instructions", examples, "local", "past result", path
        )
        self.assertEqual(matching_summary(*inputs, path=path), "past result")
        self.assertIsNone(
            matching_summary(
                *summary_inputs("pdf", "instructions", examples[::-1]), path=path
            )
        )
        examples[0]["content"] = b"changed"
        self.assertIsNone(
            matching_summary(
                *summary_inputs("pdf", "instructions", examples), path=path
            )
        )

    def test_inputs_and_previous_completed_value_survive_failed_save(self):
        inputs = ["weekly-brief", "topic", {"note.md": "digest"}, None, ["note.md"]]
        save_demo("lab", inputs, {"points": ["one"]})
        with self.assertRaises(TypeError):
            save_demo("lab", inputs, object())
        self.assertEqual(load_demo("lab", inputs), {"points": ["one"]})
        self.assertIsNone(load_demo("lab", [*inputs[:-1], []]))
        self.assertEqual(len(list(demo_path("lab", inputs).parent.iterdir())), 1)

    def test_legacy_review_is_bound_to_its_filename_and_venue(self):
        path = self.data / "replays" / "pdf-ICLR-2024-10-01.json"
        path.parent.mkdir()
        path.write_text(json.dumps({"reviews": [{}, {}, {}], "venue": "ICLR"}))
        self.assertEqual(
            read_review_demo(path, "pdf", "ICLR", "2024-10-01")["request"]["before"],
            "2024-10-01",
        )
        with self.assertRaises(ValueError):
            read_review_demo(path, "pdf", "ICLR", "2024-10-02")
