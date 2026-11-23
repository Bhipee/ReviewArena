"""Produce the public weekly brief from a measured project update and a background paper."""
import asyncio
import hashlib
import json
from run import DATA,write
from lab_replays import package
from reviewarena.lab import run_lab
from reviewarena.library import document

async def main():
    metrics=DATA/'metrics/lab-pages.json'
    stats=json.loads(metrics.read_bytes())
    content=(f"We completed the evidence-retrieval evaluation on {stats['completed']} research questions. "
                    f"We found that {stats['citing_reference_page']} of the {stats['completed']} answers cited the reference document and page.\n"
                    f"Open question: Did the other {stats['completed']-stats['citing_reference_page']} answers cite an alternative passage that supports their claim?\n"
                    "Next step: Check those answers against their original PDF passages in the human citation audit.\n")
    digest=hashlib.sha256(content.encode()).hexdigest()
    note=DATA/'lab-pilot'/'meeting-records'/digest/'group-evaluation-note.md'
    note.parent.mkdir(parents=True,exist_ok=True)
    if not note.exists():note.write_text(content)
    if note.read_text()!=content:raise ValueError('Source record changed')
    question='What did the group complete in the evidence-retrieval evaluation, and what should we discuss next?'
    paper='5NTt8GFjUHkr.pdf'
    docs={paper:document(paper,(DATA/'iclr2023'/paper).read_bytes()),note.name:document(note.name,note.read_bytes())}
    result=await run_lab(question,docs,'weekly-brief',meeting_records=[note.name])
    completed=result['points'][0]
    if not completed['sources'] or any(p['file']!=note.name or p['text'] not in note.read_text() for p in completed['sources']):
        raise ValueError('The completed work did not resolve to a literal group record')
    sections={p['heading']:p for p in result['points']}
    supervisors=sections['Supervisor questions']['text'].splitlines()
    if len(supervisors)!=3 or any(not line.endswith('?') for line in supervisors):
        raise ValueError('The public brief did not produce three supervisor questions')
    if any(not sections[name]['sources'] for name in ('Open questions','Proposed next steps','Supervisor questions')):
        raise ValueError('A public planning item lacks a supporting source')
    records={note.name:dict(path=str(note.relative_to(DATA)),sha256=hashlib.sha256(note.read_bytes()).hexdigest())}
    path=DATA/'lab-pilot/weekly-brief-with-record.json'
    write(path,dict(question=question,result=result,meeting_records=records,metrics_sha256=hashlib.sha256(metrics.read_bytes()).hexdigest()))
    package('weekly-brief',question,[paper[:-4]],path,result,meeting_records=records)
    print(completed['text'],flush=True)
if __name__=='__main__':asyncio.run(main())
