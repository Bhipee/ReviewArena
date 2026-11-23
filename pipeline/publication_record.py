"""Prepare exact-title records from public arXiv abstracts for offline demonstrations."""
import argparse
import hashlib
import json
import re
import tempfile
import time
from datetime import date
from html.parser import HTMLParser
from pathlib import Path

import requests

ROOT=Path(__file__).resolve().parents[1]


class CitationMetadata(HTMLParser):
    def __init__(self):
        super().__init__()
        self.meta={}

    def handle_starttag(self,tag,attrs):
        if tag!='meta':return
        fields=dict(attrs)
        name=fields.get('name','')
        if name.startswith('citation_'):self.meta[name]=fields.get('content','')


def prepare(identifier):
    if not re.fullmatch(r'\d{4}\.\d{4,5}',identifier):raise ValueError('Expected an arXiv identifier')
    url='https://arxiv.org/abs/'+identifier
    response=requests.get(url,timeout=25)
    response.raise_for_status()
    parser=CitationMetadata()
    parser.feed(response.text)
    meta=parser.meta
    if meta.get('citation_arxiv_id','').split('v')[0]!=identifier:raise ValueError('The returned paper has a different identifier')
    title=' '.join(meta['citation_title'].split())
    published=date.fromisoformat(meta['citation_date'].replace('/','-')).isoformat()
    normalized=' '.join(re.findall(r'[a-z0-9]+',title.lower()))
    target=ROOT/'data/publication-records'/(hashlib.sha256(normalized.encode()).hexdigest()+'.json')
    target.parent.mkdir(exist_ok=True)
    record=dict(title=title,url=url,published=published,catalog='arXiv',arxiv_id=identifier,
                source_sha256=hashlib.sha256(response.content).hexdigest(),fetched_at=int(time.time()))
    with tempfile.NamedTemporaryFile(dir=target.parent,mode='w',delete=False) as out:
        json.dump(record,out,indent=2);temp=Path(out.name)
    temp.replace(target)
    print(title,published,url,flush=True)


if __name__=='__main__':
    p=argparse.ArgumentParser();p.add_argument('arxiv_ids',nargs='+')
    for identifier in p.parse_args().arxiv_ids:prepare(identifier)
