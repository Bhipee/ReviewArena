"""Compare named publications recommended with and without the Scholar tool."""
import asyncio
import json
import os
from pathlib import Path
from run import DATA, write
from reviewarena.paper import parse_pdf
from reviewarena.lab import run_lab,is_draft_title
from reviewarena.tools import connect
from reviewarena.workflow import ask

TOPICS = {
    '5NTt8GFjUHkr': 'automatic selection of demonstrations for chain-of-thought prompting',
    'cp5PvcI6w8_': 'prior-data fitted networks for tabular classification',
    'NAQvF08TcyG': 'personalizing text-to-image generation from example images',
    'wCFB37bzud4': 'text generation with bidirectional language models',
}


def suggested_titles(value):
    if isinstance(value,str):
        return [value.strip()] if value.strip() else []
    if isinstance(value,list):
        return [t for item in value for t in suggested_titles(item)]
    if isinstance(value,dict):
        for key in ('title','titles'):
            if key in value:return suggested_titles(value[key])
    return []


async def main():
    os.environ.setdefault('REVIEWARENA_PUBLIC_RUN_CACHE',str(DATA/'public-cache'))
    root = DATA/'eval-lab-literature-v3'
    for paper, topic in TOPICS.items():
        name = paper+'.pdf'
        doc = parse_pdf((DATA/'iclr2023'/name).read_bytes())
        question = 'Recommend three related papers on '+topic+'. Exclude the supplied manuscript.'
        for arm in ('direct','scholar'):
            raw = root/paper/(arm+'-raw.json')
            if not raw.exists():
                if arm == 'direct':
                    answer = await ask('Recommend up to three real research papers. Return their exact published titles as {"titles":[string]}.',
                                       question=question,manuscript_excerpt=doc['pages'][0][:1500])
                    titles = suggested_titles(answer)
                else:
                    answer = await run_lab(question,{name:doc},'related-work-gap',name)
                    titles = [r['title'] for r in answer['external']]
                write(raw,dict(question=question,titles=list(dict.fromkeys(titles))[:3],answer=answer))
            packet = json.loads(raw.read_text())
            path = root/paper/(arm+'.json')
            if path.exists():continue
            verified=[]
            async with connect('scholar',[]) as lookup:
                for title in packet['titles']:
                    hits = await lookup('search_papers',query=title,limit=5)
                    match = next((r for r in hits if r['named_work_verified']),None)
                    verified.append(dict(title=title,exact_catalog_match=match,returned_records=len(hits),
                                         is_target=is_draft_title(title,doc['pages'][0])))
            write(path,dict(paper=paper,topic=topic,arm=arm,records=verified))
    summary={}
    for arm in ('direct','scholar'):
        papers=[json.loads((root/p/(arm+'.json')).read_text()) for p in TOPICS]
        records=[r for p in papers for r in p['records']]
        summary[arm]=dict(papers=len(papers),requested=3*len(papers),returned=len(records),
            catalog_confirmed=sum(bool(r['exact_catalog_match']) for r in records),
            target_recommendations=sum(r['is_target'] for r in records),
            confirmed_external=sum(bool(r['exact_catalog_match']) and not r['is_target'] for r in records))
    write(DATA/'metrics'/'lab-literature-v3.json',summary)
    print(summary,flush=True)

if __name__=='__main__':asyncio.run(main())
