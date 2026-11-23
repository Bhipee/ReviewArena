"""Materialize the historical split and produce page-addressable labeling packets."""
import json
from pathlib import Path
import duckdb, pymupdf
from fetch import ROOT, RAW

def build():
    db=duckdb.connect(str(ROOT/'data/history.duckdb'))
    db.execute("""create or replace table papers as select paper_openreview_id id, title, abstract, paper_decision decision, venue, cast(split_part(venue,'/',2) as integer) as year from read_parquet(?) where venue like 'ICLR.cc/%/Conference' and split_part(venue,'/',2) between '2018' and '2023'""",[str(RAW/'papers.parquet')])
    db.execute("""create or replace table reviews as select n.review_openreview_id id,p.id paper_id,n.content,n.title from read_parquet(?) n join papers p on n.replyto_openreview_id=p.id and n.venue=p.venue where lower(n.title) like '%official review%'""",[str(RAW/'notes-*.parquet')])
    db.execute("""create or replace table replies as select n.review_openreview_id id,r.id review_id,n.content from read_parquet(?) n join reviews r on n.replyto_openreview_id=r.id where lower(n.writer) like '%author%'""",[str(RAW/'notes-*.parquet')])
    print(db.sql('select (select count(*) from papers),(select count(*) from reviews),(select count(*) from replies)').fetchall())
    db.close()

def packet(pdf):
    db=duckdb.connect(str(ROOT/'data/history.duckdb'),read_only=True)
    reviews=db.execute('select id, content from reviews where paper_id=? order by id',[pdf.stem]).fetchall()
    replies=db.execute('select id,review_id,content from replies where review_id in (select id from reviews where paper_id=?)',[pdf.stem]).fetchall()
    db.close()
    with pymupdf.open(pdf) as doc:
        pages=[' '.join(p.get_text().split()) for p in doc]
    return dict(paper_id=pdf.stem,pages=pages,reviews=dict(reviews),replies=replies)

def expand():
    data=ROOT/'data'
    dest=data/'packets-expanded'
    dest.mkdir(exist_ok=True)
    for folder in [data/'historical-preprints']+[data/f'iclr{year}' for year in range(2018,2023)]:
        manifest=folder/'manifest.json'
        if not manifest.exists():continue
        for r in json.loads(manifest.read_text()):
            paper=r['id']
            out=dest/(paper+'.json')
            if out.exists() or (data/'packets'/out.name).exists():continue
            pdf=folder/(paper+'.pdf')
            raw=packet(pdf)
            if not raw['reviews'] or not any(t.strip() for t in raw['pages']):continue
            raw['pdf_info']={'file':str(pdf.relative_to(data)),'url':r['url'],
                             'version':r.get('version','Historical OCR mirror; public version may differ from submission')}
            temp=out.with_suffix('.tmp');temp.write_text(json.dumps(raw,ensure_ascii=False));temp.replace(out)
    print(len(list(dest.glob('*.json'))),'additional page-addressable packets',flush=True)


if __name__=='__main__':
    if not (ROOT/"data/history.duckdb").exists():build()
    dest=ROOT/'data/packets';dest.mkdir(exist_ok=True)
    for f in sorted((ROOT/'data/iclr2023').glob('*.pdf')):
        out=dest/(f.stem+'.json')
        if not out.exists():
            tmp=out.with_suffix('.tmp');tmp.write_text(json.dumps(packet(f),ensure_ascii=False));tmp.replace(out)
    expand()
