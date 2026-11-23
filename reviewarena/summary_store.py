"""Local storage for summary runs, editable templates and their original reference files."""
import hashlib
import json
import sqlite3
from contextlib import closing, contextmanager

from .library import DEFAULT_PATH, saved_source

HISTORY = DEFAULT_PATH.with_suffix(".summaries.sqlite3")


@contextmanager
def writer(path):
    path.parent.mkdir(parents=True, exist_ok=True)
    with closing(sqlite3.connect(path)) as db, db:
        db.execute(
            """CREATE TABLE IF NOT EXISTS summaries (
            id INTEGER PRIMARY KEY, created TEXT DEFAULT CURRENT_TIMESTAMP,
            name TEXT, digest TEXT, prompt TEXT, examples TEXT, model TEXT, summary TEXT)"""
        )
        db.execute(
            """CREATE TABLE IF NOT EXISTS summary_templates (
            id INTEGER PRIMARY KEY, name TEXT NOT NULL, prompt TEXT NOT NULL,
            examples TEXT NOT NULL, revision INTEGER NOT NULL DEFAULT 1)"""
        )
        db.execute(
            """CREATE TABLE IF NOT EXISTS summary_references (
            digest TEXT PRIMARY KEY, content BLOB NOT NULL)"""
        )
        yield db


def pack_examples(db, examples):
    metadata = []
    for example in examples:
        item = {k: example[k] for k in ("summary", "name", "digest") if k in example}
        content = example.get("content")
        if content is not None:
            item["digest"] = hashlib.sha256(content).hexdigest()
            db.execute(
                "INSERT OR IGNORE INTO summary_references(digest, content) VALUES (?, ?)",
                (item["digest"], content),
            )
        metadata.append(item)
    return json.dumps(metadata, ensure_ascii=False)


def save_summary(name, digest, prompt, examples, model, summary, path=HISTORY):
    with writer(path) as db:
        return db.execute(
            "INSERT INTO summaries(name,digest,prompt,examples,model,summary) VALUES (?,?,?,?,?,?)",
            (name, digest, prompt, pack_examples(db, examples), model, summary),
        ).lastrowid


def history(query="", path=HISTORY):
    if not path.exists():
        return []
    with closing(sqlite3.connect(path)) as db:
        db.row_factory = sqlite3.Row
        return [
            dict(r)
            for r in db.execute(
                """
            SELECT * FROM summaries WHERE instr(lower(name),lower(?)) OR instr(lower(summary),lower(?))
            OR instr(lower(prompt),lower(?)) ORDER BY id DESC""",
                (query, query, query),
            )
        ]


def matching_summary(digest, prompt, example_pairs, path=HISTORY):
    """Return the latest summary for exactly the same source, prompt and example sequence."""
    if not path.is_file():
        return None
    with closing(sqlite3.connect(path)) as db:
        for encoded, result in db.execute(
            "SELECT examples, summary FROM summaries WHERE digest=? AND prompt=? ORDER BY id DESC",
            (digest, prompt),
        ):
            pairs = [[e["summary"], e.get("digest")] for e in json.loads(encoded)]
            if pairs == example_pairs:
                return result
    return None


def list_templates(path=HISTORY):
    if not path.exists():
        return []
    with closing(sqlite3.connect(path)) as db:
        if not db.execute(
            "SELECT 1 FROM sqlite_master WHERE type='table' AND name='summary_templates'"
        ).fetchone():
            return []  # Existing history databases predate templates.
        return db.execute(
            "SELECT id, name FROM summary_templates ORDER BY id DESC"
        ).fetchall()


def restore_examples(db, encoded, library_path):
    examples = json.loads(encoded)
    for example in examples:
        digest = example.get("digest")
        if digest:
            row = db.execute(
                "SELECT content FROM summary_references WHERE digest=?", (digest,)
            ).fetchone()
            example["content"] = row[0] if row else saved_source(digest, library_path)
    return examples


def load_template(template_id, path=HISTORY, library_path=DEFAULT_PATH):
    with closing(sqlite3.connect(path)) as db:
        db.row_factory = sqlite3.Row
        record = dict(
            db.execute(
                "SELECT * FROM summary_templates WHERE id=?", (template_id,)
            ).fetchone()
        )
        record["examples"] = restore_examples(db, record["examples"], library_path)
        return record


def save_template(
    name, prompt, examples, *, template_id=None, revision=None, path=HISTORY
):
    name = name.strip()
    if (
        not name
        or not prompt.strip()
        or any(not e["summary"].strip() for e in examples)
    ):
        raise ValueError(
            "Enter a template name, instructions and a summary for each example."
        )
    with writer(path) as db:
        values = (name, prompt, pack_examples(db, examples))
        if template_id is None:
            return db.execute(
                "INSERT INTO summary_templates(name,prompt,examples) VALUES (?,?,?)",
                values,
            ).lastrowid
        updated = db.execute(
            "UPDATE summary_templates SET name=?, prompt=?, examples=?, revision=revision+1 "
            "WHERE id=? AND revision=?",
            (*values, template_id, revision),
        )
        if not updated.rowcount:
            raise ValueError(
                "This template changed in another session. Reload it or save your edits as a new template."
            )
        return template_id


def template_from_history(history_id, path=HISTORY, library_path=DEFAULT_PATH):
    with writer(path) as db:
        name, prompt, encoded = db.execute(
            "SELECT name,prompt,examples FROM summaries WHERE id=?", (history_id,)
        ).fetchone()
        examples = restore_examples(db, encoded, library_path)
        title = f"{name} · summary #{history_id}"
        template_id = db.execute(
            "INSERT INTO summary_templates(name,prompt,examples) VALUES (?,?,?)",
            (title, prompt, pack_examples(db, examples)),
        ).lastrowid
        missing = [
            e["name"] for e in examples if e.get("name") and e.get("content") is None
        ]
        return template_id, missing
