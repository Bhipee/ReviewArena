import asyncio
import re,unicodedata
from .model import literature_query
from functools import lru_cache
from .embedding import embed
from .workflow import ask,skill
from .tools import connect
from .paper import is_manuscript_title
from sklearn.feature_extraction.text import TfidfVectorizer

@lru_cache(maxsize=2)
def passage_vectors(texts):
    return embed(texts)

def title_occurrences(title,pages):
    def normalized(text):
        text=unicodedata.normalize('NFKD',text).casefold()
        return ''.join(char for char in text if char.isalnum())
    target=normalized(title)
    if not target:return []
    return [i for i,page in enumerate(pages,1) if target in normalized(page)]

def is_draft_title(title, opening):
    if is_manuscript_title(title,opening):return True
    def compact(text):
        return ''.join(c for c in unicodedata.normalize('NFKD',text).casefold() if c.isalnum())
    needle=compact(title)
    return len(needle)>=16 and 0<=compact(opening[:900]).find(needle)<=80


def linked_point(text, refs, passages):
    if not isinstance(text, str) or not text.strip():
        raise ValueError('The model returned an empty section. Retry the request.')
    if not isinstance(refs, list):
        refs = [refs]
    indices = dict.fromkeys(int(str(v)) for v in refs if str(v).isdigit() and 1 <= int(str(v)) <= len(passages))
    return {'text': text.strip(), 'sources': [passages[n-1] for n in indices]}


async def completed_work(records):
    empty=dict(heading='Completed work',text='No completed group activity was established from the selected meeting records.',sources=[])
    menu=[]
    seen=set()
    for record in records:
        for part in re.split(r'(?<=[.!?])\s+|\n+',record.get('page_text',record['text'])):
            quote=part.strip().lstrip('-* ').strip()
            if len(quote)<12 or quote not in record['text'] or quote in seen:continue
            if quote.startswith(('#','>')) or quote.endswith('?'):continue
            if re.match(r'(?:topic|open question|next step|action item|to.do)\s*:',quote,re.I):continue
            if re.search(r"\b(?:we (?:will|plan to|intend to|should)|(?:not yet|not) completed|next week we)\b",quote,re.I):continue
            menu.append(dict(id=record['id'],file=record['file'],page=record['page'],text=quote))
            seen.add(quote)
    if not menu:return empty
    proposal=await ask('Select the numbers of up to three statements reporting activities the group already performed or observed results from those activities. '
                       'Do not select future work, questions, uncompleted tasks, or claims about an external paper. '
                       'Return only {"completed":[1,2]} using integer statement numbers. Return an empty list if no statement qualifies.',
                       statements=[dict(number=i,text=item['text']) for i,item in enumerate(menu,1)])
    chosen=proposal.get('completed',[])
    if not isinstance(chosen,list):return empty
    indices=dict.fromkeys(i for i in chosen if type(i) is int and 1<=i<=len(menu))
    sources=[menu[i-1] for i in list(indices)[:3]]
    return dict(heading='Completed work',text=' '.join(s['text'] for s in sources),sources=sources) if sources else empty


