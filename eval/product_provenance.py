"""Verify both ends of the held-out product's historical-review-to-manuscript links."""
import json
from collections import Counter

import duckdb
import pyarrow.parquet as pq
import pymupdf

from run import DATA, write
from reviewarena.paper import parse_pdf


def strings(v):
    if isinstance(v, str):
        yield v
    elif isinstance(v, (list, dict)):
        for item in v.values() if isinstance(v, dict) else v:
            yield from strings(item)


def audit():
    folder=DATA/'eval-product-heldout-four'
    plan=json.loads((folder/'plan.json').read_bytes())
    snapshot=DATA/'index-snapshots'/plan['index']/'critique.parquet'
    historical={r['id']:r for r in pq.read_table(snapshot).to_pylist()}
    counts=Counter()
    checked_pages={}
    papers=[]
    with duckdb.connect(str(DATA/'history.duckdb'),read_only=True) as db:
        for p in plan['manuscripts']:
            run=folder/p['id']/'D.json'
            if not run.exists():
                continue
            result=json.loads(run.read_bytes())
            target=parse_pdf((DATA/'iclr2025'/(p['id']+'.pdf')).read_bytes())
            if (target['hash']!=p['sha256'] or result['request']['manuscript_sha256']!=target['hash']
                    or result['protocol']!=plan['protocol']):
                raise ValueError('Unexpected manuscript or model protocol: '+p['id'])
            for check in result['checked']:
                c=check['candidate']
                src=historical[c['id']]
                fields=('paper_id','review_id','critique_text','trigger_text','trigger_page','source','year')
                if not all(c[key]==src[key] for key in fields) or not 2018<=c['year']<=2023:
                    raise ValueError('Unexpected historical record: '+c['id'])
                pdf=(c.get('pdf_info') or {}).get('file') or f"iclr{c['year']}/{c['paper_id']}.pdf"
                page_key=(pdf,c['trigger_page'])
                if page_key not in checked_pages:
                    with pymupdf.open(DATA/pdf) as doc:
                        checked_pages[page_key]=' '.join(doc[c['trigger_page']-1].get_text().split())
                if c['trigger_text'] not in checked_pages[page_key]:
                    raise ValueError('Historical passage absent: '+c['id'])
                record=db.execute('select content from reviews where paper_id=? and id=?',[c['paper_id'],c['review_id']]).fetchone()
                if not record or not any(c['critique_text'] in text for text in strings(json.loads(record[0]))):
                    raise ValueError('Historical reviewer quotation absent: '+c['id'])
                if not 1<=c['matched_claim_page']<=len(target['pages']) or c['matched_claim'] not in target['pages'][c['matched_claim_page']-1]:
                    raise ValueError('Current claim absent: '+p['id'])
                counts['retrieved_links']+=1
                counts['transferred_questions']+=bool(c.get('target_question'))
                for ev in check['evidence']:
                    if not 1<=ev['page']<=len(target['pages']) or not ev['quote'] or ev['quote'] not in target['pages'][ev['page']-1]:
                        raise ValueError('Current evidence missing: '+p['id'])
                    counts['verifier_quotations']+=1
            papers.append(p['id'])
    proof=dict(papers=papers,planned=len(plan['manuscripts']),historical_index=plan['index'],counts=counts)
    write(folder/'source-audit.json',proof)
    print(proof)


if __name__=='__main__':
    audit()
