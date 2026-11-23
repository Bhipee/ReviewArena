"""Synchronous entry points for notebooks and external evaluations."""
import asyncio,re
from pathlib import Path
from .paper import parse_pdf
from .workflow import run_review as review_async,rebuttal as rebuttal_async,inspect_manuscript,ranked_candidates,ask
from .kb import current_snapshot
from .tools import connect
from .transfer import adapt_questions,supported_question_scope,copied_without_subject
from .verifier import verify_many
from .named_works import verify_comparisons
from datetime import date

def _paper(source):
    if isinstance(source,dict) and 'pages' in source:return source
    content=source if isinstance(source,bytes) else Path(source).read_bytes()
    return parse_pdf(content)

def retrieve_candidates(paper,venue="ICLR",k=20):
    if venue not in ("ICLR","NeurIPS"):
        raise ValueError("Unknown venue")
    async def collect():
        claims,paper_type,_=await inspect_manuscript(_paper(paper))
        async with connect('reviewkb',[],current_snapshot()) as kb:
            return await ranked_candidates(kb,claims,paper_type,k)
    return asyncio.run(collect())


def verify(paper,cand,before=None):
    result=verify_many(_paper(paper),[cand])[0]
    if result['status']=='valid':
        async def check_prior_work():
            async with connect('scholar',[]) as catalog:
                await verify_comparisons([result],before or date.today().isoformat(),catalog,ask)
        asyncio.run(check_prior_work())
    return {**result,'evidence':[dict(item,text=item['quote']) for item in result['evidence']]}


def check_historical_concern(paper,candidate,before,claims=None):
    """Apply a historical question only after anchoring it to the current manuscript."""
    from .embedding import embed
    if claims is None:
        claims,_,_=asyncio.run(inspect_manuscript(paper))
    anchored=[c for c in claims if type(c.get('page')) is int and 1<=c['page']<=len(paper['pages'])
              and c.get('text') and c['text'] in paper['pages'][c['page']-1]]
    if not anchored:raise ValueError('Could not locate a source claim in the current manuscript.')
    vectors=embed([candidate['trigger_text']]+[c['text'] for c in anchored])
    claim=anchored[int((vectors[1:]@vectors[0]).argmax())]
    target=dict(candidate,matched_claim=claim['text'],matched_claim_page=claim['page'])
    asyncio.run(adapt_questions([target],ask))
    return verify(paper,target,before)


def run_review(pdf_path,venue="ICLR",method="D",before=None):
    r=asyncio.run(review_async(_paper(pdf_path),venue,method,before))
    outcome=r.get('historical_outcome') or {}
    return {**r,'accept_prob':outcome.get('rate'),'rejected_candidates':[item for item in r['checked'] if item['status'] not in ('valid','hypothesis')],'tool_logs':r['tools']}

def experiment_checklist(responses):
    def order(step):
        priority=str(step.get('priority','')).strip().casefold()
        priority={'high':'1','medium':'2','low':'3'}.get(priority,priority)
        rank=int(priority) if priority in ('1','2','3') else 4
        effort=str(step.get('effort','')).strip().casefold()
        levels={'low':1,'small':1,'medium':2,'moderate':2,'high':3,'large':3}
        duration=re.fullmatch(r'(\d+(?:\.\d+)?)\s*(hours?|hrs?|days?|weeks?)',effort)
        if duration:
            unit=duration[2][0]
            return rank,0,float(duration[1])*{'h':1,'d':24,'w':168}[unit]
        level=levels.get(effort,float(effort) if effort.isdecimal() else None)
        return (rank,1,level) if level is not None else (rank,2,0)
    return sorted((r['answer'] for r in responses if r['answer'].get('experiment')),key=order)


def rebuttal_markdown(responses):
    lines=[]
    for index,item in enumerate(responses,1):
        action=item['answer']['action']
        answer=item['answer']
        lines.extend([f"## Reviewer point {index}",item['critique']])
        if 'next_step' in answer:
            source=answer.get('existing_evidence')
            evidence=f"Page {source['page']} · {source['quote']}" if source else 'No supporting passage selected for this point.'
            lines.extend(['**Existing manuscript evidence**',evidence,'**Suggested next step**',answer['next_step']])
        lines.extend([f"**Response to reviewer ({action})**",answer['draft']])
    steps=experiment_checklist(responses)
    if steps:
        lines.append("## Experiment checklist")
        lines.extend(f"- [ ] Priority {s.get('priority','unassigned')} · {s.get('effort','to estimate')} · {s['experiment']}" for s in steps)
    return "\n\n".join(lines)


def run_rebuttal(paper,review_text):
    r=asyncio.run(rebuttal_async(_paper(paper),review_text))
    return {**r,'experiment_todo':experiment_checklist(r['responses']),'markdown':rebuttal_markdown(r['responses'])}

def author_questions(paper,checked):
    """Collect applicable open questions whose triggering claim can be checked on the input page."""
    questions=[]
    seen=set()
    for item in checked:
        if item['status'] not in ('unsubstantiated','partially addressed'):continue
        c=item['candidate']
        question=c.get('target_question')
        claim=c.get('matched_claim')
        page=c.get('matched_claim_page')
        if not question or not claim or type(page) is not int or not 1<=page<=len(paper['pages']):continue
        if claim not in paper['pages'][page-1] or not supported_question_scope(claim,question):continue
        if copied_without_subject(question,c.get('transfer_question') or c['critique_text'],c.get('question_anchor','')):continue
        if question.casefold() in seen:continue
        seen.add(question.casefold())
        evidence=[]
        for passage in item.get('evidence',[]):
            number=passage.get('page')
            quote=passage.get('quote')
            if type(number) is int and 1<=number<=len(paper['pages']) and quote and quote in paper['pages'][number-1]:
                evidence.append(dict(page=number,quote=quote))
        questions.append(dict(question=question,claim=claim,page=page,source=c['source'],source_quote=c['critique_text'],status=item['status'],evidence=evidence))
    return questions


def author_question_notes(rows, *, manuscript=None, pdf_sha256=None):
    lines=['# Questions for manuscript revision']
    if manuscript:
        lines.extend(['', manuscript])
    if pdf_sha256:
        lines.append('Reviewed PDF (SHA-256): '+pdf_sha256)
    for row in rows:
        lines.extend(['','- [ ] '+row['question'],f"  - Manuscript p. {row['page']}: "+row['claim']])
        for passage in row.get('evidence',[]):
            lines.append(f"  - Partial answer, p. {passage['page']}: "+passage['quote'])
        for caption in row.get('captions',[]):
            lines.append(f"  - Caption for inspection, {caption['label']}, p. {caption['page']}: "+caption['quote'])
        if row.get('source_quote'):
            lines.append('  - Retrieved reviewer quotation: '+row['source_quote'])
        if rank:=row.get('source_rank'):
            if rank.get('historical_question'):
                lines.append('  - Historical question used for retrieval: '+rank['historical_question'])
            lines.append(f"  - Retrieval check: the assigned historical question ranks {rank['rank']} of {rank['compared']} for the proposed wording.")
        lines.extend(['  - Historical reviewer: '+row['source'],'  - Evidence or revision decision: '+row.get('note','').strip()])
    return '\n'.join(lines)
