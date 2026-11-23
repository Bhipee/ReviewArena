"""Trace works mentioned by a reviewer to dated catalog records and manuscript passages."""
import re

from .named_works import resolve_title
from .tools import connect


def local_passages(paper,mention):
    term=re.compile(r'(?<!\w)'+re.escape(mention)+r'(?!\w)',re.I)
    title=re.compile(term.pattern+r'\s*:\s*[^.!?]{8,210}[.!?]',re.I)
    caption=re.compile(r'\bTable\s+\d+[A-Za-z]?\s*[.:]\s*',re.I)
    titles=[];tables=[]
    reference_sections=[s for s in paper.get('sections',[]) if
        re.fullmatch(r'(?:[0-9]+\.?\s+)?(?:references|bibliography)',s['heading'],re.I)]
    for page,body in enumerate(paper['pages'],1):
        bibliography=''
        for section in reference_sections:
            if section['start_page']<=page<=section['end_page']:
                bibliography=body
                if page==section['start_page']:
                    marker=body.casefold().find(section['heading'].casefold())
                    if marker>=0:bibliography=body[marker+len(section['heading']):]
                break
        for found in title.finditer(bibliography):
            text=found.group()
            if text[:-1].lower() not in [r['quote'][:-1].lower() for r in titles]:
                titles.append(dict(page=page,quote=text))
        for found in caption.finditer(body):
            rest=body[found.end():found.end()+700]
            end=re.search(r'[.!?](?=\s+[A-Z(]|$)',rest)
            if end is None:continue
            text=body[found.start():found.end()+end.end()]
            if term.search(text) and re.search(r'compar|performance|accuracy|evaluation|results?',text,re.I):
                tables.append(dict(page=page,quote=text))
    return titles[:2],tables[:3]


async def inspect_comparison(paper,comment,before,ask):
    from datetime import date
    date.fromisoformat(before)
    parsed=await ask('List publications or named methods explicitly mentioned in this reviewer comment. '
        'Return a JSON object with works, an array of objects with mention (an exact name from the comment) '
        'and title (the full paper title if known, otherwise the mention). Exclude datasets and generic '
        'method classes. Return an empty list when there is no named method or paper.',reviewer_comment=comment)
    candidates={}
    for row in parsed.get('works') or []:
        if not isinstance(row,dict):continue
        mention=row.get('mention')
        if isinstance(mention,str) and len(mention.strip())>=2 and mention in comment:
            title=row.get('title')
            candidates[mention]=title if isinstance(title,str) and title.strip() else mention
    # A printed bibliography entry can establish a name even when the model omits it.
    for name in re.findall(r'\b[A-Za-z][\w-]{2,}\b',comment):
        if sum(ch.isupper() for ch in name)>=2 and name not in candidates and local_passages(paper,name)[0]:
            candidates[name]=name
    works=[];logs=[]
    if candidates:
        async with connect('scholar',logs) as catalog:
            for mention,suggestion in candidates.items():
                bibliography,tables=local_passages(paper,mention)
                query=bibliography[0]['quote'].rstrip('.!?') if bibliography else suggestion
                alias=re.sub(r'[^a-z0-9]','',mention.casefold())
                normalized=re.sub(r'[^a-z0-9]','',query.casefold())
                record=await resolve_title(catalog,query,before) if bibliography or alias and alias in normalized else None
                works.append(dict(mention=mention,query=query,catalog_record=record,
                                  bibliography=bibliography,comparison_passages=tables))
    return dict(manuscript_sha256=paper['hash'],reviewer_comment=comment,before=before,works=works,tools=logs)
