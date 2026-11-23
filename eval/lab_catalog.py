"""Check that the cited identifier resolves to the recommended title in OpenAlex."""
import json
import re
import time
import unicodedata
from urllib.parse import urlsplit
import requests
from run import DATA,write


def normalize(s):
    return ''.join(c for c in unicodedata.normalize('NFKD',s).casefold() if c.isalnum())


def lookup(item):
    parsed=urlsplit(item['url'])
    if parsed.hostname in ('doi.org','dx.doi.org') and parsed.path.startswith('/10.'):
        key='https://doi.org'+parsed.path
    elif parsed.hostname=='openalex.org' and re.fullmatch('/W[0-9]+',parsed.path):
        key=parsed.path[1:]
    else:
        return dict(url=item['url'],title=item['title'],status='unsupported identifier')
    url='https://api.openalex.org/works/'+key
    resp=requests.get(url,params={'select':'id,doi,title,type,publication_date'},timeout=(8,20))
    if resp.status_code==404:return dict(url=item['url'],title=item['title'],status='unresolved')
    resp.raise_for_status();record=resp.json()
    same=normalize(record['title'])==normalize(item['title'])
    return dict(url=item['url'],title=item['title'],status='verified' if same else 'different title',record=record)


def main():
    root=DATA/'eval-lab-literature-v3'
    all_records=[]
    for p in sorted(root.glob('*/scholar-raw.json')):
        results=[]
        for item in json.loads(p.read_text())['answer']['external']:
            results.append(lookup(item))
            time.sleep(.12)
        write(p.parent/'identifier-audit.json',results)
        all_records.extend(results)
    counts={s:sum(r['status']==s for r in all_records) for s in sorted({r['status'] for r in all_records})}
    write(DATA/'metrics/lab-catalog-identifiers.json',dict(records=len(all_records),status=counts))
    print(counts,flush=True)


if __name__=='__main__':main()
