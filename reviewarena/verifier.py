import re
from concurrent.futures import FIRST_COMPLETED, ThreadPoolExecutor, wait
from contextvars import copy_context
import numpy as np
from .embedding import embed
from .model import generate
from .transfer import HISTORICAL_CHECK_WORKERS

def passages(paper):
    out=[]
    for page,text in enumerate(paper['pages'],1):
        for m in re.finditer(r'.{1,420}(?:[.!?](?=\s|$)|\s|$)',text):
            quote=m.group().strip()
            if len(quote)>18:out.append(dict(page=page,quote=quote))
    existing={(p['page'],p['quote']) for p in out}
    out.extend(dict(page=c['page'],quote=c['quote']) for c in paper.get('captions',[]) if (c['page'],c['quote']) not in existing)
    return out


def find_captions(paper,questions,limit=2):
    """Find printed captions for the author's inspection, ordered independently for each question."""
    captions=paper.get('captions',[])
    if not captions or not questions:return [[] for _ in questions]
    from sklearn.feature_extraction.text import TfidfVectorizer
    texts=[c['quote'] for c in captions]
    vectors=embed(texts+['Represent this sentence for searching relevant passages: '+q for q in questions])
    similarity=vectors[len(captions):]@vectors[:len(captions)].T
    lexical=TfidfVectorizer(ngram_range=(1,2),stop_words='english',sublinear_tf=True)
    corpus=lexical.fit_transform(texts)
    similarity+=(lexical.transform(questions)@corpus.T).toarray()
    return [[captions[i] for i in np.argsort(-row,kind='stable')[:limit]] for row in similarity]


def ground_verdict(answer, shortlist):
    """Bind the literal quotation to an unambiguous page in the retrieved manuscript."""
    status=str(answer.get('verdict','')).strip().lower()
    refs=answer.get('refs',[])
    if not isinstance(refs,list):refs=[refs]
    anchor=answer.get('quote')
    if status not in ('valid','addressed') or not isinstance(anchor,str):
        return 'unsubstantiated',[]
    anchor=anchor.strip()
    if len(anchor)<12:return 'unsubstantiated',[]
    matches=[p for p in shortlist if anchor in p['quote']]
    if not matches:return 'unsubstantiated',[]
    cited={int(str(ref)) for ref in refs if str(ref).isdigit()}
    cited_matches=[p for p in matches if p['ref'] in cited]
    choices=cited_matches or matches
    if len({p['page'] for p in choices})!=1:return 'unsubstantiated',[]
    passage=choices[0]
    evidence={'page':passage['page'],'quote':anchor,'reason':answer.get('reason',''),
              'role':'supports' if status=='valid' else 'addresses'}
    return status,[evidence]

def parse_evidence_table(passage):
    # Some OpenReview exports concatenate Markdown table rows into one line.
    # Preserve the original passage for quoting, and expose row boundaries to the model.
    headings=[]
    table_rows=[]
    row_sources={}
    rows=re.split(r"\|\s*\|",passage)
    for i,row in enumerate(rows):
        cells=[cell.strip() for cell in row.split('|') if cell.strip()]
        if len(cells)<2 or not all(re.fullmatch(r"[-: ]+",cell) for cell in cells) or not i:
            continue
        headings=[cell.strip() for cell in rows[i-1].split('|') if cell.strip()]
        if len(headings)==len(cells):
            headings=headings[1:]
        if len(headings)!=len(cells)-1:
            continue
        for raw in rows[i+1:]:
            values=[cell.strip() for cell in raw.split('|')]
            if len(values)<len(headings)+1:
                break
            table_rows.append(dict(row=values[0],measurements=dict(zip(headings,values[1:]))))
            row_sources[values[0]]='|'.join(raw.split('|')[:len(headings)+1])
        break
    return headings, table_rows, row_sources


