"""Publish new evaluation packets and score all available verified external annotations."""
import argparse
import asyncio
import csv
import json
import subprocess
import sys
from pathlib import Path

from error_analysis import export
from format_failure import format_failure
from import_judgments import import_judgments
from metrics import prepare, summarize
from review_citations import packets, import_from, score
from run import DATA, write
from version_pairs import compare
from judgment_sensitivity import compare_annotations

from pipeline.import_truth import archived_references, verify_issues

ROOT=Path(__file__).resolve().parents[1]


def early(*args):
    subprocess.run([sys.executable,str(ROOT/'eval/early_versions.py'),*args],check=True)


def delivery_recall(root, papers):
    """Count published concerns reached by the original workflow, including failed reports."""
    with (root/'metrics/paper.csv').open(newline='') as f:
        scores={(r['paper'],r['method']):r for r in csv.DictReader(f)}
    cases={}
    for paper in papers:
        pid=paper['id']
        reference_count=len(json.loads((DATA/'truth-labels'/(pid+'.json')).read_bytes()))
        methods={}
        for method in 'ABCD':
            filename=method+'.json'
            row=scores.get((pid,method))
            if row and row['matched_references']!='':
                if int(row['references'])!=reference_count:
                    raise ValueError(f'Inconsistent reference count for {pid}/{method}')
                methods[method]=dict(delivered=True,predictions=int(row['predictions']),recovered=int(row['matched_references']))
            elif not (root/pid/filename).exists() and (DATA/'eval-errors'/root.name/pid/filename).exists():
                methods[method]=dict(delivered=False,predictions=0,recovered=0)
        if len(methods)==4:
            cases[pid]=dict(references=reference_count,methods=methods)
    total=sum(c['references'] for c in cases.values())
    methods={}
    for method in 'ABCD':
        delivered=sum(c['methods'][method]['delivered'] for c in cases.values())
        recovered=sum(c['methods'][method]['recovered'] for c in cases.values())
        with_predictions=sum(c['methods'][method]['predictions']>0 for c in cases.values())
        with_match=sum(c['methods'][method]['recovered']>0 for c in cases.values())
        methods[method]=dict(delivered_reports=delivered,reports_with_predictions=with_predictions,
                             reports_with_match=with_match,failed_reports=len(cases)-delivered,
                             recovered=recovered,recall=recovered/total if total else None)
    return dict(papers=len(cases),published_concerns=total,methods=methods,cases=cases)


def publish_frozen_coverage():
    """Account for every planned paper and method, including failures with a supplemental run."""
    import hashlib
    root=DATA/'eval-frozen'
    papers=json.loads((DATA/'iclr2025/manifest.json').read_bytes())
    counts=[]
    recoveries=[]
    failures=[]
    supplemental_scores={}
    score_file=DATA/'eval-frozen-format-recovery/metrics/paper.csv'
    if score_file.exists():
        with score_file.open(newline='') as f:
            supplemental_scores={(row['paper'],row['method']):row for row in csv.DictReader(f) if row['matched_references']!=''}
    protocols=json.loads((root/'metrics/protocol-cohorts.json').read_bytes())
    for method in 'ABCD':
        tally=dict(judged=0,awaiting_judgment=0,recorded_failure=0,awaiting_result=0)
        supplemental=0
        for paper in papers:
            path=Path(paper['id'])/(method+'.json')
            if (root/path).exists():
                packet=root/'judge-input'/path
                judgment=root/'judgments'/path
                judged=False
                if packet.exists() and judgment.exists():
                    label=json.loads(judgment.read_bytes())
                    judged=(label.get('packet_sha256')==hashlib.sha256(packet.read_bytes()).hexdigest()
                            and (label.get('model'),label.get('effort'))==('gpt-6-luna','xhigh'))
                tally['judged' if judged else 'awaiting_judgment']+=1
            elif (DATA/'eval-errors/eval-frozen'/path).exists():
                tally['recorded_failure']+=1
                failure_raw=(DATA/'eval-errors/eval-frozen'/path).read_bytes()
                error=json.loads(failure_raw)['error']
                malformed=format_failure(error)
                failures.append(dict(paper=paper['id'],method=method,error=error,
                                     invalid_json=malformed,sha256=hashlib.sha256(failure_raw).hexdigest()))
                recovery=DATA/'eval-frozen-format-recovery'/path
                if recovery.is_file():
                    if not malformed:
                        raise ValueError(f'Recovery requires an original JSON-format failure: {path}')
                    raw=recovery.read_bytes()
                    report=json.loads(raw)
                    protocol=report['protocol']['format_recovery']
                    if report['method']!=method or protocol['source_namespace']!='eval-frozen':
                        raise ValueError(f'Wrong recovery protocol for {recovery}')
                    original={k:v for k,v in report['protocol'].items() if k!='format_recovery'}
                    signature=hashlib.sha256(json.dumps(original,sort_keys=True).encode()).hexdigest()
                    if signature not in protocols.get(method,{}):
                        raise ValueError(f'Recovery model, code or index differs from primary: {recovery}')
                    source=report.get('recovery_input')
                    if source is not None:
                        expected='iclr2025/'+paper['id']+'.pdf'
                        if source['path']!=expected or source['sha256']!=paper['sha256'] or hashlib.sha256((DATA/expected).read_bytes()).hexdigest()!=source['sha256']:
                            raise ValueError(f'Recovery manuscript differs from frozen manifest: {recovery}')
                    recoveries.append(dict(paper=paper['id'],method=method,manuscript_hash_recorded=source is not None,
                                           shortened_calls=len(protocol['recovered_call_hashes']),report_sha256=hashlib.sha256(raw).hexdigest()))
                    scored=supplemental_scores.get((paper['id'],method))
                    if scored:
                        recoveries[-1]['semantic_counts']={k:int(scored[k]) for k in ('predictions','references','matched_references')}
                    supplemental+=1
            else:
                tally['awaiting_result']+=1
        counts.append(dict(method=method,**tally,supplemental=supplemental))
    write(root/'metrics/coverage.json',dict(planned=len(papers)*4,methods=counts,failures=failures,recoveries=recoveries,
               delivery_recall=delivery_recall(root,papers)))


