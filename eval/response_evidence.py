"""Test the change in verifier output when a real author's timing table becomes available."""
import json
import os
import sys
from pathlib import Path
import pyarrow.parquet as pq
from run import DATA,write
from reviewarena.verifier import verify_many


def main():
    os.environ.setdefault('REVIEWARENA_PUBLIC_RUN_CACHE',str(DATA/'public-cache'))
    item=next(r for r in pq.read_table(DATA/'critique.parquet').to_pylist() if r['review_id']=='8kPD1A88u9')
    packet=json.loads((DATA/'packets'/(item['paper_id']+'.json')).read_text())
    assert item['trigger_text'] in packet['pages'][item['trigger_page']-1]
    raw_reply=next(raw for note,parent,raw in packet['replies'] if (note,parent)==(item['reply_id'],item['review_id']))
    quote=item['reply_strategy_quote']
    field=next(s for s in json.loads(raw_reply).values() if isinstance(s,str) and quote in s)
    offset=field.index(quote)
    # Preserve the entire table in the original reply, stopping at its following paragraph.
    table=field[offset:].split('\n\n',1)[0].strip()
    if 'NTK-SAP' not in table or 'SNIP' not in table:
        table=field[offset:offset+1800]
    assert 'NTK-SAP' in table and 'SNIP' in table and table in field
    result={}
    for name,pages in [('manuscript_excerpt',[item['trigger_text']]),('excerpt_and_author_response',[item['trigger_text'],table])]:
        checked=verify_many({'pages':pages},[item])[0]
        for ev in checked['evidence']:
            assert ev['quote'] in pages[ev['page']-1]
        result[name]=dict(status=checked['status'],reason=checked['reason'],evidence=checked['evidence'])
    for condition,question in [
        ('pruning_only_with_table','How long does NTK-SAP pruning take relative to Iterative SNIP on CIFAR-10?'),
        ('matched_end_to_end_with_table','What are the measured end-to-end training times for NTK-SAP and Iterative SNIP on CIFAR-10?')]:
        check=verify_many({'pages':[item['trigger_text'],table]},[dict(item,transfer_question=question)])[0]
        for ev in check['evidence']:
            assert ev['quote'] in [item['trigger_text'],table][ev['page']-1]
        result[condition]=dict(question=question,status=check['status'],reason=check['reason'],evidence=check['evidence'])
    write(DATA/'metrics/verifier-response-evidence-current.json',
          dict(paper=item['paper_id'],review=item['review_id'],reply=item['reply_id'],manuscript_page=item['trigger_page'],
               question=item['transfer_question'],source_text=[item['trigger_text'],table],conditions=result,
               scope='Two supplied excerpts. Page 1 denotes the manuscript excerpt and page 2 denotes the linked response.'))
    print({name:r['status'] for name,r in result.items()},flush=True)


if __name__=='__main__':main()
