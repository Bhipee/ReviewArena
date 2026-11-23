"""Verify held-out critique quotations against the original review before importing."""
import argparse
import hashlib
import json
from pathlib import Path
import duckdb

DATA=Path(__file__).resolve().parents[1]/'data'

def archived_references(data):
    ids=[r['id'] for r in json.loads((data/'iclr2025/manifest.json').read_bytes())]
    with duckdb.connect() as db:
        rows=db.execute("select paper_id,decision,reviews from read_parquet(?) where year='2025' and paper_id in (select unnest(?))",
                        [str(data/'raw/reviews.parquet'),ids]).fetchall()
    refs={pid:dict(decision=decision,reviews=reviews) for pid,decision,reviews in rows}
    if len(rows)!=len(refs) or set(refs)!=set(ids):
        raise ValueError('Missing or duplicate archived held-out review records')
    return refs


def verify_issues(path,raw,reviews):
    labels=json.loads(raw)
    if not isinstance(labels,list):
        raise ValueError(f'Expected an array of issues in {path.name}')
    for row in labels:
        index=row['review_index']
        if type(index) is not int or not 0<=index<len(reviews):raise ValueError(f'Invalid review index in {path.name}')
        quote=row['quote']
        fields=reviews[index]
        if not quote.strip() or not row['paraphrase'].strip() or not any(quote in (fields.get(k) or '') for k in ('questions','weaknesses')):
            raise ValueError(f'Unverified issue in {path.name}, review {index}')
    return len(labels)


def import_truth(directory):
    refs=archived_references(DATA)
    papers={}
    dest=DATA/'truth-labels'
    dest.mkdir(exist_ok=True)
    for path in sorted(directory.glob('*.json')):
        if path.stem not in refs:raise ValueError(f'Unexpected held-out paper {path.stem}')
        raw=path.read_bytes()
        papers[path.name]=(raw,verify_issues(path,raw,refs[path.stem]['reviews']))
    for name,(raw,count) in papers.items():
        target=dest/name
        if target.exists() and target.read_bytes()==raw:continue
        tmp=target.with_suffix('.tmp');tmp.write_bytes(raw);tmp.replace(target)
    report={name:{'issues':count,'sha256':hashlib.sha256(raw).hexdigest()} for name,(raw,count) in papers.items()}
    return report

if __name__=='__main__':
    parser=argparse.ArgumentParser();parser.add_argument('directory',type=Path)
    report=import_truth(parser.parse_args().directory)
    print(len(report),'verified papers,',sum(r['issues'] for r in report.values()),'verified issues')
