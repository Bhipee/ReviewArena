"""Prepare independent annotation sheets and compute agreement after both are filled."""
import argparse,csv,json,random,sys,hashlib
from pathlib import Path
sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
from reviewarena.kb import DATA
from sklearn.metrics import cohen_kappa_score
from run import write
from import_judgments import validate
def sheets(root=DATA):
    folder=root/'human-audit'
    folder.mkdir(exist_ok=True)
    key=folder/'sample-key.json'
    if key.exists():
        sample=json.loads(key.read_text())
    else:
        rows=[]
        for f in sorted((root/'judge-input').glob('*/*.json')):
            raw=f.read_bytes()
            packet=json.loads(raw)
            digest=hashlib.sha256(raw).hexdigest()
            for i,pred in enumerate(packet['predicted']):
                for j,ref in enumerate(packet['reference']):
                    rows.append(dict(pair_id=f'{f.parent.name}/{f.stem}/{i}/{j}',packet_sha256=digest,
                                     prediction=pred,review_critique=ref['paraphrase']))
        if len(rows)<100:raise ValueError('At least 100 eligible pairs are required.')
        if any((folder/(name+'.csv')).exists() for name in ('rater1','rater2')):
            raise ValueError('Existing legacy rating sheets are already available. Use --score after annotation.')
        sample=random.Random(16).sample(rows,100)
        key.write_text(json.dumps(sample,indent=2))
    for name in ('rater1','rater2'):
        path=folder/(name+'.csv')
        if path.exists():continue
        with path.open('x') as out:
            w=csv.DictWriter(out,fieldnames=['sample_id','prediction','review_critique','same_issue'])
            w.writeheader()
            for index,row in enumerate(sample):
                w.writerow(dict(sample_id=index,prediction=row['prediction'],review_critique=row['review_critique'],same_issue=''))
    print('Prepared',len(sample),'blind pairs per annotator')
def agreement(root=DATA,status_only=False):
    def read(n):
        with (root/'human-audit'/f'{n}.csv').open() as f:
            rows=list(csv.DictReader(f))
        if rows and 'sample_id' in rows[0]:
            key=json.loads((root/'human-audit/sample-key.json').read_text())
            for r in rows:
                if not r['sample_id'].isdigit() or not 0<=int(r['sample_id'])<len(key):raise ValueError('Unknown sample ID')
                source=key[int(r['sample_id'])]
                if any(r[field]!=source[field] for field in ('prediction','review_critique')):raise ValueError('Changed source in '+r['sample_id'])
                r.update(pair_id=source['pair_id'],packet_sha256=source['packet_sha256'])
        if len(rows)!=100 or len({r['pair_id'] for r in rows})!=100:raise ValueError('Need 100 distinct pairs per rater')
        for r in rows:
            paper,method,i,j=r['pair_id'].split('/')
            packet=(root/'judge-input'/paper/(method+'.json')).read_bytes()
            p=json.loads(packet)
            if (r.get('packet_sha256') and hashlib.sha256(packet).hexdigest()!=r['packet_sha256']) or p['predicted'][int(i)]!=r['prediction'] or p['reference'][int(j)]['paraphrase']!=r['review_critique']:
                raise ValueError('Source changed for '+r['pair_id'])
        return {r['pair_id']:r['same_issue'] for r in rows}
    a,b=read('rater1'),read('rater2')
    if a.keys()!=b.keys() or any(v not in ('','0','1') for v in (*a.values(),*b.values())):
        raise ValueError('Raters must use the same sample and enter 0 or 1.')
    judges={};hashes={}
    for pair in a:
        paper,method,i,j=pair.split('/')
        name=f'{paper}/{method}.json'
        f=root/'judgments'/name
        if not f.exists():continue
        raw=f.read_bytes()
        result=json.loads(raw)
        packet=(root/'judge-input'/name).read_bytes()
        validate(result,packet,f)
        hashes[name]=hashlib.sha256(raw).hexdigest()
        judges[pair]=str(int([int(i),int(j)] in result['matches']))
    progress=dict(pairs=len(a),papers=len({key.split('/')[0] for key in a}),
                  completed={name:sum(v!='' for v in r.values()) for name,r in [('rater1',a),('rater2',b)]},
                  judged_pairs=len(judges))
    if status_only:
        print(json.dumps(progress))
        return progress
    if any(count!=len(a) for count in progress['completed'].values()) or len(judges)!=len(a):
        raise ValueError('All 100 pairs require both independent ratings and a source-verified model judgment.')
    report=dict(sample=progress,judgment_hashes=hashes,
                rater_hashes={name:hashlib.sha256((root/'human-audit'/(name+'.csv')).read_bytes()).hexdigest()
                              for name in ('rater1','rater2')},
                comparisons={name:compare_ratings([left[i] for i in a],[right[i] for i in a]) for name,left,right in
                             [('inter_rater',a,b),('rater1_vs_model',a,judges),('rater2_vs_model',b,judges)]})
    for name in ('rater1_vs_model','rater2_vs_model'):
        counts=report['comparisons'][name]['counts']
        conditional={}
        for model_label,description in [('1','model_match'),('0','model_nonmatch')]:
            total=counts['0'+model_label]+counts['1'+model_label]
            agreed=counts[model_label+model_label]
            conditional[description]=dict(assessed_pairs=total,agreed_pairs=agreed,
                                         agreement_rate=agreed/total if total else None)
        report['comparisons'][name]['agreement_by_model_decision']=conditional
    write(root/'metrics/human-agreement.json',report)
    print(json.dumps(report['comparisons'],indent=2))
    return report


def compare_ratings(left,right):
    if not left or len(left)!=len(right):raise ValueError('Need paired ratings.')
    n=len(left)
    table={x+y:sum(a==x and b==y for a,b in zip(left,right)) for x in ('0','1') for y in ('0','1')}
    return dict(pairs=n,counts=table,observed_agreement=(table['00']+table['11'])/n,
                kappa=float(cohen_kappa_score(left,right)) if len(set(left)|set(right))>1 else None)


if __name__=='__main__':
    parser=argparse.ArgumentParser();parser.add_argument('--run',default='eval');action=parser.add_mutually_exclusive_group();action.add_argument('--score',action='store_true');action.add_argument('--status',action='store_true')
    args=parser.parse_args()
    root=DATA if args.run=='eval' else DATA/args.run
    if args.status or args.score:agreement(root,status_only=args.status)
    else:sheets(root)
