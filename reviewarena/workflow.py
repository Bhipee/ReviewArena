import asyncio,re
from datetime import date
from .consistency import check_manuscript
from .comparisons import comparison_reviews
from .investigation import investigate,cited_weaknesses
from .severity import check_rating
from .novelty import compare_contributions
from .kb import ROOT,outcomes,current_snapshot
from .model import generate,literature_query
from .tools import connect
from .protocol import protocol
from .named_works import verify_comparisons
from .settings import grounded_settings,check_setting_mentions
from .transfer import adapt_questions
from .claims import ground_claims,declared_limitations
from .paper import is_manuscript_title

def skill(name):
    return (ROOT/'skills'/name/'SKILL.md').read_text()

async def ask(task,**data):
    return await asyncio.to_thread(generate,task,data)

def chunks(pages,limit=22000):
    group=[];size=0
    for i,text in enumerate(pages,1):
        for start in range(0,len(text),limit):
            part=text[start:start+limit]
            if group and size+len(part)>limit:
                yield group
                group=[];size=0
            group.append({'page':i,'text':part});size+=len(part)
    if group:yield group

from .verifier import verify_many,passages,check_answer_scope
from .embedding import embed

REVIEWER_ROLES=('Theory and assumptions','Experiments and evaluation','Clarity and reproducibility')

def assign_findings(findings):
    from .embedding import embed
    from scipy.optimize import linear_sum_assignment
    import numpy as np
    groups=[[] for _ in REVIEWER_ROLES]
    if not findings:return groups
    specialties=embed(['Theoretical justification, identifiability, proofs, assumptions, causal attribution and guarantees.',
                       'Experimental design, ablation, baselines, data, metrics, computational cost, robustness and generalization.',
                       'Clarity of exposition, missing definitions, implementation detail, documentation and reproducibility.'])
    questions=[item['candidate']['category']+' '+(item['candidate'].get('transfer_question') or item['candidate']['critique_text']) for item in findings]
    similarity=embed(questions)@specialties.T
    slots=(len(findings)+2)//3
    utility=np.hstack([similarity-.03*level for level in range(slots)])
    for row,column in zip(*linear_sum_assignment(-utility)):
        groups[column%3].append(findings[row])
    return groups

async def inspect_manuscript(paper):
    pages=paper['pages']
    anchors=[{'page':i,'excerpt':m.group()} for i,page in enumerate(pages,1) for m in list(re.finditer(r'(?i)(?:limitations?:|we evaluate|we compare|we hypothesize|we assume|our experiments show).{20,360}',page))[:2]]
    sections=paper.get('sections',[])
    analysis=await ask("Identify up to five concrete scientific claims. Return claims (array of objects with text and claim_type), paper_type (brief research design), and settings (up to five objects with kind, name, page, quote). For settings, use kind dataset, baseline, model or metric; copy quote verbatim from the numbered page and include the setting name in the quote. Return an empty array for missing evidence.",
                       opening=[dict(page=i,text=text) for i,text in enumerate(pages[:2],1)],passages=anchors[:30],
                       sections=[{k:s[k] for k in ('heading','start_page','excerpt')} for s in sections[:24]])
    claims=analysis.get('claims',[])
    paper_type=analysis.get('paper_type') if isinstance(analysis.get('paper_type'),str) else ''
    if paper_type.casefold().strip() in ('research design','scientific','paper type','research paper','other'):paper_type=''
    settings=grounded_settings(analysis.get('settings'),pages)
    claims=[c for c in claims if isinstance(c,dict) and isinstance(c.get('text'),str) and c['text'].strip()]
    if not claims:
        recovered=await ask("Extract up to five concrete scientific claims about performance, efficiency, evaluation scope, theory or generalization. Use only supplied text. Return a JSON object with a claims array of objects having text and claim_type string fields.",opening=pages[:2],passages=anchors[:30])
        claims=[c for c in recovered.get('claims',[]) if isinstance(c,dict) and isinstance(c.get('text'),str) and c['text'].strip()]
    if not claims:raise ValueError('Claim extraction returned no usable claim.')
    claims,settings=await asyncio.gather(
        ground_claims(paper,claims[:5],ask),
        check_setting_mentions(analysis.get('settings'),pages,settings,ask))
    if not claims:raise ValueError('Could not substantiate a scientific claim from the manuscript text.')
    return claims,paper_type,settings


