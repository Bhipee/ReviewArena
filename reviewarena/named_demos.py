"""Local, immutable copies of completed workspace results for presentation."""
from contextlib import closing
import hashlib
import json
import sqlite3

from .kb import DATA

ARCHIVE = DATA / "private" / "named-demos.sqlite3"
DEMO_TABLE = """CREATE TABLE IF NOT EXISTS demos (
    id INTEGER PRIMARY KEY AUTOINCREMENT, workspace TEXT NOT NULL, name TEXT NOT NULL,
    created TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP, view TEXT NOT NULL)"""


def save_named_demo(workspace, name, view, files, path=None):
    name = name.strip()
    if not name:
        raise ValueError("Enter a demo name.")
    path = path or ARCHIVE
    path.parent.mkdir(parents=True, exist_ok=True)
    with closing(sqlite3.connect(path)) as db, db:
        db.execute(DEMO_TABLE)
        db.execute("CREATE TABLE IF NOT EXISTS files (digest TEXT PRIMARY KEY, content BLOB NOT NULL)")
        db.execute("""CREATE TABLE IF NOT EXISTS attachments (
            demo INTEGER NOT NULL, label TEXT NOT NULL, digest TEXT NOT NULL, PRIMARY KEY(demo,label))""")
        demo_id = db.execute("INSERT INTO demos(workspace,name,view) VALUES(?,?,?)",
                             (workspace, name, json.dumps(view, ensure_ascii=False))).lastrowid
        for label, content in files.items():
            digest = hashlib.sha256(content).hexdigest()
            db.execute("INSERT OR IGNORE INTO files VALUES(?,?)", (digest, content))
            db.execute("INSERT INTO attachments VALUES(?,?,?)", (demo_id, label, digest))
    return demo_id


def list_named_demos(workspace, path=None):
    path = path or ARCHIVE
    if not path.is_file():
        return []
    with closing(sqlite3.connect(path)) as db:
        if not db.execute("SELECT 1 FROM sqlite_master WHERE name='demos'").fetchone():
            return []
        return db.execute("SELECT id,name,created FROM demos WHERE workspace=? ORDER BY id DESC",
                          (workspace,)).fetchall()


def load_named_demo(workspace, demo_id, path=None):
    path = path or ARCHIVE
    if not path.is_file():
        raise ValueError("This saved demo is unavailable.")
    with closing(sqlite3.connect(path)) as db:
        db.execute("BEGIN")  # Read the snapshot and its attachments at the same point in time.
        row = db.execute("SELECT name,view FROM demos WHERE workspace=? AND id=?",
                         (workspace, demo_id)).fetchone()
        if not row:
            raise ValueError("This saved demo is unavailable in this workspace.")
        files = dict(db.execute("SELECT label,content FROM attachments JOIN files USING(digest) WHERE demo=?",
                                (demo_id,)))
    return dict(id=demo_id, name=row[0], view=json.loads(row[1]), files=files)


def delete_named_demo(workspace, demo_id, path=None):
    path = path or ARCHIVE
    if not path.is_file():
        return False
    with closing(sqlite3.connect(path)) as db, db:
        db.execute("BEGIN IMMEDIATE")
        schema = db.execute("SELECT sql FROM sqlite_master WHERE type='table' AND name='demos'").fetchone()
        if not schema or not db.execute("SELECT 1 FROM demos WHERE workspace=? AND id=?", (workspace, demo_id)).fetchone():
            return False
        if "AUTOINCREMENT" not in schema[0].upper():
            # Legacy archives could reuse the last deleted ID, including one still shown in another tab.
            db.execute("ALTER TABLE demos RENAME TO demos_before_delete")
            db.execute(DEMO_TABLE)
            db.execute("""INSERT INTO demos(id, workspace, name, created, view)
                          SELECT id, workspace, name, created, view FROM demos_before_delete""")
            db.execute("DROP TABLE demos_before_delete")
        digests = db.execute("SELECT DISTINCT digest FROM attachments WHERE demo=?", (demo_id,)).fetchall()
        db.execute("DELETE FROM attachments WHERE demo=?", (demo_id,))
        db.execute("DELETE FROM demos WHERE workspace=? AND id=?", (workspace, demo_id))
        db.executemany("""DELETE FROM files WHERE digest=? AND NOT EXISTS
                          (SELECT 1 FROM attachments WHERE attachments.digest=files.digest)""", digests)
    return True
