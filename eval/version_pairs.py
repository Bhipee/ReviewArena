"""Compare two dated manuscripts for the same paper, method and evaluation protocol."""
import hashlib
import json
from statistics import mean
from pathlib import Path

from metrics import issues
from run import DATA,write


def sha(raw):
    return hashlib.sha256(raw).hexdigest()


def judgment(root,pid,method,report):
    file=method+'.json'
    labeled=root/'judgments'/pid/file
    if not labeled.exists():return None
    raw=(root/'judge-input'/pid/file).read_bytes()
    packet=json.loads(raw)
    record=json.loads(labeled.read_bytes())
    if (record['packet_sha256']!=sha(raw) or record['model']!='gpt-6-luna' or record['effort']!='xhigh'
            or packet['predicted']!=issues(report) or packet['reference']!=json.loads((DATA/'truth-labels'/(pid+'.json')).read_bytes())):
        raise ValueError(f'Stale judgment for {root.name}/{pid}/{method}')
    for prediction,reference in record['matches']:
        if not (type(prediction) is int and 0<=prediction<len(packet['predicted']) and
                type(reference) is int and 0<=reference<len(packet['reference'])):
            raise ValueError(f'Match outside source packet for {root.name}/{pid}/{method}')
    return sorted({j for _,j in record['matches']})


def report_score(report):
    scores=[]
    for reviewer in report['reviews']:
        try:score=float(reviewer['report'].get('score'))
        except (ValueError,TypeError):continue
        if 1<=score<=10:scores.append(score)
    return mean(scores) if scores else None


def compare():
    primary=DATA/'eval-frozen'
    early=DATA/'eval-early'
    inputs={r['id']:r for r in json.loads((DATA/'iclr2025/manifest.json').read_bytes())}
    alternatives={r['id']:r for r in json.loads((DATA/'iclr2025-early/manifest.json').read_bytes()) if 'path' in r}
    differs=[]
    identical=0
    for binding_path in sorted(early.glob('*/*.input.json')):
        pid=binding_path.parent.name
        method=binding_path.name.split('.')[0]
        binding=json.loads(binding_path.read_bytes())
        source=alternatives[pid]
        early_raw=(early/pid/(method+'.json')).read_bytes()
        primary_sha=sha((DATA/'iclr2025'/(pid+'.pdf')).read_bytes())
        early_sha=sha((DATA/source['path']).read_bytes())
        if (binding['input_sha256']!=early_sha or source['sha256']!=early_sha or binding['output_sha256']!=sha(early_raw)
                or inputs[pid]['sha256']!=primary_sha or binding['path']!=source['path']):
            raise ValueError('Input/output binding changed: '+pid)
        first=primary/pid/(method+'.json')
        if not first.exists():continue
        baseline=json.loads(first.read_bytes());alternate=json.loads(early_raw)
        if baseline['protocol']!=alternate['protocol']:raise ValueError('Different generation protocols: '+pid+'/'+method)
        if early_sha==primary_sha:
            if baseline!=alternate:raise ValueError('Reused result differs: '+pid)
            identical+=1
            continue
        old=judgment(primary,pid,method,baseline)
        new=judgment(early,pid,method,alternate)
        row=dict(paper=pid,method=method,primary_sha256=primary_sha,early_sha256=early_sha,
                 primary_score=report_score(baseline),early_score=report_score(alternate),
                 primary_predictions=len(issues(baseline)),early_predictions=len(issues(alternate)),
                 reference_count=len(json.loads((DATA/'truth-labels'/(pid+'.json')).read_bytes())))
        if old is not None and new is not None:
            row.update(shared_reference_indices=sorted(set(old)&set(new)),
                       primary_only_reference_indices=sorted(set(old)-set(new)),
                       early_only_reference_indices=sorted(set(new)-set(old)))
        differs.append(row)
    result=dict(eligible_early_manuscripts=len(alternatives),identical_input_results=identical,
                distinct_input_pairs=differs,semantically_judged_pairs=sum('shared_reference_indices' in r for r in differs))
    judged=[r for r in differs if 'shared_reference_indices' in r]
    result['distinct_papers_judged']=len({r['paper'] for r in judged})
    result['by_method']={}
    for method in 'ABCD':
        pairs=[r for r in judged if r['method']==method]
        result['by_method'][method]=dict(papers=len(pairs),
            primary_only=sum(len(r['primary_only_reference_indices']) for r in pairs),
            both=sum(len(r['shared_reference_indices']) for r in pairs),
            early_only=sum(len(r['early_only_reference_indices']) for r in pairs))
    write(early/'metrics/version-pairs.json',result)
    print('Identical input results:',identical,'genuine version pairs:',len(differs),'judged pairs:',result['semantically_judged_pairs'])


if __name__=='__main__':compare()