def sync_recovery_truth(root, primary):
    """Attach ground truth once the primary runner has finished that manuscript."""
    for folder in {path.parent for path in root.glob('*/[ABCD].json')}:
        source=primary/folder.name/'truth.json'
        if not source.is_file():
            continue
        expected=json.loads(source.read_bytes())
        dest=folder/'truth.json'
        if dest.is_file():
            if json.loads(dest.read_bytes())!=expected:
                raise ValueError(f'Recovery ground truth differs from primary: {dest}')
        else:
            write(dest,expected)


def verify_report_references(root, references):
    for path in root.glob('*/truth.json'):
        if json.loads(path.read_bytes())!=references.get(path.parent.name):
            raise ValueError(f'Report reference ratings or reviews differ from the archive: {path}')


def refresh(work):
    references=archived_references(DATA)
    for path in sorted((DATA/'truth-labels').glob('*.json')):
        verify_issues(path,path.read_bytes(),references[path.stem]['reviews'])
    early('--reuse-only')
    namespaces=['frozen','early']
    namespaces.extend(base+'-format-recovery' for base in ('frozen','early')
                      if (DATA/('eval-'+base+'-format-recovery')).is_dir())
    for name in namespaces:
        root=DATA/('eval-'+name)
        if name.endswith('-format-recovery'):
            sync_recovery_truth(root,DATA/('eval-'+name.removesuffix('-format-recovery')))
        verify_report_references(root,references)
        prepare(root,root)
        packets(root)
        if name=='early':
            early('--reuse-judgments')
        label_name='recovery' if name=='frozen-format-recovery' else name
        judgments=work/('reviewarena-'+label_name+'-judgments')
        citations=work/('reviewarena-'+name+'-citations')
        for row in json.loads((DATA/'iclr2025/manifest.json').read_bytes()):
            folder=judgments/row['id']
            if folder.is_dir():import_judgments(folder,row['id'],root)
        if citations.is_dir():import_from(citations,root)
        asyncio.run(score(root))
        summarize(root,root)
        export(root)
        compare_annotations(root,work/("reviewarena-"+label_name+"-judgments-prestrict"))
        print(name,len(list(root.glob('*/[ABCD].json'))),'generation results,',
              len(list((root/'judgments').glob('*/[ABCD].json'))),'semantic judgments',flush=True)
    publish_frozen_coverage()
    compare()
    if (DATA/'eval-frozen/metrics/verifier-traces.json').exists():
        subprocess.run([sys.executable,str(ROOT/'eval/verifier_trace.py')],check=True)
    input_labels=work/'reviewarena-reviewer-input-audit'
    if input_labels.is_dir():
        subprocess.run([sys.executable,str(ROOT/'eval/reviewer_inputs.py'),'--labels',str(input_labels),
                        '--other-labels',str(work/'reviewarena-other-reviewer-audit')],check=True)
    fit_labels=work/'reviewarena-product-question-fit'
    if fit_labels.is_dir() and (DATA/'eval-product-heldout-four/plan.json').exists():
        subprocess.run([sys.executable,str(ROOT/'eval/question_fit.py'),'--labels',str(fit_labels)],check=True)



if __name__=='__main__':
    parser=argparse.ArgumentParser()
    parser.add_argument('annotation_workspace',type=Path)
    args=parser.parse_args()
    if not args.annotation_workspace.is_dir():parser.error('The annotation workspace does not exist')
    refresh(args.annotation_workspace)
