"""Export blinded matching packets and aggregate completed 6luna xhigh judgments."""
import argparse,csv,json,re,hashlib
from pathlib import Path
import sys
sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
from reviewarena.kb import DATA,accepted_decision
from scipy.stats import spearmanr
from sklearn.metrics import roc_auc_score
from run import write
from import_judgments import validate
import numpy as np

def issues(run):
    out=[]
    for r in run['reviews']:
        for key,v in r['report'].items():
            if not key.lower().startswith('weak'):continue
            for text in v if isinstance(v,list) else [v]:
                if text and text not in out:out.append(text)
    return out

def prepare(run_root,judging_root):
    for f in run_root.glob('*/[ABCD].json'):
        paper=f.parent.name
        ref=DATA/'truth-labels'/(paper+'.json')
        if not ref.exists():continue
        run=json.loads(f.read_text());pred=issues(run)
        write(judging_root/'judge-input'/paper/f.name,dict(predicted=pred,reference=json.loads(ref.read_text())))

def score_metrics(rows):
    ranks=[(r['score'],r['actual_score']) for r in rows if r['score'] is not None and r['actual_score'] is not None]
    decisions=[(r['actual_decision']=='Accept',r['observed_acceptance']) for r in rows if r['actual_decision'] in ('Accept','Reject') and r['observed_acceptance'] is not None]
    scored_decisions=[(r['actual_decision']=='Accept',r['score']) for r in rows
                      if r['actual_decision'] in ('Accept','Reject') and r['score'] is not None]
    def auc(pairs):
        return float(roc_auc_score(*zip(*pairs))) if len({label for label,_ in pairs})==2 else None
    def correlation(pairs):
        if len(pairs)>2 and all(len(set(values))>1 for values in zip(*pairs)):
            return float(spearmanr(*zip(*pairs)).statistic)
        return None
    complete=[(r['score'],r['actual_score']) for r in rows
              if r['scoring_reviewers']==r['assigned_reviewers']==3 and r['actual_score'] is not None]
    panel_counts={str(n):sum(r['scoring_reviewers']==n for r in rows) for n in range(4)}
    return dict(score_pairs=len(ranks),spearman=correlation(ranks),scoring_panel_counts=panel_counts,
                complete_score_pairs=len(complete),complete_panel_spearman=correlation(complete),decision_pairs=len(decisions),auc=auc(decisions),
                accepted_decision_pairs=sum(label for label,_ in decisions),score_based_auc=auc(scored_decisions),
                score_based_auc_pairs=len(scored_decisions),score_based_auc_accepted=sum(label for label,_ in scored_decisions))


def paired_summary(out,complete):
    paired={'paper_ids':sorted(complete),'papers':len(complete),'methods':{}}
    for method in 'ABCD':
        rows=[r for r in out if r['method']==method and r['paper'] in complete]
        totals={k:sum(r[k] for r in rows) for k in ('predictions','references','matched_predictions','matched_references')}
        totals['micro_precision']=totals['matched_predictions']/totals['predictions'] if totals['predictions'] else None
        totals['micro_recall']=totals['matched_references']/totals['references'] if totals['references'] else None
        totals['no_prediction_papers']=sum(r['predictions']==0 for r in rows)
        if rows and 'actual_score' in rows[0]:totals.update(score_metrics(rows))
        paired['methods'][method]=totals
    return paired

