"""Prepare the page-linked manuscript reading for the public classroom example."""
import asyncio
import os

from run import DATA, write
from reviewarena.claims import declared_limitations
from reviewarena.paper import parse_pdf
from reviewarena.workflow import inspect_manuscript


async def main():
    os.environ.setdefault('REVIEWARENA_PUBLIC_RUN_CACHE',str(DATA/'public-cache'))
    paper=parse_pdf((DATA/'iclr2025/k2ZVAzVeMP.pdf').read_bytes())
    claims,paper_type,settings=await inspect_manuscript(paper)
    limitations=declared_limitations(paper)
    for entry in claims+settings+limitations:
        quote=entry.get('quote') or entry['text']
        if quote not in paper['pages'][entry['page']-1]:
            raise ValueError(f"Passage missing on page {entry['page']}")
    scope=dict(claims=claims,paper_type=paper_type,settings=settings,declared_limitations=limitations)
    write(DATA/'manuscript-replays'/(paper['hash']+'.json'),dict(manuscript_sha256=paper['hash'],scope=scope))
    print(len(claims),'claims,',len(settings),'settings,',len(limitations),'limitations')


if __name__=='__main__':
    asyncio.run(main())