async def weekly_result(question,passages,records):
    completed=await completed_work(records)
    # Plan from the group's own records when available. A literature-only meeting can use paper excerpts.
    chosen=list(records or passages)
    inputs=[dict(ref=i,text=p['text'][:1200],kind='group record' if i<=len(records) else 'background paper')
            for i,p in enumerate(chosen,1)]
    prompt=(skill('weekly-brief')+' Help a supervisor prepare a meeting. Use the group records as the main topic when present. '
            'Return JSON with ONLY these arrays: open_questions, proposed_steps, supervisor_questions. '
            'Each item must be an object with text (one short sentence) and ref (one integer excerpt number). '
            'Give one specific unresolved question, one concrete next action that advances the completed work, '
            'and three DISTINCT questions for the supervisor to ask, covering interpretation, error analysis, and the next test. '
            'Name the observed measurement or scientific object in each item. Address a gap implied by the result. Each question ends in a question mark. '
            'Use the facts in the cited excerpt. Do not repeat the input question, propose work already completed, '
            'report new accomplishments or write section headings. Return empty arrays where insufficient.')
    draft=await ask(prompt,meeting_topic=question,completed=completed['text'],excerpts=inputs)
    points=[completed]
    for heading,key,limit in [('Open questions','open_questions',1),('Proposed next steps','proposed_steps',1),
                              ('Supervisor questions','supervisor_questions',3)]:
        selected=[];sources={}
        label={'open_questions':r'open question','proposed_steps':r'next step|action item'}.get(key)
        if label:
            for record in records:
                match=re.search(r'(?im)^\s*(?:[-*]\s*)?(?:'+label+r')\s*:\s*(\S[^\n]*)',record['text'])
                if match and (key!='open_questions' or match[1].rstrip().endswith('?')):
                    selected.append(match[1].strip())
                    sources[record['id']]=dict(id=record['id'],file=record['file'],page=record['page'],text=match[0].strip())
                    break
        for item in ([] if selected else draft.get(key) or []):
            if not isinstance(item,dict):continue
            text=item.get('text');ref=item.get('ref')
            if not isinstance(text,str) or type(ref) is not int or not 1<=ref<=len(chosen):continue
            text=' '.join(text.split()).strip()
            if not 10<=len(text)<=280 or text.casefold()==question.strip().casefold():continue
            if key!='proposed_steps' and (not text.endswith('?') or text.count('?')!=1):continue
            if any(text.casefold()==v.casefold() for v in selected):continue
            selected.append(text)
            src=chosen[ref-1]
            sources[src['id']]={k:src[k] for k in ('file','page','id','text')}
            if len(selected)==limit:break
        body='\n'.join(f'{i}. {v}' for i,v in enumerate(selected,1)) if limit>1 else ' '.join(selected)
        points.append(dict(heading=heading,text=body or 'No source-linked item was established for this section.',sources=list(sources.values())))
    return dict(points=points,external=[],tools=[])


def topical_query(question, excerpts):
    # Recover topic terms from the question and retrieved passage when tool calling returns an empty query.
    stop=set(TfidfVectorizer(stop_words='english').get_stop_words()) | {
        'recommend','three','related','papers','paper','exclude','supplied','manuscript','draft',
        'research','references','works','please','publications','work','topic','check','find','citation','citations'}
    words=re.findall(r'[a-zA-Z][a-zA-Z0-9-]{2,}',question.lower())
    terms=list(dict.fromkeys(w for w in words if w not in stop))[:8]
    if len(terms)<2:
        vec=TfidfVectorizer(stop_words=sorted(stop),ngram_range=(1,1))
        texts=[p['text'] for p in excerpts]
        try:matrix=vec.fit_transform(texts)
        except ValueError:return ' '.join(terms)
        weights=matrix[0].toarray()[0]
        vocab=vec.get_feature_names_out()
        terms.extend(vocab[i] for i in weights.argsort()[::-1] if weights[i]>0 and vocab[i] not in terms)
    return ' '.join(terms[:8])


async def related_result(question, documents, manuscript, top):
    page=documents[manuscript]['pages'][0]
    generated=await asyncio.to_thread(literature_query,{'topic':question,'manuscript_excerpt':page[:1500]})
    fallback=topical_query(question,top)
    logs=[];records={}
    async with connect('scholar',logs) as scholar:
        for query in dict.fromkeys((generated.strip(),fallback)):
            if not query:continue
            hits=await scholar('search_papers',query=query,limit=10)
            for item in hits:
                if item.get('title') and item.get('url') and not is_draft_title(item['title'],page):
                    records.setdefault(item['title'].casefold(),dict(item))
    publications=list(records.values())
    if publications:
        query_vector=embed(['Represent this sentence for searching relevant passages: '+question])[0]
        vectors=embed([r['title']+' '+(r.get('abstract') or '')[:800] for r in publications])
        for item,score in zip(publications,vectors@query_vector):item['topic_similarity']=round(float(score),4)
        publications=sorted(publications,key=lambda r:-r['topic_similarity'])[:3]
    if not publications:
        return dict(points=[dict(text='The catalog search returned no external publications for this topic.',sources=[])],
                    external=[],tools=logs)
    manuscript_passages=[p for p in top if p['file']==manuscript]
    comparisons=[]
    for item in publications:
        item['checked_document']=manuscript
        item['title_match_pages']=title_occurrences(item['title'],documents[manuscript]['pages'])
        abstract=item.get('abstract','')
        if not abstract or not manuscript_passages:continue
        result=await ask(skill('related-work-gap')+' Identify one concrete shared idea. Return {source_quote:string, draft_quote:string}. '
                         'Copy each quote verbatim from its own source, or leave both empty if the connection is unclear.',
                         prior_abstract=abstract,draft_passages=[p['text'] for p in manuscript_passages])
        prior=result.get('source_quote');draft=result.get('draft_quote')
        if not isinstance(prior,str) or not isinstance(draft,str) or min(len(prior.strip()),len(draft.strip()))<15 or prior not in abstract:continue
        match=next((p for p in manuscript_passages if draft in p['text']),None)
        if match:comparisons.append(dict(heading=item['title'],text=f'Published abstract: “{prior}”\n\nSelected draft: “{draft}”',sources=[match]))
    if not comparisons:
        comparisons=[dict(text='See the catalog records below. The available abstracts and draft passages did not establish a specific overlap.',sources=[])]
    return dict(points=comparisons,external=publications,tools=logs)


