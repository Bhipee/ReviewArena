"""Leave one historical manuscript out and recover its reviewed critique family."""
from collections import defaultdict

import numpy as np
import pyarrow.parquet as pq
from run import DATA,write
from reviewarena.embedding import embed
from reviewarena.kb import current_snapshot


def tie_metrics(scores,target):
    above=sum(v>scores[target] for v in scores.values())
    tied=sum(v==scores[target] for v in scores.values())
    return dict(top1=max(0,min(1,(1-above)/tied)),top5=max(0,min(1,(5-above)/tied)),
                reciprocal_rank=sum(1/(above+j) for j in range(1,tied+1))/tied)


def evaluate():
    snapshot=current_snapshot()
    source=pq.read_table(snapshot/'taxonomy.parquet',columns=['category','family','family_assignment']).to_pylist()
    families={r['category']:r['family'] for r in source if r['family_assignment']=='reference member'}
    rows=[r for r in pq.read_table(snapshot/'critique.parquet').to_pylist() if r['category'] in families and r.get('abstract')]
    rows.sort(key=lambda r:(r['paper_id'],r['review_id'],r['id']))
    groups=[families[r['category']] for r in rows]
    fields={'trigger':'trigger_text','abstract':'abstract'}
    similarities={}
    for name,field in fields.items():
        texts=list(dict.fromkeys(r[field] for r in rows))
        lookup={t:i for i,t in enumerate(texts)}
        queries=embed(['Represent this sentence for searching relevant passages: '+t for t in texts])
        scores=queries@embed(texts).T
        indices=[lookup[r[field]] for r in rows]
        similarities[name]=scores[np.ix_(indices,indices)]
    queries={}
    for i,row in enumerate(rows):queries.setdefault((row['paper_id'],groups[i]),i)
    results=[]
    for (paper,target),i in queries.items():
        normalized=' '.join(rows[i]['trigger_text'].casefold().split())
        candidates=[j for j,r in enumerate(rows) if r['paper_id']!=paper and ' '.join(r['trigger_text'].casefold().split())!=normalized]
        choices={groups[j] for j in candidates}
        if target not in choices:continue
        case=dict(paper_id=paper,review_id=rows[i]['review_id'],target_family=target,eligible_families=len(choices))
        for method,matrix in similarities.items():
            best=defaultdict(lambda:-np.inf)
            for j in candidates:best[groups[j]]=max(best[groups[j]],float(matrix[i,j]))
            case[method]=tie_metrics(best,target)
        count=len(choices)
        case['uniform']=dict(top1=1/count,top5=min(5,count)/count,reciprocal_rank=sum(1/j for j in range(1,count+1))/count)
        results.append(case)
    methods={m:{k:float(np.mean([r[m][k] for r in results])) for k in ('top1','top5','reciprocal_rank')}
             for m in ('abstract','trigger','uniform')} if results else {}
    summary=dict(snapshot=snapshot.name,reference_pairs=len(rows),eligible_queries=len(results),total_queries=len(queries),
                 unique_query_papers=len({r['paper_id'] for r in results}),methods=methods)
    write(DATA/'metrics/retrieval-family-diagnostic.json',dict(**summary,cases=results))
    print(summary)


if __name__=='__main__':
    evaluate()
