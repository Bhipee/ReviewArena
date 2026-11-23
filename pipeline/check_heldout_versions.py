"""Audit the 50 inputs against submission titles, reviewer timestamps and public PDF dates."""
import argparse
import hashlib
import json
import re
import tempfile
from datetime import datetime
from pathlib import Path

import duckdb
import pymupdf
from heldout_mirror import DATA, normalize


def replace_file(path, raw):
    with tempfile.NamedTemporaryFile(dir=path.parent,delete=False) as stream:
        stream.write(raw)
        temp=Path(stream.name)
    temp.replace(path)


def main(repair):
    folder=DATA/'iclr2025'
    archive=DATA/'heldout-version-audit'
    manifest=folder/'manifest.json'
    papers=json.loads(manifest.read_bytes())
    if len(papers)!=50 or len({p['id'] for p in papers})!=50:raise ValueError('Expected 50 unique manuscripts')
    with duckdb.connect() as db:
        times=dict(db.execute("""select replyto_openreview_id,min(time) from read_parquet(?)
            where replyto_openreview_id in (select unnest(?)) and (writer ilike '%reviewer%' or title ilike '%official review%')
            group by replyto_openreview_id""",[str(DATA/'raw/notes-*.parquet'),[p['id'] for p in papers]]).fetchall())
    changes=[]
    records=[]
    for paper in papers:
        pid=paper['id']
        target=folder/(pid+'.pdf')
        raw=target.read_bytes()
        with pymupdf.open(stream=raw,filetype='pdf') as pdf:
            title_ok=normalize(paper['title']) in normalize(pdf[0].get_text()[:2300])
        if not title_ok and repair:
            meta=json.loads((archive/(pid+'.json')).read_text())
            companion=json.loads((archive/(pid+'.mirror-note.json')).read_bytes())
            if companion['forum']!=pid or normalize(companion['title'])!=normalize(paper['title']):
                raise ValueError('Different forum or title for '+pid)
            candidate=archive/(pid+'.arxiv-v4.pdf')
            if candidate.exists():
                url=paper['url'].removesuffix('v1')+'v4'
                note='Title-matched arXiv v4 predating review; may differ from the submitted manuscript.'
            else:
                candidate=archive/(pid+'.pdf')
                if hashlib.sha256(candidate.read_bytes()).hexdigest()!=meta['sha256']:raise ValueError('Mirror archive checksum mismatch')
                url=companion['pdf_url']
                note='ICLR 2025 forum-linked PDF mirror; revision identity may differ from the first submission.'
            replacement=candidate.read_bytes()
            with pymupdf.open(stream=replacement,filetype='pdf') as doc:
                if normalize(paper['title']) not in normalize(doc[0].get_text()[:2300]):
                    raise ValueError('Replacement title mismatch')
                page_count=len(doc)
            if list((DATA/'eval-frozen'/pid).glob('[ABCD].json')):
                raise ValueError('Existing frozen results need a separate input version: '+pid)
            changes.append((target,raw,replacement))
            paper.update(url=url,pages=page_count,version=note,previous_url=paper['url'],
                         previous_sha256=hashlib.sha256(raw).hexdigest(),sha256=hashlib.sha256(replacement).hexdigest())
            if url==companion['pdf_url']:paper.update(archive_url=meta['archive'],archive_member=meta['entry'])
            raw=replacement
            title_ok=True
        with pymupdf.open(stream=raw,filetype='pdf') as doc:
            date_field=(doc.metadata or {}).get('creationDate') or ''
            match=re.search(r'(\d{8})',date_field)
            created=datetime.strptime(match[1],'%Y%m%d').date().isoformat() if match else None
            if len(doc)!=paper['pages']:raise ValueError('Page-count mismatch for '+pid)
        if paper.get('sha256') and paper['sha256']!=hashlib.sha256(raw).hexdigest():
            raise ValueError('Active manuscript bytes differ from the recorded version for '+pid)
        paper['sha256']=hashlib.sha256(raw).hexdigest()
        first=times.get(pid)
        if 'arxiv.org/pdf/' in paper['url'] and paper['url'].endswith('v1'):
            version=re.search(r'/(\d{2})(\d{2})\.\d+v1$',paper['url'])
            posted_month='20'+version[1]+'-'+version[2] if version else None
            status='pre-review arXiv v1' if posted_month and first and posted_month<first[:7] else 'unknown'
        elif first and created:
            status='PDF created before first review' if created<first[:10] else 'PDF created on or after first review'
        else:status='unknown'
        if not title_ok:status='unmatched title'
        paper['timing_audit']=status
        records.append(dict(id=pid,title_match=title_ok,decision=paper['decision'],sha256=hashlib.sha256(raw).hexdigest(),
                            pdf_created=created,first_archived_review=first,timing=status))
    if changes:
        backup=archive/'original-manifest.json'
        if not backup.exists():replace_file(backup,manifest.read_bytes())
        for path,raw,replacement in changes:
            backup=archive/(path.stem+'.original.pdf')
            if backup.exists() and backup.read_bytes()!=raw:raise ValueError('Different backup already exists: '+str(backup))
            if not backup.exists():replace_file(backup,raw)
            replace_file(path,replacement)
    if repair:replace_file(manifest,json.dumps(papers,indent=2).encode())
    replace_file(DATA/'metrics/heldout-input-versions.json',json.dumps(records,indent=2).encode())
    from collections import Counter
    print('Title matches',sum(r['title_match'] for r in records),'of',len(records),'replacements',len(changes))
    print(Counter(r['timing'] for r in records))


if __name__=='__main__':
    parser=argparse.ArgumentParser()
    parser.add_argument('--repair',action='store_true')
    main(parser.parse_args().repair)
