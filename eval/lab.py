import asyncio,json,sys
from pathlib import Path
sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
from reviewarena.kb import DATA
from reviewarena.paper import parse_pdf
from reviewarena.lab import run_lab
from reviewarena.workflow import ask
from run import write
async def main():
    items=json.loads(Path(__file__).with_name('lab_qa.json').read_text())
    docs={i['paper_id']+'.pdf':parse_pdf((DATA/'iclr2023'/(i['paper_id']+'.pdf')).read_bytes()) for i in items}
    for n,item in enumerate(items):
        out=DATA/'eval-lab'/f'{n:02}.json'
        if out.exists():continue
        raw=await ask("Answer the research question without retrieving documents. Return {answer:string,source:string,page:integer or null}.",question=item['question'])
        rag=await run_lab(item['question'],docs,'question')
        cites=[s for p in rag['points'] for s in p['sources']]
        correct_page=any(s['file']==item['paper_id']+'.pdf' and s['page']==item['page'] for s in cites)
        write(out,dict(reference=item,baseline=raw,rag=rag,retrieved_cited_reference_page=correct_page))
if __name__=='__main__':asyncio.run(main())
