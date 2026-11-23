"""Recover title-matched paper versions posted publicly before the first archived review."""
import hashlib
import json
import re
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime
from email.utils import parsedate_to_datetime
from pathlib import Path

import duckdb
import pymupdf
import requests

from check_heldout_versions import replace_file
from heldout_mirror import DATA, normalize


def versions(arxiv):
    result=requests.get('https://arxiv.org/abs/'+arxiv,timeout=(15,45))
    result.raise_for_status()
    text=re.sub(r'<[^>]*>',' ',result.text)
    dates=re.findall(r'\[v(\d+)\]\s*([A-Z][a-z]{2},\s+\d{1,2}\s+[A-Z][a-z]{2}\s+\d{4}\s+[\d:]+\s+UTC)',text)
    return [(int(v),parsedate_to_datetime(d).isoformat()) for v,d in dates]


def forum_copy(paper,source):
    pid=paper['id']
    folder=DATA/'heldout-version-audit'
    path=folder/(pid+'.pdf')
    companion=folder/(pid+'.mirror-note.json')
    info=folder/(pid+'.json')
    if not (companion.exists() and path.exists() and info.exists()):return None
    note=json.loads(companion.read_text())
    metadata=json.loads(info.read_text())
    if note['forum']!=pid or normalize(note['title'])!=normalize(paper['title']):
        raise ValueError('Mirror note does not identify the expected submission')
    raw=path.read_bytes()
    if hashlib.sha256(raw).hexdigest()!=metadata['sha256']:raise ValueError('Mirror file changed: '+pid)
    with pymupdf.open(stream=raw,filetype='pdf') as pdf:
        if normalize(paper['title']) not in normalize(pdf[0].get_text()[:2300]):return None
        match=re.search(r'(\d{8})',pdf.metadata.get('creationDate') or '')
    if not match:return None
    created=datetime.strptime(match[1],'%Y%m%d').date().isoformat()
    if created>=source['first_archived_review'][:10]:return None
    return dict(id=pid,decision=paper['decision'],path=str(path.relative_to(DATA)),source=note['pdf_url'],
                sha256=metadata['sha256'],pdf_created=created,timing='Forum-linked PDF created before first review',
                first_review=source['first_archived_review'])


def main():
    folder=DATA/'iclr2025-early'
    folder.mkdir(exist_ok=True)
    primary=json.loads((DATA/'iclr2025/manifest.json').read_text())
    audit={r['id']:r for r in json.loads((DATA/'metrics/heldout-input-versions.json').read_text())}
    with duckdb.connect() as db:
        rows=db.execute("select distinct paper_openreview_id,arxiv_id from read_parquet(?) where paper_openreview_id in (select unnest(?)) and arxiv_id is not null order by 1,2",
                        [str(DATA/'raw/arxiv.parquet'),list(audit)]).fetchall()
    mapping={pid:re.sub(r'v\d+$','',uri.split('/')[-1]) for pid,uri in rows}
    def recover(paper):
        pid=paper['id'];source=audit[pid]
        if source['timing'] in ('pre-review arXiv v1','PDF created before first review'):
            return dict(id=pid,decision=paper['decision'],path='iclr2025/'+pid+'.pdf',sha256=source['sha256'],
                        source=paper['url'],timing=source['timing'],first_review=source['first_archived_review'])
        aid=mapping.get(pid)
        if not aid or not re.fullmatch(r'\d{4}\.\d{4,5}',aid):
            return forum_copy(paper,source) or dict(id=pid,excluded='No earlier linked PDF or arXiv identifier')
        threshold=source['first_archived_review'].split()[0]
        for v,date in sorted(versions(aid),reverse=True):
            if date[:10]>=threshold:continue
            url=f'https://arxiv.org/pdf/{aid}v{v}'
            path=folder/(pid+f'-v{v}.pdf')
            if path.exists():raw=path.read_bytes()
            else:
                response=requests.get(url,timeout=(15,70));response.raise_for_status();raw=response.content
            with pymupdf.open(stream=raw,filetype='pdf') as pdf:
                correct=normalize(paper['title']) in normalize(pdf[0].get_text()[:2300])
            if not correct:continue
            if not path.exists():replace_file(path,raw)
            return dict(id=pid,decision=paper['decision'],path=str(path.relative_to(DATA)),source=url,
                        sha256=hashlib.sha256(raw).hexdigest(),timing='Public arXiv posting before first review',
                        posted=date,first_review=source['first_archived_review'])
        return forum_copy(paper,source) or dict(id=pid,excluded='No title-matched earlier forum copy or linked arXiv revision')
    with ThreadPoolExecutor(4) as pool:records=list(pool.map(recover,primary))
    replace_file(folder/'manifest.json',json.dumps(records,indent=2).encode())
    print('Eligible:',len([r for r in records if 'path' in r]),'of',len(records),flush=True)
    from collections import Counter
    print(Counter('rejected' if 'reject' in r['decision'].lower() else 'accepted' for r in records if 'path' in r))


if __name__=='__main__':main()
