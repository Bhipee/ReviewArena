"""Run A/B/C/D through the live workflow, then join with held-out ground truth."""
import argparse,asyncio,json,sys,os,tempfile
from pathlib import Path
sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
from reviewarena.kb import DATA
from reviewarena.paper import parse_pdf
from reviewarena.workflow import run_review
import duckdb
from reviewarena.model import model_post

def write(path,obj):
    path.parent.mkdir(parents=True,exist_ok=True)
    with tempfile.NamedTemporaryFile(dir=path.parent,mode='w',delete=False) as out:
        json.dump(obj,out,indent=2);temp=Path(out.name)
    temp.replace(path)

async def main(args):
    os.environ.setdefault("REVIEWARENA_PUBLIC_RUN_CACHE",str(DATA/"public-cache"))
    run_dir=DATA/os.getenv('REVIEWARENA_RUN_NAMESPACE','eval')
    if run_dir.name=='eval-frozen':
        raise ValueError("Run the frozen comparison from .evaluation-runtime/baseline-v1 with its pinned code and annotation indexes. Use a separate namespace for the current product.")
    folder=DATA/'iclr2025';papers=json.loads((folder/'manifest.json').read_text())
    if args.paper:
        papers=[p for p in papers if p['id']==args.paper]
        if not papers:raise ValueError('Paper ID is not in the held-out manifest')
    if args.limit:papers=papers[:args.limit]
    failures=[]
    for p in papers:
        raw=(folder/(p['id']+'.pdf')).read_bytes()
        paper=parse_pdf(raw)
        for method in args.methods:
            out=run_dir/p['id']/(method+'.json')
            if out.exists():continue
            try:
                result=await run_review(paper,'ICLR',method,'2024-10-01',lambda msg:print(p['id'],method,msg,flush=True),pdf_bytes=raw)
            except Exception as exc:
                write(DATA/'eval-errors'/run_dir.name/p['id']/(method+'.json'),{'error':repr(exc)})
                print(p['id'],method,'failed:',str(exc),flush=True)
                if args.paper:raise
                health=model_post(os.getenv('REVIEWARENA_API_URL','http://127.0.0.1:8766/v1').rstrip('/')+'/chat/completions',
                    json={'model':os.getenv('REVIEWARENA_MODEL','default_model'),'messages':[{'role':'user','content':'Reply READY'}],'max_tokens':8},
                    headers={'Authorization':'Bearer '+os.getenv('REVIEWARENA_API_KEY','local')},timeout=(10,60))
                health.raise_for_status()
                if not health.json()['choices'][0]['message']['content'].strip():
                    raise RuntimeError('Model generation health check returned an empty answer') from exc
                failures.append((p['id'],method))
                continue
            write(out,result)
            (DATA/'eval-errors'/run_dir.name/p['id']/(method+'.json')).unlink(missing_ok=True)
            if method=='D' and result.get('request')=={'manuscript_sha256':paper['hash'],'before':'2024-10-01'}:
                write(DATA/'product-replays'/(paper['hash']+'-ICLR-2024-10-01.json'),result)
        with duckdb.connect() as db:
            row=db.execute("select decision,reviews from read_parquet(?) where paper_id=? and year='2025'",[str(DATA/'raw/reviews.parquet'),p['id']]).fetchone()
        if row:write(run_dir/p['id']/'truth.json',dict(decision=row[0],reviews=row[1]))
    if failures:raise RuntimeError(f'Unfinished paper/method evaluations: {failures}')
if __name__=='__main__':
    parser=argparse.ArgumentParser();parser.add_argument('--paper');parser.add_argument('--limit',type=int);parser.add_argument('--methods',default='ABCD')
    asyncio.run(main(parser.parse_args()))
