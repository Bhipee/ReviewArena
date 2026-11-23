"""Resume historical annotation using the requested model and reasoning effort."""
import argparse,json,os,subprocess,tempfile
from collections import Counter
from pathlib import Path

import duckdb
from fetch import ROOT
from import_labels import verify

def label(prompt,output):
    with tempfile.TemporaryDirectory() as tmp:
        target=Path(tmp)/'result.json'
        cmd=['codex','exec','--ephemeral','--skip-git-repo-check','--sandbox','read-only','-C',tmp,'-m','gpt-6-luna','-c','model_reasoning_effort="xhigh"','--output-last-message',str(target),'-']
        subprocess.run(cmd,input=prompt,text=True,check=True,stdout=subprocess.DEVNULL,timeout=1800)
        text=target.read_text().strip().removeprefix('~~~json').removesuffix('~~~').strip()
        if text.startswith(chr(96)*3):
            text=text.split('\n',1)[1].rsplit(chr(96)*3,1)[0].strip()
        records=json.loads(text)
        if not isinstance(records,list):raise ValueError("Expected annotation array.")
        output.parent.mkdir(parents=True,exist_ok=True)
        temp=output.with_suffix('.tmp');temp.write_text(json.dumps(records,ensure_ascii=False,indent=2));temp.replace(output)

def pending_packets(data):
    """Give the next slot to the year with the fewest already reviewed manuscripts."""
    with duckdb.connect(str(data/'history.duckdb'),read_only=True) as db:
        years=dict(db.execute('select id, year from papers').fetchall())
    completed={p.stem for p in (data/'labels').glob('*.json')}
    scheduled=Counter(years[paper] for paper in completed)
    packets={}
    for directory in ('packets','packets-expanded'):
        for path in (data/directory).glob('*.json'):
            if path.stem not in completed:
                packets.setdefault(path.stem,path)
    queue=[]
    for paper,path in sorted(packets.items()):
        year=years[paper]
        queue.append((scheduled[year],year,paper,path))
        scheduled[year]+=1
    return [path for _,_,_,path in sorted(queue)]


def main(limit):
    data=ROOT/'data';prompt=(ROOT/'pipeline/label_prompt.txt').read_text();done=0
    directory=data/'labels'
    directory.mkdir(exist_ok=True)
    verify(directory)
    for f in pending_packets(data):
        dest=directory/f.name
        if dest.exists():continue
        with tempfile.TemporaryDirectory(dir=directory) as stage:
            candidate=Path(stage)/f.name
            label(prompt+'\n'+f.read_text(),candidate)
            verify(candidate)
            try:
                os.link(candidate,dest)
            except FileExistsError:
                verify(dest)
                continue
        done+=1
        if limit and done>=limit:break
if __name__=='__main__':
    parser=argparse.ArgumentParser();parser.add_argument('--limit',type=int)
    main(parser.parse_args().limit)
