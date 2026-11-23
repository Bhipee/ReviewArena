"""Local, versioned research-group library for papers and meeting notes."""
import hashlib
import json
import os
import sqlite3
from contextlib import closing
from pathlib import Path
from .kb import DATA
from .paper import parse_pdf

DEFAULT_PATH=Path(os.environ.get('REVIEWARENA_LIBRARY_PATH',DATA/'private'/'group-library.sqlite3'))

def document(name,content):
    parsed=parse_pdf(content) if name.lower().endswith('.pdf') else {'pages':[content.decode('utf-8-sig')]}
    if not any(page.strip() for page in parsed['pages']):
        raise ValueError(f"{name} contains no text.")
    return parsed

def save_documents(files,path=DEFAULT_PATH):
    records=[]
    pdfs=[]
    for name,content in files:
        pages=document(name,content)['pages']
        fingerprint=hashlib.sha256(content).hexdigest()
        if name.lower().endswith('.pdf'):pdfs.append((fingerprint,content))
        records.append((Path(name).name,fingerprint,json.dumps(pages,ensure_ascii=False)))
    path.parent.mkdir(parents=True,exist_ok=True)
    with closing(sqlite3.connect(path)) as db,db:
        db.execute('create table if not exists documents(name text, digest text, pages text not null, primary key(name,digest))')
        db.execute('create table if not exists pdf_files(digest text primary key, content blob not null)')
        db.executemany('insert or ignore into pdf_files(digest,content) values(?,?)',pdfs)
        db.executemany('insert or ignore into documents(name,digest,pages) values(?,?,?)',records)

def list_documents(path=DEFAULT_PATH):
    if not path.exists():return []
    with closing(sqlite3.connect(path)) as db:
        return db.execute('select name,digest from documents order by name,digest').fetchall()

def read_documents(selected,path=DEFAULT_PATH):
    if not selected:return {}
    result={}
    with closing(sqlite3.connect(path)) as db:
        for name,digest in selected:
            row=db.execute('select pages from documents where name=? and digest=?',(name,digest)).fetchone()
            if row:
                result[f'{name} [{digest[:8]}]']={'pages':json.loads(row[0])}
    return result


def saved_pdf(digest,path=DEFAULT_PATH):
    if not path.exists():return None
    with closing(sqlite3.connect(path)) as db:
        if not db.execute("select 1 from sqlite_master where type='table' and name='pdf_files'").fetchone():
            return None
        row=db.execute('select content from pdf_files where digest=?',(digest,)).fetchone()
    return row[0] if row else None
