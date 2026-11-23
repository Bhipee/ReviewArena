"""Evaluate the current verifier on four manuscripts outside the classroom example."""
import argparse
import asyncio
import hashlib
import json
import os
from collections import Counter

from run import DATA, main as run, write
from reviewarena.kb import accepted_decision
from reviewarena.paper import parse_pdf
from reviewarena.protocol import protocol


def digest(raw):
    return hashlib.sha256(raw).hexdigest()


async def main():
    namespace = 'eval-product-heldout-four'
    folder = DATA / namespace
    plan = folder / 'plan.json'
    manifest = json.loads((DATA / 'iclr2025/manifest.json').read_bytes())
    examples = [p for p in manifest if p['id'] != 'k2ZVAzVeMP']
    papers = []
    for accepted in (True, False):
        group = [p for p in examples if accepted_decision(p['decision']) == accepted]
        group.sort(key=lambda p: digest(('Group16-manuscript-check-' + p['id']).encode()))
        papers.extend(group[:2])
    if len(papers) != 4:
        raise ValueError('Expected two accepted and two rejected manuscripts')
    snapshot = json.loads((plan if plan.exists() else DATA / 'active-index.json').read_bytes())
    if isinstance(snapshot, dict):
        snapshot = snapshot['index']
    index = DATA / 'index-snapshots' / snapshot
    os.environ['REVIEWARENA_KB_SNAPSHOT'] = str(index)
    os.environ['REVIEWARENA_RUN_NAMESPACE'] = namespace
    frozen = dict(index=snapshot, protocol=protocol('D', 'ICLR', index),
                  manuscripts=[dict(id=p['id'], sha256=p['sha256'], decision=p['decision']) for p in papers])
    if plan.exists() and json.loads(plan.read_bytes()) != frozen:
        raise ValueError('The planned product protocol or held-out manuscripts changed')
    write(plan, frozen)
    results = []
    for p in papers:
        raw = (DATA / 'iclr2025' / (p['id'] + '.pdf')).read_bytes()
        if digest(raw) != p['sha256']:
            raise ValueError('Manuscript changed: ' + p['id'])
        await run(argparse.Namespace(paper=p['id'], methods='D', limit=None))
        report = json.loads((folder / p['id'] / 'D.json').read_bytes())
        if report['protocol'] != frozen['protocol'] or report['request']['manuscript_sha256'] != p['sha256']:
            raise ValueError('Report is outside the chosen protocol: ' + p['id'])
        parsed = parse_pdf(raw)
        for check in report['checked']:
            for anchor in check['evidence']:
                page = anchor['page']
                if not 1 <= page <= len(parsed['pages']) or not anchor['quote'] or anchor['quote'] not in parsed['pages'][page-1]:
                    raise ValueError('Unbound quotation: ' + p['id'])
        counts = Counter(c['status'] for c in report['checked'])
        results.append(dict(paper=p['id'], timing=p['timing_audit'], counts=counts))
        write(folder / 'summary.json', dict(planned=len(papers), completed=len(results), cases=results))
        print(p['id'], dict(counts), flush=True)
    from product_provenance import audit
    audit()


if __name__ == '__main__':
    asyncio.run(main())