def select_claim_candidates(per_claim,k):
    """Keep the top families and cover distinct claims at minimum loss in retrieval score."""
    import numpy as np
    from scipy.optimize import linear_sum_assignment
    best={}
    for hits in per_claim:
        for family,row in hits.items():
            if family not in best or row['score']>best[family]['score']:
                best[family]=row
    families=sorted(best,key=lambda family:-best[family]['score'])[:k]
    if not families:return []
    chosen={family:best[family] for family in families}
    # A dummy column lets a claim abstain when none of its retrieved families is available.
    n=len(per_claim)
    cost=np.full((n,len(families)+n),2.0*(n+1))
    cost[:,len(families):]=n+1
    for i,hits in enumerate(per_claim):
        for j,family in enumerate(families):
            if family in hits:cost[i,j]=best[family]['score']-hits[family]['score']
    for i,j in zip(*linear_sum_assignment(cost)):
        if j<len(families):chosen[families[j]]=per_claim[i][families[j]]
    return sorted(chosen.values(),key=lambda row:-row['score'])


async def ranked_candidates(kb,claims,paper_type,k):
    if not 1<=k<=25:
        raise ValueError('Choose between 1 and 25 candidate families')
    per_claim=[]
    for claim in claims:
        hits=await kb('search_triggers',query=claim['text'],claim_type=claim.get('claim_type',''),paper_type=paper_type,k=k)
        per_claim.append({(r.get('family') or r['category']):dict(r,matched_claim=claim['text'],matched_claim_page=claim.get('page'))
                          for r in hits})
    return await adapt_questions(select_claim_candidates(per_claim,k),ask)


SCORE_LABELS = {
    'ICLR': {1: 'Strong reject', 3: 'Reject', 5: 'Borderline reject',
             6: 'Borderline accept', 8: 'Accept', 10: 'Strong accept'},
    'NeurIPS': {1: 'Strong reject', 2: 'Reject', 3: 'Borderline reject',
                4: 'Borderline accept', 5: 'Accept', 6: 'Strong accept'},
}

def overall_score_guide(venue):
    labels=SCORE_LABELS[venue]
    scale='. '.join(f'{venue} score {score} means {label.lower()}' for score,label in labels.items())
    lower=next(n for n,label in labels.items() if label=='Borderline reject')
    upper=next(n for n,label in labels.items() if label=='Borderline accept')
    return f'{scale}. Borderline accept is score {upper}. Borderline reject is score {lower}. For this venue, score 5 means {labels[5].lower()}.'


RUBRICS={
    'ICLR':dict(scores=tuple(SCORE_LABELS['ICLR']),criteria=('soundness','presentation','contribution'),
                source='https://iclr.cc/Conferences/2025/ReviewerGuide'),
    'NeurIPS':dict(scores=tuple(SCORE_LABELS['NeurIPS']),criteria=('quality','clarity','significance','originality'),
                   source='https://neurips.cc/Conferences/2025/ReviewerGuidelines'),
}


def rubric_rating(value,allowed):
    if isinstance(value,str) and re.fullmatch(r'\d+',value.strip()):
        value=int(value.strip())
    return value if type(value) is int and value in allowed else None


