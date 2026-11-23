"""Package exact public lab runs with their questions and document fingerprints."""
import hashlib
import json
from run import DATA,write
from lab_literature import TOPICS

QUESTION='Which findings on Auto-CoT should we discuss at our next research meeting?'

def package(mode,question,ids,source,result,manuscript=None,meeting_records=None):
    docs={f'{paper}.pdf': hashlib.sha256((DATA/'iclr2023'/f'{paper}.pdf').read_bytes()).hexdigest() for paper in ids}
    write(DATA/'lab-replays'/(mode+'.json'),dict(mode=mode,question=question,documents=docs,manuscript=manuscript,meeting_records=meeting_records or {},
          source=str(source.relative_to(DATA)),source_sha256=hashlib.sha256(source.read_bytes()).hexdigest(),result=result))

if __name__=='__main__':
    path=DATA/'eval-lab/00.json'
    row=json.loads(path.read_text())
    package('question',row['reference']['question'],TOPICS,path,row['rag'])
    one=['5NTt8GFjUHkr']
    for mode in ('reviewer-2',):
        path=DATA/'lab-pilot'/(mode+'-structured.json')
        if path.exists():package(mode,QUESTION,one,path,json.loads(path.read_text()))
    path=DATA/'lab-pilot/weekly-brief-with-record.json'
    if path.exists():
        row=json.loads(path.read_bytes())
        package('weekly-brief',row['question'],one,path,row['result'],meeting_records=row['meeting_records'])
    path=DATA/'eval-lab-literature-v3'/one[0]/'scholar-raw.json'
    if path.exists():
        row=json.loads(path.read_text())
        package('related-work-gap',row['question'],one,path,row['answer'],one[0]+'.pdf')
