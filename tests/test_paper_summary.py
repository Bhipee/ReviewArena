import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from reviewarena.paper_summary import chunks, history, save_summary, summarize


class PaperSummaryTests(unittest.TestCase):
    def test_prompt_and_examples_remain_paired(self):
        examples = [
            dict(
                paper=dict(pages=["Reference-only facts."]),
                summary="The reference summary.",
            ),
            dict(summary="Style-only example."),
        ]
        with patch(
            "reviewarena.paper_summary.complete", return_value="The target summary."
        ) as model:
            result = summarize(
                dict(pages=["Target-only facts."]), "Summarize in Chinese.", examples
            )
        self.assertEqual(result, "The target summary.")
        messages = model.call_args_list[0].args[0]
        self.assertNotIn(
            "Reference-only facts.", model.call_args.args[0][-1]["content"]
        )
        self.assertEqual(
            [m["role"] for m in messages],
            ["system", "user", "assistant", "user", "assistant", "user"],
        )
        self.assertIn("Summarize in Chinese.", model.call_args.args[0][-1]["content"])
        self.assertIn("Reference-only facts.", messages[1]["content"])
        self.assertIn("Target-only facts.", model.call_args.args[0][-1]["content"])

    def test_chunked_paper_includes_last_page(self):
        pages = ["initial observation " * 2100, "final-page observation"]
        seen = []

        def fake(messages, max_tokens=2400):
            seen.append(messages)
            return "concise notes"

        with patch("reviewarena.paper_summary.complete", side_effect=fake):
            summarize(
                dict(pages=pages), "Summarize.", [dict(summary="Example " * 1600)]
            )
        self.assertTrue(
            any("final-page observation" in m[-1]["content"] for m in seen[:-1])
        )
        self.assertIn("concise notes", seen[-1][-1]["content"])
        text = "中 文，" * 2000
        self.assertEqual("".join(chunks(text, 1000)), text)

    def test_history_keeps_versions_and_searches_saved_text(self):
        with tempfile.TemporaryDirectory() as folder:
            path = Path(folder) / "history.sqlite3"
            self.assertEqual(history(path=path), [])
            for output in ("旧版观察", "新版对照"):
                save_summary("Paper.pdf", "sha", "中文短评", [], "local", output, path)
            self.assertEqual(
                [r["summary"] for r in history("paper", path)], ["新版对照", "旧版观察"]
            )
            self.assertEqual(len(history("短评", path)), 2)
            self.assertEqual(len(history("对照", path)), 1)
