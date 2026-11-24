"""Admit only source-verifiable 6luna xhigh labels into the retrieval index."""
import argparse,json,sys,tempfile
from pathlib import Path
import duckdb,pyarrow as pa,pyarrow.parquet as pq
from fetch import ROOT

def values(x):
    if isinstance(x,str):yield x
    if isinstance(x,dict):
        for v in x.values():yield from values(v)
    if isinstance(x,list):
        for v in x:yield from values(v)

def verify(directory):
    data=ROOT/'data'
    rows=[]
    path=Path(directory)
    with duckdb.connect(str(data/'history.duckdb'),read_only=True) as db:
        for file in ([path] if path.is_file() else sorted(path.glob('*.json'))):
            source_packet=data/'packets'/file.name
            if not source_packet.exists():source_packet=data/'packets-expanded'/file.name
            packet=json.loads(source_packet.read_text())
            meta=db.execute('select title,decision,year,abstract,venue from papers where id=?',[packet['paper_id']]).fetchone()
            if not meta:raise ValueError(f"Unknown paper {packet['paper_id']}")
            title,decision,year,abstract,venue=meta
            annotations=json.loads(file.read_text())
            if not isinstance(annotations,list):
                raise ValueError(f'Expected an array of annotations: {file}')
            for i,r in enumerate(annotations):
                if not isinstance(r,dict):
                    raise ValueError(f'Expected an annotation object in {file}:{i}')
                required_text=('paper_id','review_id','category','target_section','claim_type','paper_type','critique_text','trigger_text')
                missing=[field for field in required_text if not isinstance(r.get(field),str) or not r[field].strip()]
                if missing:
                    raise ValueError(f'Invalid or missing fields in {file}:{i}: {", ".join(missing)}')
                page=r.get('trigger_page')
                if r['paper_id']!=packet['paper_id']:
                    raise ValueError(f"Wrong manuscript ID {file}:{i}")
                if type(page) is not int or not 1<=page<=len(packet['pages']) or len(r['trigger_text'])<20 or r['trigger_text'] not in packet['pages'][page-1]:
                    raise ValueError(f"Unverified manuscript quote {file}:{i} page {page}")
                review=packet['reviews'].get(r['review_id'])
                if not review or len(r['critique_text'])<18 or not any(r['critique_text'] in t for t in values(json.loads(review))):
                    raise ValueError(f"Unverified review quote {file}:{i} review {r['review_id']}")
                if type(r.get('severity')) is not int or r['severity'] not in (1,2,3):
                    raise ValueError(f"Invalid severity {file}:{i}")
                replies={rid:text for rid,review,text in packet['replies'] if review==r['review_id']}
                reply=replies[r['reply_id']] if r.get('reply_id') else ''
                for field in ('transfer_question','reply_strategy','reply_strategy_quote','resolution_quote','resolution_source_field'):
                    r.setdefault(field,None)
                if r['reply_strategy'] is not None:
                    quote=r['reply_strategy_quote']
                    if r['reply_strategy'] not in ('discussion','clarify','experiment','revise') or not reply or not quote or not any(quote in v for v in values(json.loads(reply))):
                        raise ValueError(f"Unverified response strategy {file}:{i}")
                if r.get('resolved') is not None:
                    original=json.loads(packet['reviews'][r['review_id']])
                    field=r.get('resolution_source_field')
                    quote=r.get('resolution_quote')
                    if type(r['resolved']) is not bool or not quote or field not in original or not any(quote in text for text in values(original[field])):
                        raise ValueError(f"Unverified reviewer resolution {file}:{i}")
                rows.append(dict(r,pdf_info=packet.get('pdf_info'),id=f"{r['review_id']}-{i}",title=title,decision=decision,year=year,venue=venue,abstract=abstract,reply=reply,source=f"https://openreview.net/forum?id={r['paper_id']}&noteId={r['review_id']}"))
    return rows

def build(directory):
    rows=verify(directory)
    if not rows:raise ValueError("No verified labels")
    path=ROOT/'data'/'critique.parquet'
    tmp=path.with_suffix('.tmp')
    pq.write_table(pa.Table.from_pylist(rows),tmp);tmp.replace(path)
    print(len(rows),'verified pairs')
def sync(directory):
    """Build from a stable snapshot, then retain the validated source files for rebuilds."""
    dest=ROOT/'data/labels'
    dest.mkdir(exist_ok=True)
    with tempfile.TemporaryDirectory() as stage:
        snapshot=Path(stage)
        for directory_path in (dest,directory):
            for source in sorted(directory_path.glob('*.json')):
                (snapshot/source.name).write_bytes(source.read_bytes())
        build(snapshot)
        for item in snapshot.glob('*.json'):
            output=dest/item.name
            data=item.read_bytes()
            if output.exists() and output.read_bytes()==data:continue
            with tempfile.NamedTemporaryFile(dir=dest,delete=False) as f:
                f.write(data)
                tmp=Path(f.name)
            tmp.replace(output)
    print(len(list(dest.glob('*.json'))),'reviewed PDF packets retained')

if __name__=='__main__':
    parser=argparse.ArgumentParser()
    parser.add_argument('directory',type=Path)
    commands=parser.add_mutually_exclusive_group()
    commands.add_argument('--sync',action='store_true')
    commands.add_argument('--check',action='store_true')
    args=parser.parse_args()
    if args.check:print(len(verify(args.directory)),'verified pairs')
    elif args.sync:sync(args.directory)
    else:build(args.directory)
