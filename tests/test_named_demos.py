import sqlite3
from contextlib import closing
from pathlib import Path
from tempfile import TemporaryDirectory
from unittest import TestCase
from unittest.mock import patch

from streamlit.testing.v1 import AppTest

from reviewarena.named_demos import delete_named_demo, list_named_demos, load_named_demo, save_named_demo


class NamedDemoTests(TestCase):
    def setUp(self):
        folder = TemporaryDirectory()
        self.addCleanup(folder.cleanup)
        self.path = Path(folder.name) / "private" / "demos.sqlite3"

    def test_workspaces_versions_and_shared_files(self):
        def save(workspace, score):
            return save_named_demo(workspace, "example", {"score": score}, {"paper": b"PDF"}, self.path)

        first = save("Manuscript review", 5)
        second = save("Manuscript review", 8)
        save("Rebuttal", None)
        self.assertEqual([r[0] for r in list_named_demos("Manuscript review", self.path)], [second, first])
        loaded = load_named_demo("Manuscript review", first, self.path)
        self.assertEqual(loaded["view"], {"score": 5})
        self.assertEqual(loaded["files"], {"paper": b"PDF"})
        with self.assertRaises(ValueError):
            load_named_demo("Rebuttal", first, self.path)
        with closing(sqlite3.connect(self.path)) as db:
            self.assertEqual(db.execute("SELECT COUNT(*) FROM files").fetchone(), (1,))

    def test_failed_save_does_not_publish_part_of_a_snapshot(self):
        with self.assertRaises(TypeError):
            save_named_demo("Rebuttal", "reply", {}, {"paper": b"PDF", "invalid": object()}, self.path)
        self.assertEqual(list_named_demos("Rebuttal", self.path), [])
        with closing(sqlite3.connect(self.path)) as db:
            self.assertEqual(db.execute("SELECT COUNT(*) FROM files").fetchone(), (0,))

    def test_delete_legacy_snapshot_keeps_shared_files_and_never_reuses_its_id(self):
        self.path.parent.mkdir(parents=True)
        with closing(sqlite3.connect(self.path)) as db, db:
            db.execute("""CREATE TABLE demos (id INTEGER PRIMARY KEY, workspace TEXT NOT NULL,
                       name TEXT NOT NULL, created TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP, view TEXT NOT NULL)""")
        keep = save_named_demo("Rebuttal", "same name", {}, {"paper": b"shared"}, self.path)
        drop = save_named_demo("Lab meeting", "same name", {}, {"paper": b"shared", "notes": b"unique"}, self.path)
        self.assertFalse(delete_named_demo("Rebuttal", drop, self.path))
        self.assertTrue(delete_named_demo("Lab meeting", drop, self.path))
        self.assertEqual(load_named_demo("Rebuttal", keep, self.path)["files"], {"paper": b"shared"})
        with closing(sqlite3.connect(self.path)) as db:
            self.assertEqual(db.execute("SELECT content FROM files").fetchall(), [(b"shared",)])
            self.assertEqual(db.execute("SELECT demo FROM attachments").fetchall(), [(keep,)])
        new = save_named_demo("Lab meeting", "same name", {}, {}, self.path)
        self.assertGreater(new, drop)
        self.assertFalse(delete_named_demo("Lab meeting", drop, self.path))
        self.assertEqual([row[0] for row in list_named_demos("Lab meeting", self.path)], [new])

    def test_row_delete_targets_the_right_demo_and_clears_only_its_playback(self):
        script = """
import streamlit as st
from reviewarena.named_demo_ui import demo_library
active = demo_library(st.expander("ForDemo"), "Rebuttal")
if active: st.write(active["view"]["reply"])
"""
        with patch("reviewarena.named_demos.ARCHIVE", self.path):
            first = save_named_demo("Rebuttal", "Same", {"reply": "first"}, {})
            second = save_named_demo("Rebuttal", "Same", {"reply": "second"}, {})
            app = AppTest.from_string(script).run()
            def click(key):
                app.button(key=key).click().run()
                self.assertFalse(app.exception)
            click(f"named-option-Rebuttal-{first}")
            click("named-load-Rebuttal")
            click(f"named-remove-Rebuttal-{second}")
            click(f"named-cancel-Rebuttal-{second}")
            self.assertEqual(len(list_named_demos("Rebuttal")), 2)
            click(f"named-remove-Rebuttal-{second}")
            click(f"named-confirm-Rebuttal-{second}")
            self.assertEqual(app.markdown[-1].value, "first")
            self.assertEqual([row[0] for row in list_named_demos("Rebuttal")], [first])
            click(f"named-remove-Rebuttal-{first}")
            click(f"named-confirm-Rebuttal-{first}")
            self.assertEqual(list_named_demos("Rebuttal"), [])
            self.assertNotIn("named-replay-Rebuttal", app.session_state)
            self.assertIn("No saved demos", app.caption[0].value)

    def test_save_and_load_in_a_new_blank_session(self):
        script = """
import streamlit as st
from reviewarena.named_demo_ui import demo_library, save_current_demo

workspace = "Rebuttal"
panel = st.expander("ForDemo")
active = demo_library(panel, workspace)
if active:
    st.write(active["view"]["reply"])
else:
    ready = st.checkbox("Completed")
    save_current_demo(panel, workspace, "Default name", {"reply": "Frozen reply"} if ready else None)
"""
        with patch("reviewarena.named_demos.ARCHIVE", self.path):
            current = AppTest.from_string(script).run()
            save_key = "named-save-Rebuttal"
            self.assertTrue(current.button(key=save_key).disabled)
            current.checkbox[0].check().run()
            current.text_input[0].set_value("Class demo").run()
            current.button(key=save_key).click().run()
            self.assertFalse(current.exception)
            self.assertIn("Class demo", current.success[0].value)
            fresh = AppTest.from_string(script).run()
            self.assertTrue(fresh.button(key=save_key).disabled)
            fresh.button(key="named-load-Rebuttal").click().run()
            self.assertFalse(fresh.exception)
            self.assertEqual(fresh.markdown[-1].value, "Frozen reply")
            fresh.button(key="named-exit-Rebuttal").click().run()
            self.assertTrue(fresh.button(key=save_key).disabled)