def summarize(run_root,judging_root):
    out=[]
    protocols={}
    for f in sorted(run_root.glob('*/[ABCD].json')):
        gt=f.parent/'truth.json'
        if not gt.exists():continue
        r=json.loads(f.read_text())
        signature=hashlib.sha256(json.dumps(r.get('protocol'),sort_keys=True).encode()).hexdigest()
        protocols.setdefault(f.stem,{}).setdefault(signature,[]).append(f.parent.name)
        truth=json.loads(gt.read_text());scores=[]
        for rr in r['reviews']:
            try:
                val=float(rr['report']['score'])
                if 1<=val<=10:scores.append(val)
            except (KeyError,ValueError,TypeError):pass
        ratings=[float(m.group()) for item in truth['reviews'] if (m:=re.match(r'\s*\d+(\.\d+)?',str(item.get('rating',''))))]
        row=dict(paper=f.parent.name,method=f.stem,scoring_reviewers=len(scores),assigned_reviewers=len(r['reviews']),score=sum(scores)/len(scores) if scores else None,actual_score=sum(ratings)/len(ratings) if ratings else None,observed_acceptance=(r.get('historical_outcome') or {}).get('rate'),actual_decision=truth['decision'],predictions=None,references=None,matched_predictions=None,matched_references=None,precision=None,recall=None)
        judge=judging_root/'judgments'/f.parent.name/f.name
        packet=judging_root/'judge-input'/f.parent.name/f.name
        judgment=json.loads(judge.read_text()) if judge.exists() else {}
        raw=packet.read_bytes() if packet.exists() else None
        if raw is not None and judgment.get('packet_sha256')==hashlib.sha256(raw).hexdigest():
            p=validate(judgment,raw,judge)
            pairs=judgment['matches']
            row.update(predictions=len(p['predicted']),references=len(p['reference']),
                       matched_predictions=len({i for i,j in pairs}),matched_references=len({j for i,j in pairs}))
            row['precision']=row['matched_predictions']/row['predictions'] if row['predictions'] else None
            row['recall']=row['matched_references']/row['references'] if row['references'] else None
        out.append(row)
    if not out:return
    root=judging_root/'metrics';root.mkdir(exist_ok=True)
    with (root/'paper.csv').open('w') as f:
        writer=csv.DictWriter(f,fieldnames=out[0]);writer.writeheader();writer.writerows(out)
    summary={}
    for method in 'ABCD':
        rows=[r for r in out if r['method']==method]
        summary[method]=dict(runs=len(rows),protocol_variants=len(protocols.get(method,{})),
                             matched_papers=sum(r['recall'] is not None for r in rows),**score_metrics(rows))
        for key in ('precision','recall'):
            values=[r[key] for r in rows if r[key] is not None];summary[method][key]=float(np.mean(values)) if values else None
    complete=set.intersection(*[{r['paper'] for r in out if r['method']==m and r['recall'] is not None} for m in 'ABCD'])
    paired=paired_summary(out,complete)
    if run_root.name=='eval-frozen':
        planned=json.loads((DATA/'iclr2025/manifest.json').read_bytes())
        paired['by_decision']={}
        for name,accepted in [('Accepted',True),('Rejected',False)]:
            ids={p['id'] for p in planned if accepted_decision(p['decision']) is accepted}
            paired['by_decision'][name]=dict(eligible=len(ids),**paired_summary(out,complete & ids))
    audit=DATA/'metrics/heldout-input-versions.json'
    if audit.exists() and run_root.name=='eval-frozen':
        versions=json.loads(audit.read_bytes())
        cohorts={}
        for row in versions:
            cohorts.setdefault(row['timing'],set()).add(row['id'])
        by_version={name:dict(eligible=len(ids),**paired_summary(out,complete & ids)) for name,ids in cohorts.items()}
        write(root/'paired-by-input-version.json',by_version)
    write(root/'protocol-cohorts.json',protocols)
    paired['multiple_protocols_within_method']=any(len(variants)>1 for variants in protocols.values())
    write(root/'paired.json',paired)
    write(root/'summary.json',summary)
if __name__=='__main__':
    parser=argparse.ArgumentParser()
    parser.add_argument('--run',default='eval',help='Evaluation output directory under data')
    args=parser.parse_args()
    run_root=DATA/args.run
    judging_root=DATA if args.run=='eval' else run_root
    prepare(run_root,judging_root);summarize(run_root,judging_root)

