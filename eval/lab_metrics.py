"""Summarize citation-page matches separately from the scientific correctness of answers."""
import json
from pathlib import Path

def summarize(paths):
    items=[]
    for path in sorted(paths):
        record=json.loads(path.read_text())
        reference=record['reference']
        expected=(reference['paper_id']+'.pdf',reference['page'])
        cited={(s['file'],s['page']) for point in record['rag']['points'] for s in point['sources']}
        items.append({'question':reference['question'],'matched_reference_page':expected in cited,
                      'distinct_cited_pages':len(cited),'has_answer':any(p['text'].strip() for p in record['rag']['points'])})
    return {'completed':len(items),'answers':sum(x['has_answer'] for x in items),
            'citing_reference_page':sum(x['matched_reference_page'] for x in items),
            'distinct_cited_pages':sum(x['distinct_cited_pages'] for x in items),'items':items}

if __name__=='__main__':
    folder=Path(__file__).resolve().parents[1]/'data'
    result=summarize((folder/'eval-lab').glob('*.json'))
    target=folder/'metrics'/'lab-pages.json'
    target.parent.mkdir(exist_ok=True)
    tmp=target.with_suffix('.tmp');tmp.write_text(json.dumps(result,indent=2));tmp.replace(target)
    print({k:v for k,v in result.items() if k!='items'})