async def chair_recommendation(venue,reports,claims=None,decision=None,novelty=None):
    findings=[]
    seen=set()

    def add(kind,statement,pages=(),evidence=()):
        if not isinstance(statement,str) or not statement.strip() or statement in seen:
            return
        seen.add(statement)
        pages=pages if isinstance(pages,(list,tuple)) else [pages]
        finding=dict(id=len(findings)+1,kind=kind,statement=statement,
                     pages=sorted({p for p in pages if type(p) is int and p>0}))
        quotes=[e['quote'] for e in evidence if isinstance(e,dict) and e.get('page') and e.get('quote')]
        if quotes:
            finding['manuscript_evidence']=quotes[:3]
        findings.append(finding)

    reviewers=[]
    for reviewer in reports:
        report=reviewer['report']
        reviewers.append(dict(role=reviewer['role'],score=report.get('score'),summary=report.get('summary')))
        for item in report.get('manuscript_conflicts',[]):
            if item['kind']=='scope_check':
                continue
            add(item['kind'],item['issue'],[source['page'] for source in item['evidence']])
        for field,kind in [('weaknesses','reviewer concern'),('strengths','reviewer strength')]:
            entries=report.get(field,[])
            for item in entries if isinstance(entries,list) else [entries]:
                if isinstance(item,dict):
                    add(kind,item.get('issue') or item.get('strength') or item.get('text'),item.get('pages') or [],item.get('evidence') or [])
                else:
                    add(kind,item)
    for row in novelty or []:
        if row['status'] in ('overlapping','distinct'):
            kind='reviewer strength' if row['status']=='distinct' else 'reviewer concern'
            statement=f"Compared with {row['title']}: {row['comparison']}"
            if row.get('validation'):
                statement+=' Manuscript evidence: '+row['validation']
            elif row['status']=='distinct':
                statement+=' This comparison establishes a technical difference; its separate performance effect is unverified.'
            add(kind,statement,[row['page'],row.get('validation_page')])
    if not findings:
        for reviewer in reviewers:
            add('reviewer assessment',reviewer['summary'])
    if not findings:
        raise ValueError('The area chair needs a readable reviewer finding.')
    if claims:
        async def assess(finding):
            if finding['kind']=='protocol':
                # Upstream protocol checks compare conflicting instructions for the same step.
                return dict(**finding,reach='replication',mechanism=(
                    "The tested procedure is ambiguous. Explain which implementation choice a reader "
                    "must make and which reported outcome they therefore cannot independently attribute to that procedure."))
            result=await ask(
                "Assess the reach of this single observation for the manuscript's central claim. "
                "First identify the specific procedure, comparison or metric affected by the observation. "
                "Then state what the central claim measures. Return reach=central if the observation "
                "directly supports or contradicts the main outcome. Return reach=replication if two incompatible descriptions of the method leave a necessary implementation, dataset or evaluation choice unknown, even if their numerical effect is unknown. For evidence limited to another setting or a discrepancy confined "
                "to another metric or a vague reviewer opinion, return reach=limited. "
                "Return JSON with reach and a one-sentence mechanism naming both the affected step and outcome.",
                claims=claims,observation=finding['statement'])
            if result.get('reach') in ('central','replication','limited') and isinstance(result.get('mechanism'),str):
                return dict(**finding,reach=result['reach'],mechanism=result['mechanism'])
        ranked=await asyncio.gather(*(assess(f) for f in findings))
        for f in filter(None,ranked):
            findings[f['id']-1]=f
    prompt=skill('area-chair')
    if decision not in ('Accept','Reject'):
        for attempt in range(2):
            verdict=await ask("Make a simulated area-chair decision using the claims, findings and reviewer reports. "
                              "Weigh the best evidence for the claimed contribution against any limitation affecting that claim. A scope limit only constrains conclusions outside that scope. Judge the substance, not the count of findings. Return recommendation (Accept or Reject).",
                              venue=venue,overall_score_meanings=overall_score_guide(venue),claims=claims or [],findings=findings,reviewers=reviewers)
            decision=str(verdict.get('recommendation','')).strip().capitalize()
            if decision in ('Accept','Reject'):
                break
        else:
            raise ValueError('The area chair did not choose Accept or Reject.')
    if decision=='Reject':
        concerns=[f for f in findings if f['kind']!='reviewer strength']
        candidates=([f for f in concerns if f.get('reach') in ('central','replication')]
                    or concerns)
        if not candidates:
            summaries=[r['summary'] for r in reviewers if isinstance(r['summary'],str)]
            selection=await ask("Extract the decisive substantive limitation from the reviewer summaries. "
                                "Copy a supporting clause exactly as quote, or an empty quote if none exists.",
                                summaries=summaries)
            quote=selection.get('quote')
            if not isinstance(quote,str) or not quote.strip() or not any(quote in s for s in summaries):
                raise ValueError('The reviews contain no identifiable concern supporting rejection.')
            candidates=[dict(id=len(findings)+1,kind='reviewer concern',statement=quote,pages=[])]
    else:
        candidates=[f for f in findings if f['kind']=='reviewer strength']
        if not candidates:
            summaries=[r['summary'] for r in reviewers if isinstance(r['summary'],str)]
            selection=await ask("Extract the strongest affirmative evidence in the reviewer summaries. "
                                "Copy exactly one supporting clause as quote, excluding caveats. "
                                "If no affirmative evidence is present, return an empty quote.", summaries=summaries)
            quote=selection.get('quote')
            if not isinstance(quote,str) or not quote.strip() or not any(quote in s for s in summaries):
                raise ValueError('The reviews contain no identifiable supporting evidence for acceptance.')
            candidates=[dict(id=len(findings)+1,kind='reviewer strength',statement=quote,pages=[])]
        prompt=("Write the reason for acceptance. Pick the best affirmative evidence and explain what "
                "scientific contribution it establishes and why that contribution merits publication. "
                "Write impact as the completion of 'I recommend acceptance because ...'. Lead with the "
                "contribution. Leave out the weakness list and proposed revisions. Use only supplied facts. "
                "Return JSON with finding_id (one listed integer) and impact (the because-clause).")
    for attempt in range(2):
        response=await ask(prompt,venue=venue,decision=decision,claims=claims or [],findings=candidates)
        impact=response.get('impact')
        ref=rubric_rating(response.get('finding_id'),[f['id'] for f in candidates])
        if ref and isinstance(impact,str) and impact.strip() and '?' not in impact:
            finding=next(f for f in candidates if f['id']==ref)
            if finding.get('manuscript_evidence'):
                finding=dict(finding,statement=' '.join(finding['manuscript_evidence']))
            pages=', '.join(map(str,finding['pages']))
            prefix=f"(p. {pages}) " if pages else ''
            reason=impact.strip()
            if decision=='Accept':
                reason=re.sub(r'^\s*(?:I |we )?recommend acceptance because\s+|^because\s+', '',reason,flags=re.I)
                if not reason:
                    continue
                if re.match(r'^(The|This|These|Across|In|It)\b',reason):
                    reason=reason[0].lower()+reason[1:]
                reason='I recommend acceptance because '+reason
            return dict(recommendation=decision,summary=reason+' '+prefix+finding['statement'],
                        decisive_finding=finding,impact=reason,rationale_version=2)
        prompt+=' Supply one listed finding_id and a plain declarative impact string.'
    raise ValueError('The area chair did not return a decision linked to a finding and its impact.')


