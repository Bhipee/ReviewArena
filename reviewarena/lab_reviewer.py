"""Produce source-linked reviewer notes from sentences in the selected research documents."""
import asyncio
import json
import os
import re
from .model import model_post

CONTRIBUTION=re.compile(r'\b(?:we (?:introduce|present|propose|develop|demonstrate|show|find)|our (?:main )?(?:contribution|results? (?:show|indicate)))\b',re.I)
LIMITATION=re.compile(r'\b(?:our (?:main |current )?limitation|one limitation of (?:our|this)|our (?:approach|model|method|study|system) (?:is limited|fails|cannot|struggles|relies)|we (?:did not|could not|were unable|leave .{0,70}future work)|we only (?:evaluate|study|consider))\b',re.I)


def passages_with_sentences(passages,pattern):
    rows=[];seen=set()
    for passage in passages:
        for match in re.finditer(r'(?:^|(?<=[.!?])\s+)([^.!?]{25,650}[.!?])(?=\s|$)',passage['text']):
            quote=match[1].strip()
            if pattern.search(quote) and quote not in seen:
                rows.append((passage,quote));seen.add(quote)
    return rows[:16]


def complete(task,payload,limit):
    response=model_post(os.getenv('REVIEWARENA_API_URL','http://127.0.0.1:8766/v1').rstrip('/')+'/chat/completions',
        headers={'Authorization':'Bearer '+os.getenv('REVIEWARENA_API_KEY','local')},
        json={'model':os.getenv('REVIEWARENA_MODEL','default_model'),'temperature':0,'max_tokens':limit,
              'messages':[{'role':'system','content':task},{'role':'user','content':json.dumps(payload,ensure_ascii=False)}]},timeout=(10,180))
    response.raise_for_status()
    return response.json()['choices'][0]['message']['content'].strip()


async def review(question,passages,instructions):
    points=[];anchors=[]
    for heading,pattern,meaning in [('Contributions',CONTRIBUTION,'a contribution of this manuscript'),
                                    ('Weaknesses',LIMITATION,'a limitation of the authors’ own work')]:
        choices=passages_with_sentences(passages,pattern)
        selected=None
        if choices:
            response=await asyncio.to_thread(complete,instructions+' Select one numbered quote that explicitly describes '
                +meaning+'. Exclude descriptions of previous methods. If none fits respond 0. Output only the integer.',
                dict(meeting_topic=question,quotes={str(i+1):q for i,(_,q) in enumerate(choices)}),10)
            match=re.fullmatch(r'\s*(\d+)[.)]?\s*',response)
            if match and 1<=int(match[1])<=len(choices):selected=choices[int(match[1])-1]
        if selected:
            p,quote=selected
            points.append(dict(heading=heading,text='The authors state: “'+quote+'”',sources=[p]))
            anchors.append(selected)
        else:
            points.append(dict(heading=heading,text='The checked passages did not establish '+meaning+'.',sources=[]))
    if anchors:
        passage,quote=anchors[0]
        response=await asyncio.to_thread(complete,'Act as a supervisor. Ask one concrete experimental or methodological question '
            'about the quoted claim. It must be answerable by the authors. Give just one question ending in a question mark. '
            'Do not ask what to discuss at a meeting.',dict(claim=quote),100)
        questions=re.findall(r'[^?!\n]{8,420}\?',response)
        question_text=questions[0].strip().lstrip('- ') if questions else 'What measurement would most directly test this claim?'
        points.append(dict(heading='Questions for the author',text=question_text+'\n\nClaim to discuss: “'+quote+'”',sources=[passage]))
    else:
        points.append(dict(heading='Questions for the author',text='Which central claim should the group examine, and where is its supporting evidence?',sources=[]))
    return dict(points=points,external=[],tools=[])
