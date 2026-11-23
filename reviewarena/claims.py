"""Anchor manuscript claims to complete, page-addressable sentences before retrieval."""
import asyncio
import re

import numpy as np

from .embedding import embed
from .lab_reviewer import CONTRIBUTION, LIMITATION


def sentences(paper):
    candidates=[]
    seen=set()
    for page,text in enumerate(paper['pages'],1):
        for sentence in re.split(r'(?<=[.!?])\s+(?=[A-Z(\[])',text):
            quote=re.sub(r'(?<=[.!?])\s+\d+(?:\.\d+)*\.?$', '',sentence.strip())
            if not 35<=len(quote)<=900 or quote in seen or len(re.findall(r'[A-Za-z]{2,}',quote))<7:
                continue
            seen.add(quote)
            candidates.append(dict(page=page,quote=quote))
    return candidates


async def ground_claims(paper,proposals,ask):
    sources=sentences(paper)
    if not sources:return []
    queries=[p['text'] for p in proposals]
    features=await asyncio.to_thread(embed,[r['quote'] for r in sources]+queries)
    scores=features[-len(queries):]@features[:len(sources)].T
    menus={}
    for i,claim in enumerate(proposals,1):
        indices=np.argsort(-scores[i-1])[:4]
        menus[i]=dict(proposed_claim=claim['text'],sentences={int(j)+1:sources[j]['quote'] for j in indices})
    answer=await ask("Select at most one source sentence per proposed claim. It must state a finding of the present manuscript "
                     "and preserve the comparator, metric and experimental conditions. A related topic, a cited paper's finding, "
                     "or a visualization alone cannot establish a stronger claim. Use 0 when no option fits. "
                     "Return JSON with selections as a list of objects, each containing integer claim_id and sentence_id.",
                     choices=menus)
    selected={}
    choices=answer.get('selections',answer.get('choices',[]))
    for item in choices if isinstance(choices,list) else []:
        if not isinstance(item,dict):continue
        i,j=item.get('claim_id'),item.get('sentence_id')
        if type(i) is int and i in menus and type(j) is int and j in menus[i]['sentences']:
            selected.setdefault(j,i)
    result=[dict(text=sources[j-1]['quote'],page=sources[j-1]['page'],
                 claim_type=proposals[i-1].get('claim_type') or '',
                 origin='source sentence selected for a proposed claim') for j,i in selected.items()]
    if len(result)<3:
        # Preserve directly attributable statements when some paraphrases are declined.
        for source in sources:
            if CONTRIBUTION.search(source['quote']) and all(item['text']!=source['quote'] for item in result):
                result.append(dict(text=source['quote'],page=source['page'],claim_type='',
                                   origin='explicit author statement'))
                if len(result)==3:break
    return result

def declared_limitations(paper):
    """Return explicit author disclosures, outside the independently verified findings."""
    strong=re.compile(r"\b(?:limitations?\s*:\s*(?:the|one|our|we)|(?:the (?:main|primary|most significant) limitation of)|our (?:main |primary )?limitation)\b",re.I)
    rows=[]
    for source in sentences(paper):
        quote=source['quote']
        if not strong.search(quote) and not LIMITATION.search(quote):continue
        if re.search(r"\b(?:they|prior work|previous work) (?:report|state|acknowledge)",quote,re.I):continue
        rows.append((0 if strong.search(quote) else 1,source))
    return [source for _,source in sorted(rows,key=lambda item:item[0])[:3]]