async def run_review(paper,venue="ICLR",method="D",before=None,progress=None,prepared_reading=None,on_stage=None):
    if method not in 'ABCD' or len(method)!=1:raise ValueError("Unknown evaluation method")
    if venue not in ('ICLR','NeurIPS'):raise ValueError("Unknown venue")
    def stage(units,label):
        if on_stage:
            on_stage(dict(fraction=units/8,label=label))

    stage(0,"Reading manuscript claims and settings")
    snapshot=current_snapshot()
    stamp=protocol(method,venue,snapshot)
    before=before or date.today().isoformat()
    logs=[];checked=[];contexts=[];sources=[];novelty=[];pages=paper['pages']
    if prepared_reading is None:
        claims,paper_type,settings=await inspect_manuscript(paper)
    else:
        if not paper.get('hash') or prepared_reading.get('manuscript_sha256')!=paper['hash']:
            raise ValueError('The saved reading belongs to different PDF bytes.')
        claims=prepared_reading['claims']
        settings=prepared_reading['settings']
        paper_type=prepared_reading['paper_type']
        for item in claims+settings:
            page=item['page']
            quote=item.get('text') or item['quote']
            if not quote or not 1<=page<=len(pages) or quote not in pages[page-1]:
                raise ValueError('The saved reading contains an unverified manuscript passage.')
    stage(1,"Retrieving historical reviews")
    async with connect('reviewkb',logs,snapshot) as kb:
        if method=='B':contexts=await kb('similar_context',query=' '.join(pages[:1]),k=5)
        if method in ('C','D'):
            candidates=await ranked_candidates(kb,claims,paper_type,20)
            if progress:progress(f"Retrieved {len(candidates)} historical critique types")
            if method=='D':
                active=sum(bool(c.get('target_question',True)) for c in candidates)
                def verified(n):
                    stage(2+n/max(active,1),f"Checking manuscript evidence · {n}/{active} questions")
                verified(0)
                checked=await asyncio.to_thread(verify_many,paper,candidates,on_verified=verified)
            else:
                checked=[dict(candidate=r,status='hypothesis' if r['target_question'] else 'not transferred',evidence=[]) for r in candidates]
    if method=='D':
        stage(3,"Checking related papers and prior work")
        contexts=await asyncio.to_thread(comparison_reviews,claims,pages[0],before)
        query=await asyncio.to_thread(literature_query,claims)
        async with connect('scholar',logs) as scholar:
            await verify_comparisons(checked,before,scholar,ask)
            if query:
                try:
                    hits=await scholar('search_papers',query=query,before=before,limit=5)
                    sources=[r for r in hits if not is_manuscript_title(r['title'],pages[0])][:3]
                except RuntimeError:pass
        stage(3.25,"Comparing claimed contributions with prior work")
        novelty=await compare_contributions(paper,claims,sources,before,ask)
    kept=[r for r in checked if r['status'] in ('valid','hypothesis')]
    paper_context=[]
    if method in ('A','B'):
        for group in chunks(pages):
            paper_context.append(await ask("Summarize scientific claims, experimental support and limitations with page numbers. Return a JSON object with a field notes containing three short strings.",pages=group))
    if method=='D':
        paper_context=[dict(page=s['start_page'],heading=s['heading'],excerpt=s['excerpt'])
                       for s in paper.get('sections',[]) if s['excerpt'] and s['heading'].casefold() not in ('references','bibliography')][:28]
        paper_context.extend(dict(page=c['page'],excerpt=c['quote']) for c in paper.get('captions',[])[:8])
        for n,row in enumerate(paper_context,1):
            row['id']=f'excerpt-{n}'
    conflicts=[]
    if method=='D':
        stage(3.5,"Cross-checking methods, results and appendices")
        conflicts=await check_manuscript(paper,ask)
    groups=await asyncio.to_thread(assign_findings,kept)
    completed_reviewers=0
    stage(4,"Investigating and scoring · 0/3 reviewers finished")
    async def review(i,role):
        nonlocal completed_reviewers
        assigned=[dict(critique_id=r['candidate']['id'],category=r['candidate']['category'],historical_issue=r['candidate']['critique_text'],target_question=r['candidate'].get('target_question'),current_evidence=r['evidence'],status=r['status']) for r in groups[i]]
        rubric=RUBRICS[venue]
        if method=='D':
            shared=[dict(id=f'lead-{n+1}.{j+1}',page=e['page'],quote=e['quote'])
                    for n,lead in enumerate(assigned) for j,e in enumerate(lead['current_evidence'])]
            trace=await investigate(role,paper,claims,[r['target_question'] for r in assigned],before,ask)
            guidance=("Assess the strongest supported contribution and the most consequential supported limitation "
                      "against the same question: what can the reader conclude within the claimed setting? "
                      "State the decisive manuscript evidence and page. Explain what a limitation changes: "
                      "the main result, its reproducibility, or only its scope. Credit solid evidence within scope. "
                      "If a necessary comparison or premise fails, explain which claim loses support. "
                      "Optional leads may be ignored or rebutted. Do not invent a strength or flaw to fill a field. "
                      "Assign the venue rating that best fits the balance of evidence.")
            form=dict(summary="Briefly explain why the evidence supports the selected rating, citing a manuscript page.",
                      score=list(rubric['scores']),confidence="integer 1 to 5",
                      criteria={name:"integer 1 to 4 or null" for name in rubric['criteria']},
                      strengths=["specific supported contribution and its page; empty list if none"],
                      weaknesses=[dict(issue="specific supported limitation; empty list if none",evidence_ids=["source IDs"])],
                      questions=["material unresolved question; empty list if none"])
            report=await ask(f"Assess the submitted manuscript as the specified reviewer. Give an overall integer rating from the supplied scale even if there are no historical matches. Higher is better. {guidance} Use contribution_comparisons for originality within the compared works. Shared components and insufficient evidence do not warrant a novelty penalty. Historical reviews only illustrate standards. Return one flat JSON object following the form. Write summary as plain text and select exactly one score.",
                             venue=venue,overall_score_meanings=overall_score_guide(venue),role=role,form=form,claims=claims,settings=settings,manuscript=paper_context,
                             investigation=trace,optional_source_passages=shared,optional_leads=assigned,cross_checks=conflicts,contribution_comparisons=novelty,other_papers=contexts)
            if len(report)==1:
                nested=next(iter(report.values()))
                if isinstance(nested,dict) and 'score' in nested:
                    report=nested
        else:
            report=await ask(skill(venue.lower()+'-reviewer'),overall_score_meanings=overall_score_guide(venue),role=role,claims=claims,settings=settings,assigned=assigned,background=contexts,prior_publications=sources,manuscript_notes=paper_context,method=method)
        raw_score=report.get('score')
        report['score']=rubric_rating(raw_score,rubric['scores'])
        if method=='D' and (report['score'] is None or not isinstance(report.get('summary'),str) or not report['summary'].strip()):
            revised=await ask(f"Assign an overall manuscript score independently of historical matches. Choose exactly one integer from allowed_scores. {guidance} Return JSON with score (integer) and rationale (plain string, one sentence citing a manuscript page) grounded in the supplied manuscript evidence.",
                              role=role,overall_score_meanings=overall_score_guide(venue),allowed_scores=rubric['scores'],claims=claims,settings=settings,notes=paper_context,cross_checks=conflicts,investigation=trace,optional_source_passages=shared,optional_leads=assigned,contribution_comparisons=novelty)
            report['score']=rubric_rating(revised.get('score'),rubric['scores'])
            if report['score'] is None:
                raise ValueError(f"{role} returned no valid {venue} rating after two attempts.")
            rationale=revised.get('rationale')
            if not isinstance(rationale,str) or not rationale.strip():
                raise ValueError(f"{role} returned no readable rationale for its rating.")
            report['summary']=rationale
        if report['score'] is None and raw_score is not None:
            report['score_status']='Model returned a value outside the venue scale'
        report['confidence']=rubric_rating(report.get('confidence'),range(1,6))
        criteria=report.get('criteria')
        if not isinstance(criteria,dict):criteria={}
        report['criteria']={name:rubric_rating(criteria.get(name,report.get(name)),range(1,5)) for name in rubric['criteria']}
        if method=='D':
            report['investigation']=trace
            excerpts=[dict(id=row['id'],page=row['page'],quote=row['excerpt']) for row in paper_context]
            report['weaknesses']=cited_weaknesses(report.get('weaknesses'),trace,shared+excerpts)
            await check_rating(report,role,claims,conflicts,pages,SCORE_LABELS[venue],ask)
        else:
            for field in list(report):
                if field.lower().startswith('weak') and field!='weaknesses':
                    report.setdefault('weaknesses',report.pop(field))
        if method=='D' and conflicts:
            report['manuscript_conflicts']=conflicts
        if progress:progress({'role':role,'report':report})
        completed_reviewers+=1
        stage(4+completed_reviewers,f"Investigating and scoring · {completed_reviewers}/3 reviewers finished")
        return dict(role=role,report=report)
    reports=await asyncio.gather(*(review(i,role) for i,role in enumerate(REVIEWER_ROLES)))
    stage(7,"Synthesizing the three reviews")
    try:
        meta=await chair_recommendation(venue,reports,claims,novelty=novelty)
    except ValueError as exc:
        meta=dict(error=str(exc))
    return dict(method=method,venue=venue,contribution_comparisons=novelty,manuscript_conflicts=conflicts,rubric=dict(year=2025,score_labels=SCORE_LABELS[venue],**RUBRICS[venue]),comparison_reviews=contexts if method=='D' else [],request=dict(manuscript_sha256=paper.get('hash'),before=before),protocol=stamp,claims=claims,declared_limitations=declared_limitations(paper),paper_type=paper_type,settings=settings,reviews=reports,meta_review=meta,checked=checked,historical_outcome=outcomes([r['candidate']['category'] for r in kept],[r['candidate']['severity'] for r in kept],snapshot) if method=='D' else None,tools=logs,sources=sources)

