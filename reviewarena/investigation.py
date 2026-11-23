"""Role-directed, read-only investigation before a Live review."""
import asyncio
import re

from .comparisons import comparison_reviews, STOP
from .model import ModelJSONError
from .verifier import passages


async def investigate(role, paper, claims, hints, before, ask):
    trace = []
    blocks = passages(paper)
    pages = paper['pages']
    focus={
        'Theory and assumptions':'Identify the necessary premise for the central claim and check it.',
        'Experiments and evaluation':'Examine design choices such as splits, controls, baselines or metrics.',
        'Clarity and reproducibility':'Find what an independent reader needs to reproduce the procedure.'
    }.get(role,role)
    for turn in range(3):
        try:
            action = await ask(
                "Investigate the manuscript from your assigned perspective. Form your own question. "
                "Optional leads can be ignored or challenged. Seek strengths as well as weaknesses. "
                "Choose one action: search_manuscript (query: 2-6 keywords), read_page (page: integer), "
                "search_prior_work (query: technical keywords for the OpenReview abstract index), "
                "or finish when existing evidence is sufficient. Use previous observations to decide "
                "what to do next. Return a flat JSON object with question, action and its argument.",
                role=role, perspective=focus, claims=claims, optional_leads=hints, total_pages=len(pages),
                opening=pages[0][:1000] if pages else '', previous_actions=trace)
        except ModelJSONError:
            break
        name = action.get('action')
        if name == 'finish' or name not in ('search_manuscript','read_page','search_prior_work'):
            break
        argument=action.get('argument')
        params=argument if isinstance(argument,dict) else action
        query=str(params.get('query') or argument or '').removeprefix('query:').strip()[:220]
        page=params.get('page',argument)
        if isinstance(page,str) and re.fullmatch(r'(?:page[: ]*)?[0-9]+',page,re.I):
            page=int(re.search(r'[0-9]+',page).group())
        arg = page if name == 'read_page' else query
        if any(step['tool']==name and step['argument']==arg for step in trace):
            break
        step = dict(tool=name, argument=arg, question=str(action.get('question') or '')[:350], results=[])
        trace.append(step)
        if name == 'read_page' and type(page) is int and 1 <= page <= len(pages):
            content=pages[page-1]
            step['results']=[dict(page=page,quote=content[i:i+900]) for i in range(0,len(content),900)]
        elif name == 'search_manuscript' and query:
            terms=set(re.findall(r'[a-z0-9-]{2,}',query.lower()))-STOP
            ranked=sorted(((sum(t in block['quote'].lower() for t in terms),i)
                           for i,block in enumerate(blocks)),reverse=True)
            step['results']=[dict(blocks[i]) for score,i in ranked[:4] if score]
        elif name == 'search_prior_work' and query:
            rows=await asyncio.to_thread(comparison_reviews,[dict(text=query)],pages[0],before,3,abstracts=True)
            step['results']=[dict(title=r['title'],url=r['url'],quote=r['abstract'][:1400]) for r in rows]
        for i,row in enumerate(step['results'],1):
            row['id']=f'{turn+1}.{i}'
    return trace


def cited_weaknesses(items, trace, shared=()):
    evidence={r['id']:r for step in trace for r in step['results']}
    evidence.update({r['id']:r for r in shared})
    out=[]
    for item in items if isinstance(items,list) else []:
        if not isinstance(item,dict) or not isinstance(item.get('issue'),str):
            continue
        ids=item.get('evidence_ids')
        if not isinstance(ids,list) or not ids or any(str(i) not in evidence for i in ids):
            continue
        sources=[evidence[str(i)] for i in ids]
        pages=sorted({s['page'] for s in sources if 'page' in s})
        if pages:
            out.append(dict(issue=item['issue'],pages=pages,evidence=sources))
    return out
