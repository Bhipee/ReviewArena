"""Compare claim assignment on a fixed historical index without reading held-out reviews."""
import hashlib
import json
import os

from run import DATA,write
from reviewarena.claims import sentences
from reviewarena.kb import current_snapshot,search
from reviewarena.lab_reviewer import CONTRIBUTION
from reviewarena.paper import parse_pdf
from reviewarena.workflow import select_claim_candidates


def compare(claims,paper_type):
    groups=[]
    best={}
    for claim in claims:
        hits=search(claim['text'],20,claim_type=claim.get('claim_type',''),paper_type=paper_type)
        group={}
        for hit in hits:
            family=hit['family']
            row=dict(family=family,score=hit['score'],matched_claim=claim['text'])
            group[family]=row
            if family not in best or row['score']>best[family]['score']:best[family]=row
        groups.append(group)
    original=sorted(best.values(),key=lambda r:-r['score'])[:20]
    covered=select_claim_candidates(groups,20)
    previous={r['family']:r for r in original}
    if set(previous)!={r['family'] for r in covered}:raise ValueError('Changed families')
    return dict(claims=len(claims),families=len(covered),previous_claims=len({r['matched_claim'] for r in original}),
                current_claims=len({r['matched_claim'] for r in covered}),
                changed=sum(r['matched_claim']!=previous[r['family']]['matched_claim'] for r in covered),
                score_difference=sum(previous[r['family']]['score']-r['score'] for r in covered))


if __name__=='__main__':
    snapshot=current_snapshot()
    os.environ['REVIEWARENA_KB_SNAPSHOT']=str(snapshot)
    rows=[]
    for entry in json.loads((DATA/'iclr2025/manifest.json').read_bytes()):
        raw=(DATA/'iclr2025'/(entry['id']+'.pdf')).read_bytes()
        digest=hashlib.sha256(raw).hexdigest()
        if digest!=entry['sha256']:raise ValueError('Changed input '+entry['id'])
        paper=parse_pdf(raw)
        claims=[dict(text=s['quote'],page=s['page']) for s in sentences(paper) if CONTRIBUTION.search(s['quote'])][:3]
        rows.append(dict(id=entry['id'],sha256=digest,**compare(claims,'')))
    source=DATA/'eval-product-author-checks/k2ZVAzVeMP/D.json'
    result=json.loads(source.read_bytes())
    production=compare(result['claims'],result['paper_type'])
    result=dict(snapshot=snapshot.name,
          protocol='First three distinct attributable sentences in PDF order, no type prior; no review text used.',
          papers=rows,saved_review=dict(source_sha256=hashlib.sha256(source.read_bytes()).hexdigest(),**production))
    write(DATA/'metrics'/'claim-coverage'/snapshot.name/'results.json',result)
    write(DATA/'metrics/claim-coverage.json',result)
    print(len(rows),'papers;',sum(r['previous_claims'] for r in rows),'->',sum(r['current_claims'] for r in rows),'covered author statements;',sum(r['families'] for r in rows),'unchanged families;',production)
