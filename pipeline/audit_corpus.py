"""Verify labelable historical manuscripts against page packets and archived official review threads."""
import hashlib
import json
import unicodedata
from collections import Counter
from pathlib import Path
import duckdb
import pymupdf
from fetch import ROOT

DATA=ROOT/'data'


def main():
    known=set()
    years=Counter()
    counts=Counter()
    heldout={r['id'] for r in json.loads((DATA/'iclr2025/manifest.json').read_text())}
    def norm(title):return ''.join(c for c in unicodedata.normalize('NFKD',title).casefold() if c.isalnum())
    test_rows=json.loads((DATA/'iclr2025/manifest.json').read_text())
    test_hashes={hashlib.sha256((DATA/'iclr2025'/(r['id']+'.pdf')).read_bytes()).hexdigest():r['id'] for r in test_rows}
    titles={norm(r['title']):r['id'] for r in test_rows}
    same_file=[];same_title=[]
    with duckdb.connect(str(DATA/'history.duckdb'),read_only=True) as db:
        for paper_id,title in db.execute('select id,title from papers').fetchall():
            if norm(title) in titles:same_title.append([paper_id,titles[norm(title)]])
        for folder in [DATA/f'iclr{y}' for y in range(2020,2024)]+[DATA/'historical-preprints']:
            manifest=json.loads((folder/'manifest.json').read_text())
            for row in manifest:
                pid=row['id']
                if pid in known or pid in heldout:raise ValueError(f'Duplicate or held-out ID: {pid}')
                known.add(pid)
                pdf=folder/(pid+'.pdf')
                digest=hashlib.sha256(pdf.read_bytes()).hexdigest()
                if digest in test_hashes:same_file.append([pid,test_hashes[digest]])
                if row.get('sha256') and row['sha256']!=digest:
                    raise ValueError(f'Manuscript version changed: {pid}')
                with pymupdf.open(pdf) as doc:
                    if len(doc)!=row['pages']:raise ValueError(f'Page count changed: {pid}')
                    pages=[' '.join(p.get_text().split()) for p in doc]
                db_paper=db.execute('select year,title,decision from papers where id=?',[pid]).fetchone()
                if db_paper!=(row['year'],row['title'],row['decision']):raise ValueError(f'Historical metadata mismatch: {pid}')
                reviews=dict(db.execute('select id,content from reviews where paper_id=?',[pid]).fetchall())
                if not reviews or not any(pages):
                    counts['no_review_or_text']+=1;continue
                packet_files=[d/(pid+'.json') for d in (DATA/'packets',DATA/'packets-expanded') if (d/(pid+'.json')).exists()]
                if len(packet_files)!=1:raise ValueError(f'Expected one packet for {pid}; got {len(packet_files)}')
                packet=json.loads(packet_files[0].read_text())
                replies=db.execute('select id,review_id,content from replies where review_id in (select id from reviews where paper_id=?)',[pid]).fetchall()
                if (packet['paper_id']!=pid or packet['pages']!=pages or packet['reviews']!=reviews or
                    sorted(tuple(r) for r in packet['replies'])!=sorted(replies)):
                    raise ValueError(f'Source text, review IDs or reply thread differ: {pid}')
                if info:=packet.get('pdf_info'):
                    if info['file']!=str(pdf.relative_to(DATA)) or info['url']!=row['url']:raise ValueError(f'PDF provenance differs: {pid}')
                counts.update(packets=1,pages=len(pages),reviews=len(reviews),replies=len(replies))
                years[row['year']]+=1
            print(folder.name,'audited;',counts['packets'],'packets',flush=True)
    result=dict(historical_pdfs=len(known),heldout_papers=len(heldout),overlapping_paper_ids=0,
                identical_pdf_pairs=same_file,identical_normalized_title_pairs=same_title,verified_by_year=years,**counts)
    path=DATA/'metrics'/'historical-source-audit.json'
    tmp=path.with_suffix('.tmp');tmp.write_text(json.dumps(result,indent=2));tmp.replace(path)
    print(result,flush=True)


if __name__=='__main__':main()
