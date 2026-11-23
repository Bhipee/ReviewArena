"""Acquire a year-stratified rejected-paper supplement with conservative version matching."""
import hashlib
import json
import random
import re
import time
from urllib.parse import urlsplit
import duckdb
import pymupdf
import requests
from fetch import RAW,ROOT,download

DATA=ROOT/'data'


def folded(text):
    return ''.join(c for c in text.casefold() if c.isalnum())


def acquire(per_year=50):
    folder=DATA/'historical-preprints'
    folder.mkdir(exist_ok=True)
    manifest=folder/'manifest.json'
    saved={r['id']:r for r in json.loads(manifest.read_text())} if manifest.exists() else {}
    with duckdb.connect(str(DATA/'history.duckdb'),read_only=True) as db:
        rows=db.execute("""select distinct p.id,p.title,p.year,p.decision,a.arxiv_id
             from papers p join read_parquet(?) a on p.id=a.paper_openreview_id
             where lower(p.decision) like '%reject%' and a.arxiv_id is not null
             order by p.year,p.id,a.arxiv_id""",[str(RAW/'arxiv.parquet')]).fetchall()
    random.Random(16).shuffle(rows)
    for paper,title,year,decision,uri in rows:
        if paper in saved or sum(r['year']==year for r in saved.values())>=per_year:continue
        aid=re.sub(r'v\d+$','',urlsplit(uri).path.split('/')[-1])
        if not re.fullmatch(r'\d{4}\.\d{4,5}',aid) or aid[:4]>f'{(year-1)%100:02}09':continue
        url='https://arxiv.org/pdf/'+aid+'v1';path=folder/(paper+'.pdf')
        try:
            download((url,path))
            with pymupdf.open(path) as doc:
                text=folded(doc[0].get_text())
                title_key=folded(title)
                if len(title_key)<12 or title_key not in text[:2000]:continue
                pages=len(doc)
        except (requests.RequestException,RuntimeError):continue
        saved[paper]=dict(id=paper,title=title,year=year,decision=decision,pages=pages,url=url,
            sha256=hashlib.sha256(path.read_bytes()).hexdigest(),version='arXiv v1; title matched on page 1; posted before October of the submission year')
        temp=manifest.with_suffix('.tmp');temp.write_text(json.dumps(list(saved.values()),indent=2));temp.replace(manifest)
        if len(saved)%25==0:print('Admitted',len(saved),'title-matched manuscripts',flush=True)
        time.sleep(1)
    print('Verified rejected-paper sample by year:',{y:sum(r['year']==y for r in saved.values()) for y in range(2018,2024)})


if __name__=='__main__':acquire()
