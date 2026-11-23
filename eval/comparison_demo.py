"""Reproduce a public reviewer request and verify the comparison present in a later PDF."""
import asyncio
import json
import os

import pyarrow.parquet as pq

from run import DATA,write
from reviewarena.comparison_reader import inspect_comparison
from reviewarena.kb import current_snapshot
from reviewarena.paper import parse_pdf
from reviewarena.workflow import ask


async def main():
    os.environ.setdefault('REVIEWARENA_PUBLIC_RUN_CACHE',str(DATA/'public-cache'))
    paper_id='3KWnuT-R1bh'
    row=next(r for r in pq.read_table(current_snapshot()/'critique.parquet').to_pylist()
             if r['paper_id']==paper_id and 'ConViT' in r['critique_text'] and 'CoAtNet' in r['critique_text'])
    source=json.loads((DATA/'packets'/f'{paper_id}.json').read_bytes())
    comment=row['critique_text']
    review=json.loads(source['reviews'][row['review_id']])
    if not any(comment in str(v) for v in review.values()):raise ValueError('Reviewer quote changed')
    paper=parse_pdf((DATA/'iclr2023'/(paper_id+'.pdf')).read_bytes())
    result=await inspect_comparison(paper,comment,'2022-10-01',ask)
    for work in result['works']:
        for passage in work['bibliography']+work['comparison_passages']:
            if passage['quote'] not in paper['pages'][passage['page']-1]:raise ValueError('Source passage changed')
    if {w['mention'] for w in result['works'] if w['catalog_record'] and w['comparison_passages']}!={'ConViT','CoAtNet'}:
        raise ValueError('Could not verify both requested works and their table passages: '+repr(result['works'])[:1700])
    record=dict(paper_id=paper_id,title=row['title'],historical_review=row['source'],result=result)
    write(DATA/'metrics/reviewer-comparison-demo.json',record)
    print([(w['mention'],w['catalog_record']['published'],w['comparison_passages'][0]['page']) for w in result['works']])


if __name__=='__main__':
    asyncio.run(main())
