"""Anchor model-suggested experimental settings to a contiguous passage in the PDF."""
from difflib import SequenceMatcher
import re
from .model import ModelJSONError

WORDS=re.compile(r'\w+',re.UNICODE)


def evidence_span(page,name,quote):
    if name.casefold() not in quote.casefold():return None
    if quote in page:return quote
    spans=list(WORDS.finditer(page))
    actual=[m[0].casefold() for m in spans]
    proposed=[w.casefold() for w in WORDS.findall(quote)]
    blocks=SequenceMatcher(None,actual,proposed,autojunk=False).get_matching_blocks()
    for start,_,length in sorted(blocks,key=lambda b:-b.size):
        if length<6:break
        anchor=page[spans[start].start():spans[start+length-1].end()]
        if len(anchor)>=24 and name.casefold() in anchor.casefold():return anchor
    return None


def grounded_settings(suggestions,pages):
    settings=[]
    seen=set()
    for item in suggestions if isinstance(suggestions,list) else []:
        if not isinstance(item,dict):continue
        name=item.get('name');quote=item.get('quote');kind=item.get('kind');page=item.get('page')
        if kind not in ('dataset','baseline','model','metric') or not isinstance(name,str) or not name.strip() or not isinstance(quote,str) or len(quote.strip())<12:continue
        key=(kind,name.casefold())
        if key in seen:continue
        preferred=page if type(page) is int and 1<=page<=len(pages) else None
        matches=[]
        order=([preferred] if preferred else [])+[i for i in range(1,len(pages)+1) if i!=preferred]
        for i in order:
            if name.casefold() not in pages[i-1].casefold():continue
            anchor=evidence_span(pages[i-1],name,quote)
            if anchor:
                matches.append((i,anchor))
                if i==preferred:break
        if len(matches)==1:
            i,anchor=matches[0]
            settings.append(dict(kind=kind,name=name,page=i,quote=anchor));seen.add(key)
    return settings


async def check_setting_mentions(suggestions,pages,settings,ask):
    known={(r['kind'],r['name'].casefold()) for r in settings}
    choices=[]
    for r in suggestions if isinstance(suggestions,list) else []:
        if not isinstance(r,dict):continue
        name=r.get('name');kind=r.get('kind')
        if not isinstance(name,str) or len(name.strip())<3 or kind not in ('dataset','baseline','model','metric') or (kind,name.casefold()) in known:continue
        preferred=r.get('page')
        order=sorted(range(1,len(pages)+1),key=lambda n:n!=preferred)
        matches=0
        for page in order:
            for occurrence in re.finditer(re.escape(name),pages[page-1],re.I):
                a,b=occurrence.span()
                snippet=pages[page-1][max(0,a-130):min(len(pages[page-1]),b+150)]
                choices.append(dict(kind=kind,name=name,page=page,quote=snippet))
                matches+=1
                if matches==3:break
            if matches==3:break
    if not choices:return settings
    try:
        answer=await ask('Select the passages that explicitly establish the authors used the stated dataset, model, metric, or baseline in this paper. Exclude general mentions, future work, and references to what other authors did. Return {"choices":[integer passage IDs]}. Select at most one per named setting. You may return an empty list.',passages=[dict(id=n,**p) for n,p in enumerate(choices,1)])
    except ModelJSONError:
        return settings
    selected=answer.get('choices')
    for identifier in selected if isinstance(selected,list) else []:
        if type(identifier) is not int or not 1<=identifier<=len(choices):continue
        row=choices[identifier-1];key=(row['kind'],row['name'].casefold())
        if key not in known:
            settings.append(row);known.add(key)
    return settings
