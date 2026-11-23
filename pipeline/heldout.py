"""Supplement the accepted PDF mirror with pre-submission rejected-paper preprints."""
from fetch import ROOT,RAW,download
import re,json,random
from urllib.parse import urlparse
import duckdb,pymupdf,requests
def main():
    dest=ROOT/'data/iclr2025';manifest=dest/'manifest.json'
    existing=json.loads(manifest.read_text())
    if len(existing)==50 and all(r.get('timing_audit') for r in existing):
        print('Keeping the version-audited held-out sample:',manifest)
        return
    rows=[r for r in existing if 'reject' not in r['decision'].lower()]
    download(('https://huggingface.co/datasets/ulab-ai/ResearchArcade-openreview-arxiv/resolve/main/data/train-00000-of-00001.parquet',RAW/'arxiv.parquet'))
    query="""select distinct a.arxiv_id,r.paper_id,r.title from read_parquet(?) a join read_parquet(?) r on r.paper_id=a.paper_openreview_id where r.year='2025' and decision='Reject' and a.arxiv_id is not null"""
    candidates=duckdb.connect().execute(query,[str(RAW/'arxiv.parquet'),str(RAW/'reviews.parquet')]).fetchall()
    rng=random.Random(16);candidates.sort();rng.shuffle(candidates)
    count=0
    for uri,i,title in candidates:
        aid=re.sub(r'v\d+$','',urlparse(uri).path.split('/')[-1])
        if not re.fullmatch(r'\d{4}\.\d{4,5}',aid) or aid[:4]>'2409':continue
        url='https://arxiv.org/pdf/'+aid+'v1';path=dest/(i+'.pdf')
        try:
            download((url,path))
            with pymupdf.open(path) as pdf:pages=len(pdf)
        except (requests.RequestException,RuntimeError):continue
        rows.append(dict(id=i,title=title,decision='Reject',url=url,pages=pages,year=2025,version='arXiv v1 before submission month; may differ from submitted version'))
        count+=1
        if count==25:break
    tmp=manifest.with_suffix('.tmp');tmp.write_text(json.dumps(rows,indent=2));tmp.replace(manifest)
    print(len(rows),'held-out papers',count,'rejected')
if __name__=='__main__':main()
