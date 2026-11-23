"""Prepare whole-corpus 6luna classification packets and verify returned review coverage."""
import argparse
import hashlib
import json
import tempfile
from pathlib import Path
import duckdb
from fetch import ROOT

DATA=ROOT/'data'


def write(path,data):
    path.parent.mkdir(parents=True,exist_ok=True)
    with tempfile.NamedTemporaryFile(dir=path.parent,mode='w',delete=False) as out:
        json.dump(data,out,ensure_ascii=False)
        tmp=Path(out.name)
    tmp.replace(path)


def export():
    packets=DATA/'class-packets'
    manifest=packets/'manifest.json'
    if manifest.exists():
        entries=json.loads(manifest.read_text())
        for e in entries:
            if hashlib.sha256((packets/e['file']).read_bytes()).hexdigest()!=e['sha256']:
                raise ValueError(e['file']+' differs from its exported fingerprint')
        return entries
    entries=[]
    with duckdb.connect(str(DATA/'history.duckdb'),read_only=True) as db:
        rows=db.execute('select id,content from reviews order by id')
        while batch:=rows.fetchmany(20):
            name=f'{len(entries):05}.json'
            reviews=[{'id':rid,'content':json.loads(content)} for rid,content in batch]
            write(packets/name,{'reviews':reviews})
            entries.append(dict(file=name,count=len(batch),sha256=hashlib.sha256((packets/name).read_bytes()).hexdigest()))
    write(manifest,entries)
    return entries


def import_packet(path,manifest):
    entry=manifest[path.name]
    raw=(DATA/'class-packets'/path.name).read_bytes();digest=hashlib.sha256(raw).hexdigest()
    label=json.loads(path.read_text())
    if (label.get('packet_sha256'),label.get('model'),label.get('effort'))!=(digest,'gpt-6-luna','xhigh') or digest!=entry['sha256']:
        raise ValueError(f'{path}: wrong packet or annotator')
    prepared={r['id'] for r in json.loads(raw)['reviews']}
    labels=label['reviews']
    if len(labels)!=len(prepared) or {r['review_id'] for r in labels}!=prepared:
        raise ValueError(f'{path}: incomplete or duplicate review IDs')
    rows=[]
    for r in labels:
        if not isinstance(r['issues'],list):raise ValueError(f'{path}: issues must be an array')
        for item in r['issues']:
            fields=('category','claim_type','paper_type')
            if not all(isinstance(item.get(k),str) and item[k].strip() for k in fields) or type(item.get('severity')) is not int or item['severity'] not in (1,2,3):
                raise ValueError(f'{path}: invalid issue in '+r['review_id'])
            rows.append(dict(review_id=r['review_id'],severity=item['severity'],**{k:item[k] for k in fields}))
    for target,content in [(DATA/'classes'/('packet-'+path.name),rows),(DATA/'class-provenance'/path.name,label)]:
        if target.is_file() and target.read_bytes()==json.dumps(content,ensure_ascii=False).encode():
            continue
        write(target,content)


def import_labels(folder):
    manifest={e['file']:e for e in json.loads((DATA/'class-packets/manifest.json').read_text())}
    for path in sorted(folder.glob('*.json')):
        import_packet(path,manifest)


if __name__=='__main__':
    p=argparse.ArgumentParser()
    p.add_argument('--import-labels',type=Path)
    args=p.parse_args()
    if args.import_labels:import_labels(args.import_labels)
    else:
        entries=export()
        print(len(entries),'packets;',sum(r['count'] for r in entries),'reviews')
