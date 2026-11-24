"""Adapt each historical question to a specific, quoted claim in the new draft."""
import re
from difflib import SequenceMatcher
from .model import bounded_model_map


HISTORICAL_CHECK_WORKERS = 2

# Comparisons about message traffic require a claim about exchanging data.
COMMUNICATION = re.compile(r'\b(?:communicat\w*|bandwidth|network traffic|message passing|'
                           r'bytes (?:sent|received|transferred)|data transfer)\b',re.I)


EXCHANGE = re.compile(r'\b(?:send|sent|sends|receiv\w*|upload\w*|download\w*|transmit\w*|exchang\w*)'
                      r'\b.{0,45}\b(?:bits?|bytes?|packets?|messages?|updates?|gradients?|parameters?|'
                      r'clients?|nodes?|servers?)\b',re.I)


def supported_question_scope(claim,question):
    return not COMMUNICATION.search(question) or bool(COMMUNICATION.search(claim) or EXCHANGE.search(claim))


def copied_without_subject(question,historical,anchor):
    """Catch a reused historical question linked only by a generic phrase."""
    def words(value):
        return re.findall(r"[a-z0-9]+",value.casefold())
    similarity=SequenceMatcher(None,words(question),words(historical),autojunk=False).ratio()
    if similarity<.85:return False
    generic={'the','and','are','for','with','that','this','these','other','model','models',
             'method','methods','architecture','architectures','experiments','results','comparison'}
    return not any(w not in generic and len(w)>2 for w in words(anchor))


async def adapt_questions(candidates,ask):
    async def adapt_group(group):
        tasks=[dict(id=i,claim=c['matched_claim'],historical_question=c.get('transfer_question') or c['critique_text'])
               for i,c in enumerate(group,1)]
        response=await ask(
            'Which historical experimental or reasoning checks apply to the current claim? For each applicable '
            'check, write a neutral question using the current manuscript terminology. Preserve the substantive '
            'check. If a required premise is absent, omit the item. Do not transfer datasets, model names, '
            'metrics or settings unique to the historical question. Return {"questions":[{"id":1,'
            '"anchor":"literal phrase from current claim","question":"question including that phrase?"}]}.',
            items=tasks)
        proposed=response.get('questions')
        questions={}
        for row in proposed if isinstance(proposed,list) else []:
            if not isinstance(row,dict):continue
            i=row.get('id')
            if type(i) is not int or not 1<=i<=len(group):continue
            anchor=row.get('anchor')
            question=row.get('question')
            if not isinstance(anchor,str) or not isinstance(question,str):continue
            anchor=anchor.strip()
            claim=group[i-1]['matched_claim']
            if len(anchor)<5 or anchor not in claim:continue
            if anchor.casefold() not in question.casefold():
                # The model sometimes returns the full source sentence with a shorter quoted phrase.
                words=anchor.split()
                match=SequenceMatcher(None,[w.casefold() for w in words],question.casefold().split(),autojunk=False).find_longest_match()
                if match.size<2:continue
                phrase=' '.join(words[match.a:match.a+match.size])
                if not any(len(w)>=5 or w.isupper() for w in phrase.split()):continue
                anchor=phrase
            # Do not reuse names unique to the historical paper.
            names=re.findall(r'\b(?:[A-Z]{2,}[A-Za-z0-9-]*|[A-Z][a-z]+[A-Z][A-Za-z0-9-]*)\b',question)
            historical=tasks[i-1]['historical_question']
            names.extend(w for w in historical.split()[1:] if re.fullmatch(r'[A-Z][a-z]{3,}',w) and w in question)
            if any(name.casefold() not in claim.casefold() for name in names):continue
            if supported_question_scope(claim,question) and not copied_without_subject(question,historical,anchor):
                questions[i]=(question.strip(),anchor)
        for i,c in enumerate(group,1):
            c['target_question'],c['question_anchor']=questions.get(i,('', ''))

    batches=[candidates[i:i+5] for i in range(0,len(candidates),5)]
    await bounded_model_map(batches,adapt_group,limit=HISTORICAL_CHECK_WORKERS)

    selected=[c for c in candidates if c['target_question']]
    if selected:
        checks=[dict(id=i,source_claim=c['matched_claim'],historical_check=c.get('transfer_question') or c['critique_text'],
                     proposed_question=c['target_question']) for i,c in enumerate(selected,1)]
        review=await ask('Audit proposed questions. Keep an item only if it preserves the historical scientific check AND '
                         'the current quoted claim supplies the premise for applying that check. Reject a generic rewording '
                         'that drops the historical control, or a question introducing an unrelated outcome, dataset, or '
                         'experimental setting. Asking for a measurement to test the stated claim is allowed. Return '
                         '{"keep_ids":[1,2]} with integer IDs, or an empty list.',items=checks)
        keep=review.get('keep_ids')
        allowed={i for i in keep if type(i) is int} if isinstance(keep,list) else set()
        for i,c in enumerate(selected,1):
            if i not in allowed:
                c['target_question'],c['question_anchor']='',''
    return candidates