def check_answer_scope(question, passage):
    """Require evidence for the outcome, comparator and measurement scope in the question."""
    headings, table_rows, row_sources = parse_evidence_table(passage)
    if table_rows:
        def named(label):
            return re.search(r'(?<![\w-])'+re.escape(label)+r'(?![\w-])',question,re.I)
        names=sorted((row['row'] for row in table_rows if row['row'] and named(row['row'])),key=len,reverse=True)
        names=[name for name in names if not any(name.casefold() in longer.casefold() for longer in names if len(longer)>len(name))]
        columns=[col for col in headings if named(col)]
        if len(names)>=2 and len(columns)==1:
            column=columns[0]
            comparisons={row['row']:row['measurements'][column] for row in table_rows if row['row'] in names}
            if all(re.search(r'\d',value) for value in comparisons.values()):
                introduction=passage[:passage.find('|')][:350]
                direct=generate(
                    "Answer the question using the supplied table cells. First identify the requested measurement "
                    "and what the table measures. If the measurements agree, give the two numbers with their units as a short answer. "
                    "If a requested quantity is missing explain which in the answer. Return JSON fields "
                    "requested_measurement, table_measurement, answer and supported (boolean).",
                    dict(question=question,table_heading=introduction,column=column,measurements=comparisons))
                answer=str(direct.get('answer','')).casefold()
                # The model checks scope. Both displayed values come from the printed cells below.
                grounded=any(re.search(r'(?<![\w.])'+re.escape(value.casefold())+r'(?!\w)',answer) for value in comparisons.values())
                if direct.get('supported') is True and grounded:
                    spans=[(passage.index(row_sources[name]),len(row_sources[name])) for name in names]
                    literal=passage[min(i for i,n in spans):max(i+n for i,n in spans)]
                    return 'full',literal,column+' · '+', '.join(name+' '+value for name,value in comparisons.items())
    result=generate(
        "You are checking whether a research question can be closed using only the supplied passage. "
        "Identify what was actually measured and what the question requests. "
        "A component measurement does not establish a whole-system result. A description of planned work does not establish a completed experiment. "
        "Choose full only when the measured outcome, comparison and scope directly answer the question. "
        "Inspect the methods in the row labels and measurements under the relevant column. Choose partial only if the quoted text reports a relevant measured outcome in a narrower setting. Training settings or comparator names alone are insufficient for a question about results. A directional comparison alone does not establish statistical significance. "
        "Return JSON fields coverage (full, partial, insufficient), quote (literal text from the passage that establishes the measured outcome), and explanation (one sentence).",
        dict(question=question,table_records=table_rows,source_passage=passage,required_fields={"coverage":"full | partial | insufficient","quote":"exact source substring","explanation":"one sentence"}))
    quote=result.get('quote')
    coverage=result.get('coverage')
    if isinstance(quote,str):
        quote=quote.strip()
        if quote not in passage:
            # A model may normalize capitalization or add an introductory article.
            words=re.sub(r'^(?:the|a|an)\s+','',quote,flags=re.I).split()
            match=re.search(r'\s+'.join(re.escape(w) for w in words),passage,flags=re.I) if len(words)>=5 else None
            quote=match.group() if match else ''
    if coverage not in ('full','partial') or not isinstance(quote,str) or len(quote.strip())<12 or quote.strip() not in passage:
        return 'insufficient', '', 'The cited passage did not establish the full scope of the requested result.'
    return coverage, quote.strip(), str(result.get('explanation') or 'Inspect the scope of the cited measurement.')


