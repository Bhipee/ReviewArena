"""Produce a traceable error-analysis sheet from judged public evaluations."""
import argparse
import csv
import json
from run import DATA
from import_judgments import validate


def export(root):
    dest=root/'metrics'/'error-analysis.csv'
    dest.parent.mkdir(parents=True,exist_ok=True)
    rows=[]
    for f in sorted((root/'judgments').glob('*/*.json')):
        packet_path=root/'judge-input'/f.relative_to(root/'judgments')
        judgment=json.loads(f.read_bytes())
        packet=validate(judgment,packet_path.read_bytes(),f)
        pairs={tuple(pair) for pair in judgment['matches']}
        pred,reference=packet['predicted'],packet['reference']
        matched_pred={i for i,_ in pairs}
        matched_ref={j for _,j in pairs}
        def emit(kind,i=None,j=None):
            issue=pred[i] if i is not None else ''
            if not isinstance(issue,str):issue=json.dumps(issue,ensure_ascii=False)
            ref=reference[j] if j is not None else {}
            rows.append([f.parent.name,f.stem,kind,i,j,issue,ref.get('review_index'),ref.get('paraphrase',''),ref.get('quote','')])
        for i,j in sorted(pairs):emit('semantic_match',i,j)
        for i in range(len(pred)):
            if i not in matched_pred:emit('prediction_without_review_match',i=i)
        for j in range(len(reference)):
            if j not in matched_ref:emit('missed_reference_issue',j=j)
    tmp=dest.with_suffix('.tmp')
    with tmp.open('w',newline='') as file:
        writer=csv.writer(file)
        writer.writerow(['paper','method','category','prediction_index','reference_index','prediction','review_index','reference_issue','review_quote'])
        writer.writerows(rows)
    tmp.replace(dest)
    print(len(rows),'evidence rows ->',dest)


if __name__=='__main__':
    parser=argparse.ArgumentParser();parser.add_argument('--run',default='eval-frozen')
    args=parser.parse_args();export(DATA if args.run=='eval' else DATA/args.run)