async def run_lab(question,documents,mode,manuscript=None,meeting_records=()):
    if mode=='weekly-brief' and meeting_records:
        if not set(meeting_records).issubset(documents):raise ValueError('A selected meeting record is unavailable.')
        documents={name:doc for name,doc in documents.items() if name in meeting_records}
    passages=[]
    for name,paper in documents.items():
        for i,text in enumerate(paper['pages'],1):
            for start in range(0,len(text),1200):
                passages.append(dict(id=f'S{len(passages)+1}',file=name,page=i,text=text[start:start+1450]))
    if not passages:raise ValueError("Add at least one lab document.")
    if mode=='reviewer-2':
        from .lab_reviewer import review
        return await review(question,passages,skill(mode))
    vec=TfidfVectorizer(ngram_range=(1,2),sublinear_tf=True)
    matrix=vec.fit_transform(p['text'] for p in passages)
    scores=(matrix@vec.transform([question]).T).toarray().ravel()
    vectors=passage_vectors(tuple(p['text'] for p in passages))
    semantic=vectors@embed(['Represent this sentence for searching relevant passages: '+question])[0]
    ranked=sorted(range(len(passages)),key=lambda i:-(.65*semantic[i]+.35*scores[i]))
    if mode=='weekly-brief' and meeting_records:
        # Include each selected record before filling the remaining context with topical passages.
        first={}
        for i in ranked:
            filename=passages[i]['file']
            if filename in meeting_records:first.setdefault(filename,i)
        chosen=list(first.values())
        chosen.extend(i for i in ranked if i not in first.values())
        top=[passages[i] for i in chosen[:max(8,len(first))]]
    else:top=[passages[i] for i in ranked[:8]]
    logs=[];external=[]
    if mode=='related-work-gap':
        return await related_result(question,documents,manuscript or next(iter(documents)),top)
    candidates=[dict(ref=n+1,file=p['file'],page=p['page'],excerpt=p['text']) for n,p in enumerate(top)]
    if mode=='weekly-brief':
        records=[dict(p,page_text=documents[p['file']]['pages'][p['page']-1])
                 for p in top if p['file'] in meeting_records]
        return await weekly_result(question,top,records)
    result=await ask('Answer the research question using the supplied group documents. Write a concise answer grounded in the excerpts. Return JSON with exactly two keys: answer (a string), refs (a list of integer passage numbers that directly support the answer). If the material does not answer the question, say so and return an empty refs list.',question=question,excerpts=candidates,external_publications=external)
    return dict(points=[linked_point(result.get('answer'),result.get('refs',[]),top)],external=external,tools=logs)

def meeting_markdown(question,result,agreed_decision=None):
    lines=['# Research meeting notes',question]
    citations={}
    for point in result['points']:
        if point.get('heading'):lines.append('## '+point['heading'])
        refs=[]
        for item in point['sources']:
            key=(item['file'],item['page'],item['text'],item['id'])
            refs.append(citations.setdefault(key,len(citations)+1))
        text=point['text']
        lines.append(text+(' '+''.join(f'[^{n}]' for n in dict.fromkeys(refs)) if refs else ' *(No linked passage.)*'))
    if agreed_decision:
        lines.extend(['## Decision agreed by the group',agreed_decision])
    if citations:
        lines.append('## Source passages')
        for (filename,page,quote,source_id),n in citations.items():
            lines.append(f'[^{n}]: {filename}, p. {page} ({source_id}) — '+quote.replace('\n','\n    '))
    if result.get('external'):
        lines.append('## Publications')
        for item in result['external']:
            entry=f"- [{item['title']}]({item['url']}) · {item['catalog']} · {item['published']}"
            if item.get('checked_document'):
                pages=', '.join(map(str,item.get('title_match_pages',[])))
                status='exact title on p. '+pages if pages else 'no exact title match'
                entry+=f" · {item['checked_document']}: {status}"
            lines.append(entry)
    return '\n\n'.join(lines)
