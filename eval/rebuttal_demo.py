import sys,json,asyncio,hashlib,os
from pathlib import Path
sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
from reviewarena.kb import DATA
from reviewarena.paper import parse_pdf
from reviewarena.workflow import rebuttal
from run import write
async def main():
    paper_id='k2ZVAzVeMP'
    paper=parse_pdf((DATA/'iclr2025'/(paper_id+'.pdf')).read_bytes())
    quote=json.loads((DATA/'truth-labels'/(paper_id+'.json')).read_text())[0]['quote']
    os.environ.setdefault('REVIEWARENA_PUBLIC_RUN_CACHE',str(DATA/'public-cache'))
    res=await rebuttal(paper,quote)
    key=paper['hash']+'-'+hashlib.sha256(quote.encode()).hexdigest()
    if not res['responses'] or any(item['critique'] not in quote for item in res['responses']):
        raise ValueError('A reply could not be traced to the pasted reviewer text')
    for item in res['responses']:
        if item['answer']['action']=='clarify' and not any(ev.get('role')=='addresses' and ev == item['answer'].get('existing_evidence') for ev in item['evidence']):
            raise ValueError('A clarification needs a quotation that answers the concern')
        for ev in item['evidence']:
            if ev['quote'] not in paper['pages'][ev['page']-1]:
                raise ValueError('A reply cited a passage outside the manuscript')
    write(DATA/'rebuttal-replays'/(key+'.json'),dict(manuscript_sha256=paper['hash'],review_sha256=hashlib.sha256(quote.encode()).hexdigest(),quote=quote,result=res))
    print('Verified',len(res['responses']),'point-by-point responses',flush=True)
if __name__=='__main__':asyncio.run(main())
