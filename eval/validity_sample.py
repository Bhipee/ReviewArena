"""Draw 50 predicted critiques for independent validity review against the target PDF."""
import argparse
import csv
import hashlib
import json
import random
from pathlib import Path
from run import DATA,write
from collections import Counter
import pymupdf
from metrics import issues
from format_failure import format_failure
from import_judgments import validate


def make_sample(run):
    root = DATA/run
    papers = json.loads((DATA/'iclr2025'/'manifest.json').read_text())
    rows = []
    excluded=[]
    returned=Counter()
    for paper in papers:
        for method in 'ABCD':
            path = root/paper['id']/(method+'.json')
            if not path.exists():
                failure=DATA/'eval-errors'/run/paper['id']/(method+'.json')
                if failure.exists():
                    reason=json.loads(failure.read_bytes()).get('error','')
                    if format_failure(reason):
                        excluded.append(dict(paper=paper['id'],method=method,reason=reason))
                        continue
                raise ValueError(f'Complete all evaluations before sampling: missing {path}')
            raw = path.read_bytes()
            returned[method]+=1
            for index, concern in enumerate(issues(json.loads(raw))):
                rows.append(dict(paper=paper['id'], method=method, index=index, concern=concern,
                                 run_sha256=hashlib.sha256(raw).hexdigest()))
    sampled = random.Random(16).sample(rows,50)
    if run=='eval-frozen':
        expected={paper['id']:paper['sha256'] for paper in papers}
        for pid in {row['paper'] for row in sampled}:
            pdf=DATA/'iclr2025'/(pid+'.pdf')
            if hashlib.sha256(pdf.read_bytes()).hexdigest()!=expected[pid]:
                raise ValueError('The manuscript differs from the frozen sample: '+pid)
    out = root/'validity-audit'
    out.mkdir(exist_ok=True)
    manifest = out/'sample.json'
    if manifest.exists() and json.loads(manifest.read_text()) != sampled:
        raise ValueError('Existing sample belongs to different run outputs.')
    if not manifest.exists():manifest.write_text(json.dumps(sampled,indent=2))
    write(out/'sampling-frame.json',dict(selected_papers=len(papers),returned_reports=returned,
          eligible_predictions=Counter(r['method'] for r in rows),excluded_generation_failures=excluded,
          sample_size=len(sampled),seed=16))
    target = out/'rater.csv'
    if target.exists():return target
    with target.open('x') as f:
        writer = csv.writer(f)
        writer.writerow(['sample_id','paper_id','manuscript','predicted_concern','validity','evidence_page','reason'])
        for i,row in enumerate(sampled):
            writer.writerow([i,row['paper'],str(DATA/'iclr2025'/(row['paper']+'.pdf')),row['concern'],'','',''])
    return target


def published_match(root,item):
    path=Path(item['paper'])/(item['method']+'.json')
    packet=root/'judge-input'/path
    judgment=root/'judgments'/path
    if not packet.exists() or not judgment.exists():
        return 'awaiting semantic judgment'
    raw=packet.read_bytes()
    decisions=json.loads(judgment.read_bytes())
    source = validate(decisions, raw, judgment)
    if source['predicted'][item['index']]!=item['concern']:
        raise ValueError('Sample and matching packet disagree: '+str(path))
    matched=any(i==item['index'] for i,_ in decisions['matches'])
    return 'matched published concern' if matched else 'no matched published concern'


def score_sample(run):
    sheet=make_sample(run)
    sample=json.loads((sheet.parent/'sample.json').read_text())
    with sheet.open() as f:ratings=list(csv.DictReader(f))
    if len(ratings)!=50 or {r['sample_id'] for r in ratings}!={str(i) for i in range(50)}:
        raise ValueError('The sheet must contain all 50 original sample IDs.')
    counts=Counter();methods={};published={}
    for row in ratings:
        item=sample[int(row['sample_id'])]
        if item['paper']!=row['paper_id'] or str(item['concern'])!=row['predicted_concern']:
            raise ValueError('Judged concern differs from the sampled output: '+row['sample_id'])
        verdict=row['validity'].strip().casefold()
        if verdict not in ('valid','invalid','insufficient') or not row['reason'].strip():
            raise ValueError('Complete the validity and reason for sample '+row['sample_id'])
        if verdict in ('valid','invalid'):
            with pymupdf.open(DATA/'iclr2025'/(item['paper']+'.pdf')) as doc:
                if not row['evidence_page'].isdigit() or not 1<=int(row['evidence_page'])<=len(doc):
                    raise ValueError('Enter a manuscript evidence page for sample '+row['sample_id'])
        counts[verdict]+=1
        methods.setdefault(item['method'],Counter())[verdict]+=1
        group=published_match(DATA/run,item)
        published.setdefault(group,Counter())[verdict]+=1
    write(sheet.parent/'summary.json',dict(sample_size=len(ratings),counts=counts,by_method=methods,by_published_match=published))
    return dict(counts)


if __name__=='__main__':
    parser=argparse.ArgumentParser();parser.add_argument('--run',default='eval-frozen')
    parser.add_argument('--score',action='store_true')
    args=parser.parse_args()
    print(score_sample(args.run) if args.score else make_sample(args.run))
