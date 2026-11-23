"""Audit what a released family name communicates about new, source-verified concerns."""
import argparse
import json
import random
from collections import Counter
from pathlib import Path

import pyarrow.parquet as pq
from run import write
from reviewarena.kb import DATA,current_snapshot
from reviewarena.family_audit import verify_ratings


def prepare(snapshot):
    folder=DATA/'family-audit'/snapshot.name
    target=folder/'packet.json'
    if target.exists():return target
    taxonomy=pq.read_table(snapshot/'taxonomy.parquet').to_pylist()
    by_category={r['category']:r for r in taxonomy if r.get('family_assignment')=='embedding assignment'}
    population={}
    for row in pq.read_table(snapshot/'critique.parquet').to_pylist():
        if row['category'] in by_category:
            population.setdefault(row['category'],row)
    if not population:raise ValueError('No new detailed categories eligible for a family audit')
    first=next(iter(by_category.values()))
    ref=first['family_reference_sha256']
    groups=json.loads((DATA/'taxonomy-naming'/(ref+'.json')).read_bytes())
    names=json.loads((DATA/'taxonomy-naming'/(ref+'.labels.json')).read_bytes())['names']
    examples={names[key]:g['categories'] for key,g in groups.items()}
    ordered=sorted(population,key=lambda c:(by_category[c]['family_similarity'],c))
    rng=random.Random(16)
    selected=[]
    for q in range(5):
        pool=ordered[len(ordered)*q//5:len(ordered)*(q+1)//5]
        for category in rng.sample(pool,min(5,len(pool))):
            row=population[category];family=by_category[category]['family']
            selected.append(dict(category=category,family=family,reference_examples=examples[family],
                                 review_quote=row['critique_text'],manuscript_quote=row['trigger_text'],
                                 review_id=row['review_id'],paper_id=row['paper_id'],similarity_quintile=q+1))
    rng.shuffle(selected)
    write(target,dict(snapshot=snapshot.name,reference=ref,eligible_detailed_categories=len(population),items=selected))
    return target


def score(packet_file,annotation):
    raw=packet_file.read_bytes()
    label=json.loads(annotation.read_bytes())
    packet,ratings=verify_ratings(raw,label)
    counts=Counter(r['verdict'] for r in ratings)
    write(packet_file.parent/'judgment.json',label)
    summary=dict(sample_size=len(ratings),counts=dict(counts),reference=packet['reference'],
                 eligible_detailed_categories=packet['eligible_detailed_categories'],snapshot=packet['snapshot'])
    write(packet_file.parent/'metrics.json',summary)
    write(DATA/'metrics/family-assignment-audit.json',summary)
    print(dict(counts))


if __name__=='__main__':
    p=argparse.ArgumentParser()
    p.add_argument('--packet',type=Path)
    p.add_argument('--ratings',type=Path)
    args=p.parse_args()
    if args.ratings and not args.packet:p.error('Specify the source packet with the ratings')
    if args.ratings:score(args.packet,args.ratings)
    else:print(prepare(current_snapshot()))