async def response_evidence(critique,blocks,vectors):
    query=(await asyncio.to_thread(embed,[critique]))[0]
    order=(vectors@query).argsort()[::-1][:12]
    choices=[dict(ref=n+1,**blocks[i]) for n,i in enumerate(order)]
    prompt=("Identify passages from the target manuscript that bear directly on this reviewer question. "
            "For a passage answering the question choose addresses; for one explicitly demonstrating a shortcoming choose supports. "
            "Return up to two entries in evidence, each with ref (integer), role (addresses or supports), and reason (one short sentence). "
            "Return an empty list when none of the supplied excerpts is sufficient. Cite only numbered references.")
    answer=await ask(prompt,question=critique,passages=choices)
    selected={}
    items=answer.get('evidence')
    for item in items if isinstance(items,list) else []:
        if not isinstance(item,dict):continue
        ref=item.get('ref')
        if type(ref) is not int or not 1<=ref<=len(choices) or item.get('role') not in ('addresses','supports'):continue
        source=choices[ref-1]
        role=item['role']
        anchor=source['quote']
        reason=str(item.get('reason',''))
        if role=='addresses':
            coverage,anchor,reason=await asyncio.to_thread(check_answer_scope,critique,anchor)
            if coverage=='insufficient':continue
            if coverage=='partial':role='partially addresses'
        selected[ref]=dict(page=source['page'],quote=anchor,reason=reason,role=role)
    return list(selected.values())[:2]


