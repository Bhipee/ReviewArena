"""Cluster review issues and apply reviewed family names to exactly matching memberships."""
from pathlib import Path
import argparse,fcntl,hashlib,json,sys,tempfile
import numpy as np
import pyarrow as pa,pyarrow.parquet as pq
from sklearn.cluster import AgglomerativeClustering,MiniBatchKMeans
sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
from reviewarena.embedding import embed
from reviewarena.review_vectors import passage_vectors
from reviewarena.family_audit import applicable_ratings
from reviewarena.kb import DATA
import duckdb
from family_reference import load_reference,assign_categories

def category_vectors(names):
    model_files=[DATA/'bge-small/model_optimized.onnx',DATA/'bge-small/tokenizer.json',DATA.parent/'reviewarena/embedding.py']
    signature=hashlib.sha256(b''.join(hashlib.sha256(p.read_bytes()).digest() for p in model_files)).hexdigest()
    path=DATA/'taxonomy-vectors.npz'
    saved={}
    if path.exists():
        with np.load(path,allow_pickle=False) as data:
            if data['encoder'].item()==signature:
                saved=dict(zip(data['names'].tolist(),data['vectors']))
    missing=[name for name in names if name not in saved]
    if missing:saved.update(zip(missing,embed(missing)))
    vectors=np.stack([saved[name] for name in names])
    if missing:
        with tempfile.NamedTemporaryFile(dir=DATA,delete=False) as output:
            np.savez(output,encoder=signature,names=names,vectors=vectors);temp=Path(output.name)
        temp.replace(path)
    return vectors


def family_names(groups,annotation):
    folder=DATA/'taxonomy-naming'
    folder.mkdir(exist_ok=True)
    payload=json.dumps(groups,ensure_ascii=False,sort_keys=True,indent=2).encode()
    signature=hashlib.sha256(payload).hexdigest()
    packet=folder/(signature+'.json')
    if not packet.exists():packet.write_bytes(payload)
    labels=folder/'approved.json'
    approved=json.loads(labels.read_text()) if labels.exists() else {}
    if annotation:
        result=json.loads(annotation.read_text())
        source=folder/(result['packet_sha256']+'.json')
        if hashlib.sha256(source.read_bytes()).hexdigest()!=result['packet_sha256'] or (result.get('model'),result.get('effort'))!=('gpt-6-luna','xhigh'):
            raise ValueError('Unverified taxonomy naming source or model')
        original=json.loads(source.read_bytes())
        values=result['names']
        if set(values)!=set(original) or any(not isinstance(v,str) or not v.strip() for v in values.values()):
            raise ValueError('A family name is required for each original cluster')
        if len({v.strip().casefold() for v in values.values()})!=len(original):
            raise ValueError('Use distinct family names for distinct clusters')
        approved.update({key:{'name':name.strip(),'source':result['packet_sha256']} for key,name in values.items()})
        (folder/(result['packet_sha256']+'.labels.json')).write_bytes(annotation.read_bytes())
        with tempfile.NamedTemporaryFile(dir=folder,mode='w',delete=False) as out:
            json.dump(approved,out,indent=2);temp=Path(out.name)
        temp.replace(labels)
    print('Taxonomy naming packet:',packet)
    return {key:approved[key]['name'] for key in groups if key in approved}


def cluster_categories(names):
    vectors=category_vectors(names)
    n=len(names)
    if n==1:labels=[0]
    elif n>4096:
        labels=MiniBatchKMeans(n_clusters=65,batch_size=1024,n_init=3,random_state=16).fit_predict(vectors)
    else:
        params={'n_clusters':min(65,n)} if n>=65 else {'n_clusters':None,'distance_threshold':.16}
        labels=AgglomerativeClustering(metric='cosine',linkage='average',**params).fit_predict(vectors)
    groups={}
    for group in set(labels):
        ix=np.where(np.asarray(labels)==group)[0];center=vectors[ix].mean(0)
        name=names[ix[np.argmax(vectors[ix]@center)]]
        members=[names[i] for i in ix]
        key=hashlib.sha256(json.dumps(members,ensure_ascii=False).encode()).hexdigest()
        groups[key]=dict(representative=name,categories=members)
    return groups


