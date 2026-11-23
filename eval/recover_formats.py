"""Recover failed JSON generations under an explicit, separate formatting protocol."""
import argparse
import asyncio
import hashlib
import json
import os,sys
from pathlib import Path
from threading import Lock
from format_failure import format_failure
RUNTIME=Path(__file__).resolve().parents[1]/'.evaluation-runtime/baseline-v1'
sys.path.insert(0,str(RUNTIME/'eval'))
from run import DATA,write
from reviewarena import workflow,model,verifier

FORMAT = (' Keep each scalar under two sentences and each list to at most three entries. '
          'For an individual reviewer report return exactly the six requested fields once. '
          'Emit the closing brace immediately after the final field. Do not enumerate further examples.')


VERIFIER_FORMAT = (' Output only the four keys verdict, refs, quote, reason. For quote, select at most '
                   'eighteen consecutive words verbatim from a single supplied passage. The reason must '
                   'fit on one line and contain at most sixteen words. Return a complete JSON object.')


def main(paper,method,source):
    original=model.generate
    recovered=[]
    verifier_retries=[]
    lock=Lock()
    def bounded(task,payload):
        try:
            return original(task,payload)
        except ValueError as exc:
            if str(exc)!='Model returned invalid JSON twice.':raise
        digest=hashlib.sha256(json.dumps([task,payload],sort_keys=True,ensure_ascii=False).encode()).hexdigest()
        try:
            result=original(task+FORMAT,payload)
        except ValueError as exc:
            if str(exc)!='Model returned invalid JSON twice.' or 'target_passages' not in payload:
                raise
            result=original(task+VERIFIER_FORMAT,payload)
            with lock:verifier_retries.append(digest)
        with lock:recovered.append(digest)
        return result
    namespace=source+'-format-recovery'
    failure=DATA/'eval-errors'/source/paper/(method+'.json')
    if not failure.is_file() or not format_failure(json.loads(failure.read_text())['error']):
        raise ValueError('No recorded JSON-format failure for this run')
    os.environ['REVIEWARENA_RUN_NAMESPACE']=namespace
    os.environ['REVIEWARENA_KB_SNAPSHOT']=str(DATA/'eval-frozen'/'indexes')
    os.environ.setdefault('REVIEWARENA_PUBLIC_RUN_CACHE',str(DATA/'public-cache'))
    model.generate=workflow.generate=verifier.generate=bounded
    output=DATA/namespace/paper/(method+'.json')
    if output.exists():
        print('Recovery output already exists:',output)
        return
    if source=='eval-early':
        manifest=json.loads((DATA/'iclr2025-early/manifest.json').read_bytes())
        entry=next(r for r in manifest if r['id']==paper and r.get('path'))
        path=entry['path']
        source_url=entry['source']
    else:
        manifest=json.loads((DATA/'iclr2025/manifest.json').read_bytes())
        entry=next(r for r in manifest if r['id']==paper)
        path='iclr2025/'+paper+'.pdf'
        source_url=entry['url']
    raw=(DATA/path).read_bytes()
    digest=hashlib.sha256(raw).hexdigest()
    if digest!=entry['sha256']:
        raise ValueError('Recovery manuscript bytes differ from their source manifest')
    if source=='eval-early':
        recorded=json.loads(failure.read_bytes())
        if (recorded.get('input_sha256'),recorded.get('path'))!=(digest,path):
            raise ValueError('Early recovery manuscript differs from the failed input')
    from reviewarena.paper import parse_pdf
    result=asyncio.run(workflow.run_review(parse_pdf(raw),'ICLR',method,'2024-10-01'))
    result['recovery_input']={'sha256':digest,'path':path,'source':source_url}
    truth=DATA/source/paper/'truth.json'
    if truth.exists():write(output.parent/'truth.json',json.loads(truth.read_bytes()))
    result['protocol']['format_recovery']={'retry_instruction':FORMAT,'recovered_call_hashes':recovered,
                                        'source_namespace':source}
    if verifier_retries:
        result['protocol']['format_recovery'].update(verifier_retry_instruction=VERIFIER_FORMAT,
                                                    verifier_retry_call_hashes=verifier_retries)
    write(output,result)


if __name__=='__main__':
    parser=argparse.ArgumentParser()
    parser.add_argument('paper');parser.add_argument('method',choices=list('ABCD'))
    parser.add_argument('--source',choices=['eval-frozen','eval-early'],default='eval-frozen')
    args=parser.parse_args();main(args.paper,args.method,args.source)
