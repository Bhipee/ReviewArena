"""Build the Live paper-comparison index from the downloaded OpenReview snapshot."""
import json
import os
import sqlite3
import tempfile
import tarfile
import re
from datetime import datetime, timezone
from pathlib import Path

import duckdb

DATA = Path(__file__).resolve().parents[1] / 'data'


def review_excerpt(content):
    fields = {k.lower().replace(' ','_'):v for k,v in content.items()}
    for key in ('weaknesses','strength_and_weaknesses','strengths_and_weaknesses','questions','review','main_review','summary_of_the_review','summary','paper_summary'):
        value = fields.get(key)
        if isinstance(value,dict):
            value=value.get('value')
        if isinstance(value,str) and len(value.strip())>=40:
            return value.strip()[:1400]
    return ''


def extend_iclr(db, archive):
    db.executescript("""
        CREATE TEMP TABLE submissions(pid TEXT PRIMARY KEY,title TEXT,abstract TEXT,venue TEXT);
        CREATE TEMP TABLE extra_reviews(id TEXT PRIMARY KEY,pid TEXT,posted TEXT,excerpt TEXT);
    """)
    with tarfile.open(archive,'r|bz2') as tar:
        for member in tar:
            match=re.search(r'(?:^|/)iclr_(20[0-9]{2})/(papers|reviews)\.jsonl$',member.name)
            if not member.isfile() or not match:
                continue
            year,kind=match.groups()
            for line in tar.extractfile(member):
                note=json.loads(line)
                content=note['content']
                if kind=='papers':
                    title,abstract=[content.get(k,'') for k in ('title','abstract')]
                    title=title.get('value','') if isinstance(title,dict) else title
                    abstract=abstract.get('value','') if isinstance(abstract,dict) else abstract
                    if title:
                        db.execute('INSERT OR IGNORE INTO submissions VALUES(?,?,?,?)',(note['id'],title,abstract,'ICLR.cc/'+year+'/Conference'))
                elif note.get('_kind')=='Official_Review':
                    excerpt=review_excerpt(content)
                    timestamp=note.get('pdate') or note.get('cdate') or note.get('tcdate')
                    if excerpt and timestamp:
                        posted=datetime.fromtimestamp(timestamp/1000,timezone.utc).date().isoformat()
                        db.execute('INSERT OR IGNORE INTO extra_reviews VALUES(?,?,?,?)',(note['id'],note['_paper_forum'],posted,excerpt))
            print(member.name,flush=True)
    db.executescript("""
        CREATE INDEX temp.by_submission ON extra_reviews(pid);
        CREATE TEMP TABLE existing AS SELECT paper_id FROM papers;
        CREATE UNIQUE INDEX temp.existing_by_id ON existing(paper_id);
        INSERT INTO papers SELECT title,abstract,pid,venue FROM submissions s
            WHERE EXISTS(SELECT 1 FROM extra_reviews r WHERE r.pid=s.pid)
              AND NOT EXISTS(SELECT 1 FROM existing e WHERE e.paper_id=s.pid);
        INSERT OR IGNORE INTO reviews SELECT r.id,r.pid,r.posted,r.excerpt FROM extra_reviews r JOIN submissions s USING(pid);
    """)


def build():
    target = DATA / 'comparison-pool.sqlite'
    with tempfile.TemporaryDirectory(dir=DATA) as staging:
        output = Path(staging) / target.name
        with sqlite3.connect(output) as db, duckdb.connect() as source:
            db.executescript("""
                CREATE VIRTUAL TABLE papers USING fts5(title, abstract, paper_id UNINDEXED,
                                                       venue UNINDEXED, tokenize='porter unicode61');
                CREATE TABLE reviews(id TEXT PRIMARY KEY, paper_id TEXT, posted TEXT, excerpt TEXT);
                CREATE INDEX reviews_by_paper ON reviews(paper_id, posted);
            """)
            rows = source.execute("""
                SELECT p.paper_openreview_id, p.title, p.abstract, p.venue,
                       n.review_openreview_id, n.time, n.content
                FROM read_parquet(?) p JOIN read_parquet(?) n
                  ON p.paper_openreview_id=n.replyto_openreview_id AND p.venue=n.venue
                WHERE regexp_full_match(lower(p.venue), '[^/]+/[0-9]{4}/conference')
                  AND lower(n.title) LIKE '%official review%' AND n.time IS NOT NULL
                ORDER BY p.paper_openreview_id,n.review_openreview_id
            """, [str(DATA/'raw/papers.parquet'), str(DATA/'raw/notes-*.parquet')])
            previous = None
            while batch := rows.fetchmany(2000):
                for pid,title,abstract,venue,rid,posted,content in batch:
                    value = review_excerpt(json.loads(content))
                    if not value:
                        continue
                    if pid != previous:
                        db.execute('INSERT INTO papers VALUES(?,?,?,?)',(title,abstract,pid,venue))
                        previous = pid
                    db.execute('INSERT OR IGNORE INTO reviews VALUES(?,?,?,?)',(rid,pid,str(posted)[:10],value.strip()[:1400]))
            archive=DATA/'raw/iclr-openreview-2020-2026.tar.bz2'
            if archive.exists():
                extend_iclr(db,archive)
        os.replace(output,target)


if __name__=='__main__':
    build()
