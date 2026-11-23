"""Blind assessment of whether a proposed manuscript question preserves the historical scientific check."""
import argparse
import asyncio
import os
from pathlib import Path
import hashlib
import json

from run import DATA,write

ROOT=DATA/'eval-product-heldout-four'
AUDIT=ROOT/'question-fit'


def prepare():
    plan=json.loads((ROOT/'plan.json').read_bytes())
    inputs=[]
    for p in plan['manuscripts']:
        result=ROOT/p['id']/'D.json'
        if not result.exists():
            continue
        report=json.loads(result.read_bytes())
        if report['protocol']!=plan['protocol'] or report['request']['manuscript_sha256']!=p['sha256']:
            raise ValueError('Manuscript or protocol differs: '+p['id'])
        for i,check in enumerate(report['checked']):
            c=check['candidate']
            if not c.get('target_question'):
                continue
            row=dict(source_quote=c['critique_text'],source_check=c.get('transfer_question') or c['critique_text'],
                     target_claim=c['matched_claim'],target_question=c['target_question'])
            path=AUDIT/'inputs'/f"{p['id']}-{i}.json"
            if path.exists() and json.loads(path.read_bytes())!=row:
                raise ValueError('Blind assessment input changed: '+path.name)
            if not path.exists():
                write(path,row)
            inputs.append(path)
    return inputs


def rank_checks():
    from reviewarena.question_alignment import source_ranks
    plan=json.loads((ROOT/'plan.json').read_bytes())
    rule=dict(keep_if="assigned historical check ties for highest cosine similarity among this paper's 20 retrieved checks",
              development=[r['id'] for r in plan['manuscripts'][:3]],held_out=plan['manuscripts'][3]['id'])
    rule_path=AUDIT/'rank-rule.json'
    if rule_path.exists() and json.loads(rule_path.read_bytes())!=rule:
        raise ValueError('The recorded rule or development split changed')
    if not rule_path.exists():
        write(rule_path,rule)
    for entry in plan['manuscripts']:
        report=ROOT/entry['id']/'D.json'
        if not report.exists():continue
        candidates=[z['candidate'] for z in json.loads(report.read_bytes())['checked']]
        for index,rank in source_ranks(candidates).items():
            name=f"{entry['id']}-{index}.json"
            digest=hashlib.sha256((AUDIT/'inputs'/name).read_bytes()).hexdigest()
            write(AUDIT/'ranks'/name,dict(packet_sha256=digest,**rank))


async def predict(inputs):
    from reviewarena.question_fit import check_question_fit
    from reviewarena.protocol import protocol
    from reviewarena.workflow import ask
    os.environ.setdefault('REVIEWARENA_PUBLIC_RUN_CACHE',str(DATA/'public-cache'))
    plan=json.loads((ROOT/'plan.json').read_bytes())
    current=protocol('D','ICLR',DATA/'index-snapshots'/plan['index'])
    identity={k:current[k] for k in ('model','endpoint_host','endpoint_port')}
    if any(v!=plan['protocol'][k] for k,v in identity.items()):
        raise ValueError('Question-fit model differs from the planned product model')
    source=Path(__file__).resolve().parents[1]/'reviewarena/question_fit.py'
    identity['question_fit_sha256']=hashlib.sha256(source.read_bytes()).hexdigest()
    for path in inputs:
        out=AUDIT/'predictions'/path.name
        raw=path.read_bytes()
        result=await check_question_fit(json.loads(raw),ask)
        write(out,dict(packet_sha256=hashlib.sha256(raw).hexdigest(),inference=identity,**result))
        print(path.stem,result['same_check'],result['grounded_in_claim'],flush=True)


def score(inputs, labels):
    counts=dict(kept_applicable=0,kept_inapplicable=0,excluded_applicable=0,excluded_inapplicable=0)
    rows=[]
    rank_counts={}
    missing_decisions=0
    pending_predictions=0
    for path in inputs:
        pred=AUDIT/'predictions'/path.name
        mark=labels/path.name
        if not mark.exists():
            continue
        sha=hashlib.sha256(path.read_bytes()).hexdigest()
        estimate=json.loads(pred.read_bytes()) if pred.exists() else {}
        label=json.loads(mark.read_bytes())
        if (label.get('model'),label.get('effort'),label.get('packet_sha256'))!=('gpt-6-luna','xhigh',sha) or (estimate and estimate.get('packet_sha256')!=sha):
            raise ValueError('Unexpected provenance: '+path.name)
        if not all(type(label.get(field)) is bool for field in ('same_check','grounded_in_claim')):
            raise ValueError('Invalid question rating: '+path.name)
        applicable=label['same_check'] and label['grounded_in_claim']
        keep=None
        if all(type(estimate.get(field)) is bool for field in ('same_check','grounded_in_claim')):
            keep=estimate['same_check'] and estimate['grounded_in_claim']
        if not estimate:
            pending_predictions+=1
        elif keep is None:
            missing_decisions+=1
        else:
            counts[('kept_' if keep else 'excluded_')+('applicable' if applicable else 'inapplicable')]+=1
        ranking=json.loads((AUDIT/'ranks'/path.name).read_bytes())
        if ranking['packet_sha256']!=sha:raise ValueError('Unbound source ranking')
        rule=json.loads((AUDIT/'rank-rule.json').read_bytes())
        subset='held_out' if path.stem.rsplit('-',1)[0]==rule['held_out'] else 'development'
        bucket=rank_counts.setdefault(subset,dict(kept_applicable=0,kept_inapplicable=0,excluded_applicable=0,excluded_inapplicable=0))
        bucket[('kept_' if ranking['rank']==1 else 'excluded_')+('applicable' if applicable else 'inapplicable')]+=1
        rows.append(dict(item=path.stem,source_rank=ranking['rank'],subset=subset,applicable=applicable,keep=keep,assessment=label['reason'],prediction=estimate.get('reason')))
    write(AUDIT/'summary.json',dict(available=len(inputs),judged=len(rows),model_counts=counts,unparsed_model_decisions=missing_decisions,pending_model_decisions=pending_predictions,source_rank_counts=rank_counts,items=rows))
    print(counts)


if __name__=='__main__':
    parser=argparse.ArgumentParser()
    parser.add_argument('--predict',action='store_true')
    parser.add_argument('--labels',type=Path)
    args=parser.parse_args()
    inputs=prepare()
    rank_checks()
    print('Verified transferred questions:',len(inputs),flush=True)
    if args.predict:
        asyncio.run(predict(inputs))
    if args.labels:
        score(inputs,args.labels)
