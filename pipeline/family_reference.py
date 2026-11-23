"""Apply a released set of named critique families to a growing issue vocabulary."""
import hashlib
import json

import numpy as np


def load_reference(folder,source):
    packet=(folder/(source+'.json')).read_bytes()
    annotation=json.loads((folder/(source+'.labels.json')).read_bytes())
    if hashlib.sha256(packet).hexdigest()!=source or annotation['packet_sha256']!=source:
        raise ValueError('The family reference no longer matches its naming packet')
    if (annotation['model'],annotation['effort'])!=('gpt-6-luna','xhigh'):
        raise ValueError('Unexpected model for critique-family names')
    groups=json.loads(packet)
    names=annotation['names']
    if set(groups)!=set(names) or len({v.strip().casefold() for v in names.values()})!=len(groups):
        raise ValueError('Family names must cover the reference exactly and be distinct')
    for key,group in groups.items():
        members=group['categories']
        expected=hashlib.sha256(json.dumps(members,ensure_ascii=False).encode()).hexdigest()
        if not members or key!=expected or group['representative'] not in members:
            raise ValueError('Invalid reference membership or representative')
    return [(names[k],groups[k]['categories']) for k in sorted(groups)]


def assign_categories(groups,categories,vectorize):
    reference=[member for _,members in groups for member in members]
    if len(reference)!=len(set(reference)):raise ValueError('Duplicate reference category')
    vocabulary=sorted(set(reference).union(categories))
    vectors=dict(zip(vocabulary,vectorize(vocabulary)))
    reference_vectors=np.stack([vectors[c] for c in reference])
    offsets=np.cumsum([0]+[len(members) for _,members in groups])[:-1]
    centers=np.add.reduceat(reference_vectors,offsets,axis=0)
    centers=centers/np.linalg.norm(centers,axis=1,keepdims=True)
    assignments={c:(name,'reference member',None) for name,members in groups for c in members}
    new=[c for c in categories if c not in assignments]
    for start in range(0,len(new),256):
        batch=new[start:start+256]
        query=np.stack([vectors[c] for c in batch])
        nearest=np.maximum.reduceat(query@reference_vectors.T,offsets,axis=1)
        similarity=(query@centers.T+nearest)/2
        for c,scores in zip(batch,similarity):
            best=int(np.argmax(scores))
            assignments[c]=(groups[best][0],'embedding assignment',float(scores[best]))
    return {c:assignments[c] for c in categories}
