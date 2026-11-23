"""Compare two match annotations for identical, blinded scientific issue packets."""
import hashlib
import json

from metrics import paired_summary
from run import write


def verified_pairs(label,packet,sha):
    if (label.get('packet_sha256'),label.get('model'),label.get('effort'))!=(sha,'gpt-6-luna','xhigh'):
        raise ValueError('Cannot compare annotations from different packets or annotators')
    pairs=set()
    for i,j in label['matches']:
        if type(i) is not int or type(j) is not int or not (0<=i<len(packet['predicted']) and 0<=j<len(packet['reference'])):
            raise ValueError('Invalid comparison indices')
        pairs.add((i,j))
    return pairs


def compare_annotations(root,first_pass):
    if not first_pass.is_dir():return
    rows={'first_pass':[],'current':[]}
    edits=[]
    for source in sorted(first_pass.glob('*/[ABCD].json')):
        relative=source.relative_to(first_pass)
        current=root/'judgments'/relative
        if not current.is_file():continue
        raw=(root/'judge-input'/relative).read_bytes()
        packet=json.loads(raw)
        digest=hashlib.sha256(raw).hexdigest()
        original=json.loads(source.read_bytes())
        before=verified_pairs(original,packet,digest)
        after=verified_pairs(json.loads(current.read_bytes()),packet,digest)
        archived=root/'judgments-first-pass'/relative
        if not archived.exists():write(archived,original)
        elif json.loads(archived.read_bytes())!=original:raise ValueError(f'First-pass labels changed for {relative}')
        paper,method=relative.parent.name,relative.stem
        for name,pairs in [('first_pass',before),('current',after)]:
            rows[name].append(dict(paper=paper,method=method,predictions=len(packet['predicted']),references=len(packet['reference']),
                                   matched_predictions=len({i for i,_ in pairs}),matched_references=len({j for _,j in pairs})))
        if before!=after:
            edits.append(dict(paper=paper,method=method,packet_sha256=digest,removed=sorted(before-after),added=sorted(after-before)))
    common=set.intersection(*[{r['paper'] for r in rows['current'] if r['method']==m} for m in 'ABCD'])
    result=dict(compared_reports=len(rows['current']),changed_reports=len(edits),edits=edits,
                **{name:paired_summary(items,common) for name,items in rows.items()})
    write(root/'metrics/judgment-sensitivity.json',result)
    return result