async def rebuttal(paper,text):
    logs=[];responses=[]
    if not isinstance(text,str) or not text.strip():
        raise ValueError("Enter at least one reviewer comment.")
    parts=await ask("Identify the distinct reviewer requests. Return {concerns:[{quote:string,category:string}]}. "
                    "For quote copy a complete question or sentence verbatim from the review. Give each a short descriptive category. "
                    "Keep distinct requests separate and preserve their order.",review=text)
    concerns=[]
    proposed=parts.get('concerns')
    for item in proposed if isinstance(proposed,list) else []:
        quote=item.get('quote') if isinstance(item,dict) else item
        if not isinstance(quote,str) or not quote.strip() or quote.strip() not in text:continue
        quote=quote.strip()
        if any(q==quote for q,_ in concerns):continue
        label=item.get('category') if isinstance(item,dict) else ''
        concerns.append((quote,label.strip() if isinstance(label,str) else ''))
    # Keep explicit questions even when the model omits one from a multi-question review.
    for sentence in re.split(r'(?<=[?.!])\s+|\n+',text):
        sentence=sentence.strip()
        if sentence.endswith('?') and not any(sentence in quote for quote,_ in concerns):
            concerns=[pair for pair in concerns if pair[0] not in sentence]
            concerns.append((sentence,''))
    if not concerns:
        concerns=[(para.strip(),'') for para in re.split(r'\n\s*\n',text.strip()) if para.strip()]
    concerns.sort(key=lambda item:text.index(item[0]))
    blocks=passages(paper)
    vectors=await asyncio.to_thread(embed,[b['quote'] for b in blocks]) if blocks else None
    async with connect('reviewkb',logs,current_snapshot()) as kb:
        for critique,category in concerns:
            history=await kb('search_critiques',query=critique,k=5,require_reply=True)
            evidence=await response_evidence(critique,blocks,vectors) if blocks else []
            # Historical replies guide action selection; never copy their measurements into the author's draft.
            strategies=sorted({r['reply_strategy'] for r in history if r.get('reply_strategy')})
            outcomes_by_strategy={}
            for name in strategies:
                examples=[r for r in history if r.get('reply_strategy')==name]
                observed=[r['resolved'] for r in examples if r.get('resolution_quote') and type(r.get('resolved')) is bool]
                outcomes_by_strategy[name]=dict(replies=len({r['reply_id'] for r in examples if r.get('reply_id')}),concerns=len(examples),known_outcomes=len(observed),resolved=sum(observed))
            plan=await ask(skill('rebuttal-writer')+" Return a JSON object with action (clarify, experiment, or revise), evidence_index (one-based integer, or zero), planned_step (an imperative instruction for future work, one sentence), priority (1-3), and effort. Never output a completed experiment or numerical result.",current_concern=critique,current_manuscript_evidence=evidence,historical_response_strategies=strategies)
            action=plan.get('action')
            if action not in ('clarify','experiment','revise'):action='revise'
            ref=plan.get('evidence_index',0)
            quote=evidence[ref-1] if type(ref) is int and 0<ref<=len(evidence) else None
            if action=='clarify' and (not quote or quote['role']!='addresses'):action='revise'
            lines=["Thank you for raising the following point: "+critique.rstrip('.')+"."]
            if quote:lines.append(f"Our manuscript states on page {quote['page']}: “{quote['quote']}”")
            step=str(plan.get('planned_step','')).strip()
            if not step or any(x in step.lower() for x in ['we have','we found','our results show','we conducted','we demonstrate']):step='Address the reviewer’s question about '+critique.rstrip('.')+'.'
            lines.append("Planned revision: "+step)
            answer=dict(action=action,draft=' '.join(lines),experiment=step if action=='experiment' else '',priority=plan.get('priority',2),effort=plan.get('effort','To estimate'),historical_strategies=strategies)
            responses.append(dict(critique=critique,category=category,answer=answer,evidence=evidence,history=history,strategy_outcomes=outcomes_by_strategy))
    return dict(responses=responses,tools=logs)
