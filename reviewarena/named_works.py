"""Check publications implicated by a target-specific missing-comparison criticism."""
import re

async def lookup_title(scholar,title,before):
    try:
        records=await scholar('resolve_paper_title',title=title,before=before)
    except RuntimeError:
        return 'lookup_error',None
    for record in records:
        published=record.get('published')
        if record.get('named_work_verified') and published and published<before:
            return 'confirmed',record
    return 'unconfirmed',None


async def resolve_title(scholar,title,before):
    _,record=await lookup_title(scholar,title,before)
    return record


async def verify_comparisons(checked,before,scholar,ask):
    comparison=re.compile(r'compar|baselines?|prior work|related work|benchmark',re.I)
    for item in checked:
        if item['status']!='valid':continue
        question=item['candidate'].get('target_question') or item['candidate'].get('transfer_question') or ''
        reason=item.get('reason','')
        if not comparison.search(question+' '+reason):continue
        result=await ask('Does this criticism allege an omitted comparison to a specific named publication or method? '
            'Return {"named":false,"works":[]} for general calls for baselines. Otherwise set named=true and return '
            'one object per implicated work with mention (exact substring of the criticism or its question) and title '
            '(the published title if known, otherwise the literal mention). Do not infer a named work from the topic.',
            criticism=reason,question=question)
        if result.get('named') is False:
            item['comparison_check']={'status':'general comparison request','works':[]}
            continue
        verified=[];failures=[]
        for work in result.get('works') or []:
            if not isinstance(work,dict):continue
            mention=work.get('mention');title=work.get('title')
            if not isinstance(mention,str) or not mention.strip() or mention not in reason+' '+question or not isinstance(title,str) or not title.strip():
                failures.append('Unattributed work');continue
            match=await resolve_title(scholar,title,before)
            if match:verified.append(dict(mention=mention,record=match))
            else:failures.append(mention)
        if verified and not failures:
            item['comparison_check']={'status':'verified before cutoff','works':verified}
        else:
            item['comparison_check']={'status':'named comparison unresolved','works':verified,'unresolved':failures}
            item['status']='unsubstantiated'
            item['reason']='The proposed named comparison could not be confirmed before the literature cutoff.'