def main(annotation=None,propose=False):
    records=[]
    completed=set()
    fields=['review_id','category','claim_type','paper_type','severity']
    for path in sorted((DATA/'class-provenance').glob('*.json')):
        batch=json.loads(path.read_bytes())
        for review in batch['reviews']:
            rid=review['review_id']
            if rid in completed:
                raise ValueError(f'Duplicate review in whole-corpus packets: {rid}')
            completed.add(rid)
            records.extend(dict(review_id=rid, **{k:issue[k] for k in fields[1:]}) for issue in review['issues'])
    # Legacy stratified labels can cover reviews outside the completed packet set.
    for path in sorted((DATA/'classes').glob('*.json')):
        if not path.name.startswith('packet-'):
            records.extend(row for row in json.loads(path.read_bytes()) if row['review_id'] not in completed)
    raw=(DATA/'critique.parquet').read_bytes()
    detail=pq.read_table(pa.BufferReader(raw)).to_pylist()
    records+=[{k:r[k] for k in fields} for r in detail]
    names=sorted({r['category'] for r in records})
    folder=DATA/'taxonomy-naming'
    pointer=folder/'reference.json'
    source=json.loads(pointer.read_bytes()) if pointer.exists() else None
    if propose or annotation or not source:
        groups=cluster_categories(names)
        reviewed_names=family_names(groups,annotation)
        if propose:return
        if annotation:source=json.loads(annotation.read_bytes())['packet_sha256']
    if source:
        reference=load_reference(folder,source)
        assignments=assign_categories(reference,names,category_vectors)
        reviewed_names={family for family,_,_ in assignments.values()}
        if annotation:
            with tempfile.NamedTemporaryFile(dir=folder,mode='w',delete=False) as out:
                json.dump(source,out);temp=Path(out.name)
            temp.replace(pointer)
    else:
        assignments={member:(reviewed_names.get(key,g['representative']),'cluster member',None)
                     for key,g in groups.items() for member in g['categories']}
    for r in records:
        r['family'],r['family_assignment'],r['family_similarity']=assignments[r['category']]
        r['family_reference_sha256']=source
    family_count=len({family for family,_,_ in assignments.values()})
    with duckdb.connect(str(DATA/'history.duckdb'),read_only=True) as conn:
        conn.register('labels',pa.Table.from_pylist(records))
        joined=conn.sql('select distinct l.*,p.id as paper_id,p.year,p.decision from labels l join reviews r on l.review_id=r.id join papers p on r.paper_id=p.id order by paper_id,review_id,category,claim_type,paper_type,severity,family').arrow().read_all()
    tmp=DATA/'taxonomy.tmp';pq.write_table(joined,tmp);tmp.replace(DATA/'taxonomy.parquet')
    taxonomy=(DATA/'taxonomy.parquet').read_bytes()
    audits=applicable_ratings(DATA/'family-audit',source,assignments,detail)
    audit_bytes=json.dumps(audits,ensure_ascii=False,sort_keys=True).encode()
    version=hashlib.sha256(raw+taxonomy+audit_bytes).hexdigest()
    target=DATA/'index-snapshots'/version
    target.mkdir(exist_ok=True,parents=True)
    for name,content in [('critique.parquet',raw),('taxonomy.parquet',taxonomy),('family-audits.json',audit_bytes)]:
        path=target/name
        if not path.exists():
            with tempfile.NamedTemporaryFile(dir=target,delete=False) as f:
                f.write(content);tmp=Path(f.name)
            tmp.replace(path)
    for field in ('trigger_text','critique_text'):
        passage_vectors(detail,field,publish=True)
    with tempfile.NamedTemporaryFile(dir=DATA,mode='w',delete=False) as f:
        json.dump(version,f);pointer=Path(f.name)
    pointer.replace(DATA/'active-index.json')
    coverage={'whole_corpus_reviews_processed':len(completed),'reviews_with_a_labeled_issue':len({r['review_id'] for r in records}),
              'pdf_packets_processed':len(list((DATA/'labels').glob('*.json'))),'verified_pairs':len(detail),
              'papers_with_verified_pairs':len({r['paper_id'] for r in detail}),'index_snapshot':version,'named_clusters':len(reviewed_names),'clusters':family_count,'family_reference_sha256':source,
              'reference_categories':sum(origin=='reference member' for _,origin,_ in assignments.values()),
              'audited_examples':len(audits),'excluded_family_examples':sum(r['verdict']!='fits' for r in audits),
              'inferred_categories':sum(origin=='embedding assignment' for _,origin,_ in assignments.values())}
    destination=DATA/'metrics/label-coverage.json';destination.parent.mkdir(exist_ok=True)
    with tempfile.NamedTemporaryFile(dir=destination.parent,mode='w',delete=False) as f:
        json.dump(coverage,f,indent=2);temp=Path(f.name)
    temp.replace(destination)
    print(len(records),'rows',family_count,'families')
if __name__=='__main__':
    parser=argparse.ArgumentParser()
    modes=parser.add_mutually_exclusive_group()
    modes.add_argument('--import-family-names',type=Path)
    modes.add_argument('--propose-recluster',action='store_true')
    args=parser.parse_args()
    with (DATA/'.taxonomy.lock').open('a') as lock:
        fcntl.flock(lock,fcntl.LOCK_EX)
        main(args.import_family_names,args.propose_recluster)
