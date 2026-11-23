"""Match mirrored ICLR PDFs by normalized title and retain source provenance."""
import json, random, re
from pathlib import Path
from concurrent.futures import ThreadPoolExecutor
from urllib.parse import quote
import duckdb, requests, pymupdf
from fetch import RAW, ROOT, download

def slug(s):
    return re.sub('[^a-z0-9]', '', s.lower())

def main(year, limit):
    repo = f"SlowGuess/ICLR_{year}_OCR"
    meta = requests.get(f"https://huggingface.co/api/datasets/{repo}", timeout=90)
    meta.raise_for_status()
    pdfs = {slug(p['rfilename'].split('/')[0]):p['rfilename'] for p in meta.json()['siblings'] if p['rfilename'].endswith('_origin.pdf')}
    records = duckdb.connect().execute("select paper_openreview_id,title,paper_decision from read_parquet(?) where venue=?", [str(RAW/'papers.parquet'),f'ICLR.cc/{year}/Conference']).fetchall()
    matches = [(i,title,dec,pdfs[slug(title)]) for i,title,dec in records if slug(title) in pdfs]
    random.Random(16).shuffle(matches)
    if year==2025:
        neg=[m for m in matches if 'reject' in m[2].lower()][:limit//2]
        pos=[m for m in matches if 'reject' not in m[2].lower() and 'withdraw' not in m[2].lower()][:limit//2]
        matches=pos+neg
    dest = ROOT/'data'/f'iclr{year}'
    dest.mkdir(exist_ok=True)
    def get(row):
        i,title,decision,path=row
        url=f"https://huggingface.co/datasets/{repo}/resolve/main/"+quote(path)
        filename=dest/f'{i}.pdf'
        try:
            download((url,filename))
            with pymupdf.open(filename) as pdf: pages=len(pdf)
            return dict(id=i,title=title,decision=decision,url=url,pages=pages,year=year)
        except (requests.RequestException,RuntimeError) as exc:
            print(i,str(exc)[:200],flush=True)
    with ThreadPoolExecutor(5) as pool:
        out=[r for r in pool.map(get,matches[:limit]) if r]
    (dest/'manifest.json').write_text(json.dumps(out,indent=2))
    print(year,'matched',len(matches),'downloaded',len(out),flush=True)

if __name__=='__main__':
    import sys
    main(int(sys.argv[1]),int(sys.argv[2]))