def verify_many(paper,candidates,on_verified=None):
    if not candidates:return []
    if any('target_question' in c and not c['target_question'] for c in candidates):
        active=[c for c in candidates if 'target_question' not in c or c['target_question']]
        results=iter(verify_many(paper,active,on_verified))
        return [next(results) if 'target_question' not in c or c['target_question'] else
                dict(candidate=c,status='not transferred',evidence=[],searched_pages=0,
                     reason='No question grounded in the current claim was produced for this historical concern.')
                for c in candidates]
    blocks=passages(paper)
    matrix=embed([p['quote'] for p in blocks])
    questions=[c.get('target_question') or c.get('transfer_question') or c['category']+' evidence measurements limitations comparison' for c in candidates]
    queries=embed(questions)
    displays=find_captions(paper,questions)
    by_text={(b['page'],b['quote']):i for i,b in enumerate(blocks)}
    def verify_one(c,q,captions):
        order=np.argsort(-(matrix@q))
        picks=list(order[:8])
        for display in captions:
            idx=by_text[(display['page'],display['quote'])]
            if idx not in picks:picks.append(idx)
        for i in order:
            if all(blocks[j]['page']!=blocks[i]['page'] for j in picks):picks.append(i)
        for j,block in enumerate(blocks):
            if re.search(r"\b(limitations?|future work|we restrict|only evaluate)\b",block["quote"],re.I) and j not in picks:picks.append(j)
        shortlist=[dict(ref=n+1,**blocks[i]) for n,i in enumerate(picks)]
        answer=generate("Read a target paper excerpt set. Decide if the general issue named by concern_type is directly evidenced in this target. The old review explains the type only. Use valid for an explicitly evidenced weakness; addressed for evidence of the actual requested analysis or experiment; otherwise unsubstantiated. For example, an efficiency comparison needs a measured time or cost against a baseline. A hyperparameter sweep alone cannot establish speed. Return fields verdict (valid, addressed, or unsubstantiated), refs (one or two integer ref values), quote (exact substring from the first cited passage), and reason (say exactly what is measured or missing without introducing names or page numbers absent from the passage). If uncertain abstain. Do not invent or reuse an example.",dict(concern_type=c['category'],question=c.get('target_question') or c.get('transfer_question',''),target_passages=shortlist))
        status,evidence=ground_verdict(answer,shortlist)
        reason=answer.get('reason','')
        if status=='unsubstantiated':
            reason='No supporting quotation could be verified on a specific manuscript page.'
        if status=='valid':
            audit=generate("Determine what this literal quotation actually establishes. Decide independently of the first assessment. Use 'weakness' only for a specific evidenced shortcoming that the author should act on. If it reports that the relevant check was performed and supplies an answer, choose 'answer'. A description of a metric, method or experiment alone does not demonstrate a shortcoming. If neither conclusion follows choose 'insufficient'. Return a JSON object with relation (weakness, answer or insufficient) and explanation (one specific sentence tied to the quotation).",dict(research_question=c.get('target_question') or c.get('transfer_question') or c['category'],quotation=evidence[0]['quote']))
            relation=str(audit.get('relation','')).lower().strip()
            status={'weakness':'valid','answer':'addressed'}.get(relation,'unsubstantiated')
            reason=audit.get('explanation') or reason
            if status=='unsubstantiated':evidence=[]
            else:
                evidence[0]['role']='supports' if status=='valid' else 'addresses'
                evidence[0]['reason']=reason
        if status=='addressed':
            source=evidence[0]
            coverage,anchor,reason=check_answer_scope(c.get('target_question') or c.get('transfer_question') or c['category'],paper['pages'][source['page']-1])
            if coverage=='insufficient':
                status,evidence='unsubstantiated',[]
            else:
                status='addressed' if coverage=='full' else 'partially addressed'
                evidence=[dict(page=source['page'],quote=anchor,reason=reason,role='addresses' if coverage=='full' else 'partially addresses')]
        if status in ('unsubstantiated','partially addressed'):
            question=c.get('target_question') or c.get('transfer_question') or c['category']
            for caption in captions:
                coverage,anchor,explanation=check_answer_scope(question,caption['quote'])
                # Suggested captions remain available for the author's inspection.
                # Promote a secondary retrieval only when it answers the entire question.
                if coverage=='full':
                    status='addressed'
                    reason=explanation
                    evidence=[dict(page=caption['page'],quote=anchor,reason=reason,caption=caption['label'],role='addresses')]
                    break
        return dict(candidate=c,status=status,evidence=evidence,reason=reason,searched_pages=len(paper['pages']))

    if len(candidates)==1:
        result=verify_one(candidates[0],queries[0],displays[0])
        if on_verified:on_verified(1)
        return [result]

    out=[None]*len(candidates)
    next_index=0
    completed=0
    pending={}
    with ThreadPoolExecutor(max_workers=HISTORICAL_CHECK_WORKERS) as pool:
        while completed<len(candidates):
            while next_index<len(candidates) and len(pending)<HISTORICAL_CHECK_WORKERS:
                i=next_index
                # Carry this manuscript's diagnostic context into each worker.
                future=pool.submit(copy_context().run,verify_one,candidates[i],queries[i],displays[i])
                pending[future]=i
                next_index+=1
            done,_=wait(pending,return_when=FIRST_COMPLETED)
            for future in done:
                out[pending.pop(future)]=future.result()
                completed+=1
                if on_verified:on_verified(completed)
    return out
