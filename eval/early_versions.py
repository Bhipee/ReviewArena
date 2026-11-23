"""Run the frozen comparison on alternate pre-review manuscripts and reuse byte-identical primary inputs."""
import argparse
import asyncio
import hashlib
import json
import os
import sys
from pathlib import Path

ROOT=Path(__file__).resolve().parents[1]
RUNTIME=ROOT/'.evaluation-runtime/baseline-v1'
DATA=ROOT/'data'
sys.path.insert(0,str(RUNTIME/'eval'))
from run import write
from reviewarena.paper import parse_pdf
from reviewarena.workflow import run_review


def json_format_failure(exc):
    if isinstance(exc,BaseExceptionGroup):
        return all(json_format_failure(child) for child in exc.exceptions)
    return isinstance(exc,ValueError) and str(exc)=='Model returned invalid JSON twice.'


async def evaluate(paper_filter,methods,reuse_only=False):
    destination=DATA/'eval-early'
    os.environ['REVIEWARENA_KB_SNAPSHOT']=str(RUNTIME/'data/eval-frozen/indexes')
    os.environ.setdefault('REVIEWARENA_PUBLIC_RUN_CACHE',str(DATA/'public-cache'))
    records=json.loads((DATA/'iclr2025-early/manifest.json').read_text())
    if paper_filter and not any(r['id']==paper_filter and 'path' in r for r in records):
        raise ValueError('Paper is missing an eligible pre-review input')
    failed=[]
    for row in records:
        if 'path' not in row or (paper_filter and row['id']!=paper_filter):continue
        pid=row['id']
        raw=(DATA/row['path']).read_bytes()
        if hashlib.sha256(raw).hexdigest()!=row['sha256']:raise ValueError('Early manuscript changed: '+pid)
        shared=row['path']=='iclr2025/'+pid+'.pdf'
        if reuse_only and not shared:continue
        if shared and not any((DATA/'eval-frozen'/pid).glob('[ABCD].json')):continue
        paper=parse_pdf(raw)
        for method in methods:
            output=destination/pid/(method+'.json')
            source=destination/pid/(method+'.input.json')
            if output.exists() and source.exists():
                bound=json.loads(source.read_text())
                if bound['input_sha256']!=row['sha256'] or bound['output_sha256']!=hashlib.sha256(output.read_bytes()).hexdigest():
                    raise ValueError('Early run or source changed: '+pid)
                continue
            if shared:
                primary=DATA/'eval-frozen'/pid/(method+'.json')
                if not primary.exists():continue
                result=json.loads(primary.read_text())
            else:
                print('Evaluating',pid,method,row['source'],flush=True)
                try:
                    result=await run_review(paper,'ICLR',method,'2024-10-01')
                except Exception as exc:
                    if not json_format_failure(exc):raise
                    write(DATA/'eval-errors'/'eval-early'/pid/(method+'.json'),
                          dict(error='Model returned invalid JSON twice.',input_sha256=row['sha256'],path=row['path']))
                    print('Format failure:',pid,method,flush=True)
                    failed.append((pid,method))
                    if paper_filter:raise
                    continue
            write(output,result)
            write(source,dict(input_sha256=row['sha256'],output_sha256=hashlib.sha256(output.read_bytes()).hexdigest(),
                              shared_primary_input=shared,source=row['source'],path=row['path']))
            (DATA/'eval-errors'/'eval-early'/pid/(method+'.json')).unlink(missing_ok=True)
        if not any((destination/pid).glob('[ABCD].json')):continue
        import duckdb
        with duckdb.connect() as db:
            decision,reviews=db.execute("select decision,reviews from read_parquet(?) where year='2025' and paper_id=?",
                                        [str(DATA/'raw/reviews.parquet'),pid]).fetchone()
        write(destination/pid/'truth.json',dict(decision=decision,reviews=reviews))

    if failed:raise RuntimeError(f'Unfinished pre-review evaluations: {failed}')


def reuse_shared_judgments():
    early=DATA/'eval-early'
    primary=DATA/'eval-frozen'
    reused=0
    for source in sorted(early.glob('*/*.input.json')):
        binding=json.loads(source.read_bytes())
        if not binding['shared_primary_input']:continue
        pid=source.parent.name
        name=source.name.replace('.input.json','.json')
        if json.loads((early/pid/name).read_bytes())!=json.loads((primary/pid/name).read_bytes()):
            raise ValueError('Different prediction in a shared input: '+pid)
        for inputs,labels in [('judge-input','judgments'),('citation-input','citation-labels')]:
            origin=primary/labels/pid/name
            target=early/labels/pid/name
            packet=early/inputs/pid/name
            if target.exists() or not origin.exists() or not packet.exists():continue
            raw=packet.read_bytes()
            label=json.loads(origin.read_bytes())
            if raw!=(primary/inputs/pid/name).read_bytes() or hashlib.sha256(raw).hexdigest()!=label['packet_sha256']:
                raise ValueError('Different labeling packet for '+pid)
            if (label['model'],label['effort'])!=('gpt-6-luna','xhigh'):raise ValueError('Unexpected label origin')
            write(target,label)
            reused+=1
    print('Reused source-identical judgments:',reused)


if __name__=='__main__':
    parser=argparse.ArgumentParser()
    parser.add_argument('--paper')
    parser.add_argument('--methods',default='ABCD')
    parser.add_argument('--reuse-only',action='store_true')
    parser.add_argument('--reuse-judgments',action='store_true')
    args=parser.parse_args()
    if args.reuse_judgments:
        reuse_shared_judgments()
        sys.exit(0)
    asyncio.run(evaluate(args.paper,args.methods,args.reuse_only))
