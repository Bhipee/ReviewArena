import hashlib
import json
import sqlite3
import tempfile
import unittest
from pathlib import Path

from reviewarena.library import save_documents
from reviewarena.summary_store import (
    history,
    list_templates,
    load_template,
    save_summary,
    save_template,
    template_from_history,
)


class SummaryTemplateTests(unittest.TestCase):
    def setUp(self):
        temp = tempfile.TemporaryDirectory()
        self.addCleanup(temp.cleanup)
        self.store = Path(temp.name) / "summaries.sqlite3"
        self.library = Path(temp.name) / "library.sqlite3"

    def test_save_edit_and_copy_without_target(self):
        pairs = [
            {"summary": "中文示例", "content": b"reference", "name": "Example.md"},
            {"summary": "Style only"},
        ]
        original = save_template("Original", "Prompt A", pairs, path=self.store)
        self.assertEqual(history(path=self.store), [])
        loaded = load_template(original, self.store)
        self.assertEqual(loaded["examples"][0]["content"], b"reference")
        loaded["examples"][0]["summary"] = "Changed example"
        copy = save_template("Copy", "Prompt B", loaded["examples"], path=self.store)
        self.assertEqual(
            load_template(original, self.store)["examples"][0]["summary"], "中文示例"
        )
        save_template(
            "Renamed",
            "Prompt C",
            [pairs[1]],
            template_id=original,
            revision=loaded["revision"],
            path=self.store,
        )
        self.assertEqual(load_template(original, self.store)["examples"], [pairs[1]])
        self.assertEqual(
            load_template(copy, self.store)["examples"][0]["summary"], "Changed example"
        )
        with self.assertRaises(ValueError):
            save_template(
                "Stale",
                "Prompt A",
                [],
                template_id=original,
                revision=loaded["revision"],
                path=self.store,
            )

    def test_history_conversion_is_independent_of_editor_and_current_templates(self):
        pairs = [
            {"name": "ref.pdf", "content": b"%PDF-snapshot", "summary": "Example 1"}
        ]
        template = save_template("Template", "Instructions", pairs, path=self.store)
        run = save_summary(
            "Target.pdf", "target", "Instructions", pairs, "model", "output", self.store
        )
        save_template(
            "Template", "Changed", [], template_id=template, revision=1, path=self.store
        )
        created, missing = template_from_history(run, self.store, self.library)
        restored = load_template(created, self.store)
        self.assertFalse(missing)
        self.assertEqual(restored["prompt"], "Instructions")
        self.assertEqual(restored["examples"][0]["content"], b"%PDF-snapshot")
        with sqlite3.connect(self.store) as db:
            self.assertEqual(
                db.execute("SELECT count(*) FROM summary_references").fetchone()[0], 1
            )
        self.assertEqual(history(path=self.store)[0]["summary"], "output")

    def test_pre_template_history_recovers_exact_files_and_marks_missing(self):
        raw = "旧例子".encode("utf-8-sig")
        save_documents([("Library name.txt", raw)], self.library)
        old = [
            {
                "name": "ref.txt",
                "digest": hashlib.sha256(raw).hexdigest(),
                "summary": "Text example",
            },
            {"name": "missing.pdf", "digest": "oldhash", "summary": "PDF example"},
            {"summary": "No attachment"},
        ]
        with sqlite3.connect(self.store) as db:
            db.execute(
                "CREATE TABLE summaries (id INTEGER PRIMARY KEY,name TEXT,prompt TEXT,examples TEXT)"
            )
            db.execute(
                "INSERT INTO summaries VALUES (1,?,?,?)",
                ("Old.pdf", "Old prompt", json.dumps(old)),
            )
        self.assertEqual(list_templates(self.store), [])
        created, missing = template_from_history(1, self.store, self.library)
        self.assertEqual(missing, ["missing.pdf"])
        self.library.unlink()
        restored = load_template(created, self.store, self.library)["examples"]
        self.assertEqual(restored[0]["content"], raw)
        self.assertIsNone(restored[1]["content"])
        self.assertEqual(restored[2], old[2])
